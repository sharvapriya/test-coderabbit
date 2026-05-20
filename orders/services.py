from dataclasses import dataclass
from decimal import Decimal

from django.db import transaction
from django.utils import timezone

from .models import (
    DeliveryAssignment,
    Order,
    OrderItem,
    OrderStatusHistory,
    Wallet,
    WalletTransaction,
)
from sellers.models import SellerPayout
from .utils.email import refund_processed_email


class OrderCancellationError(Exception):
    def __init__(self, message, *, status_code=400, code="order_cancellation_error"):
        super().__init__(message)
        self.message = message
        self.status_code = status_code
        self.code = code


@dataclass
class CancellationResult:
    order: Order
    refunded_amount: Decimal
    wallet_balance: Decimal


def _quantize_money(amount):
    return Decimal(amount or "0").quantize(Decimal("0.01"))


def _item_refund_amount(order_item, *, quantity_to_cancel):
    quantity_to_cancel = int(quantity_to_cancel or 0)
    if quantity_to_cancel <= 0:
        return Decimal("0.00")

    unit_price = Decimal(order_item.price or "0")

    if order_item.order.payment_method == Order.PAYMENT_WALLET:
        return _quantize_money(unit_price * quantity_to_cancel)

    if order_item.quantity <= 0:
        return Decimal("0.00")

    proportional_amount = (order_item.get_net_cost() * Decimal(quantity_to_cancel)) / Decimal(order_item.quantity)
    return _quantize_money(proportional_amount)


def get_wallet(user):
    if not user or not getattr(user, "is_authenticated", False):
        return None
    wallet, _ = Wallet.objects.get_or_create(user=user)
    return wallet


def get_wallet_balance(user):
    wallet = get_wallet(user)
    return wallet.balance if wallet else Decimal("0")


def calculate_wallet_usage(*, total_amount, wallet_balance, use_wallet):
    total_amount = total_amount or Decimal("0")
    wallet_balance = wallet_balance or Decimal("0")
    if total_amount < 0:
        total_amount = Decimal("0")
    if wallet_balance < 0:
        wallet_balance = Decimal("0")
    wallet_applied = min(total_amount, wallet_balance) if use_wallet else Decimal("0")
    remaining_amount = total_amount - wallet_applied
    if remaining_amount < 0:
        remaining_amount = Decimal("0")
    return wallet_applied, remaining_amount


def _record_wallet_transaction(*, wallet, amount, transaction_type, source, description="", order=None, return_request=None, metadata=None):
    return WalletTransaction.objects.create(
        wallet=wallet,
        order=order,
        return_request=return_request,
        transaction_type=transaction_type,
        source=source,
        amount=amount,
        balance_after=wallet.balance,
        description=description,
        metadata=metadata or {},
    )


def credit_wallet(*, user, amount, source, description, order=None, return_request=None, metadata=None):
    amount = Decimal(amount or "0")
    if amount <= 0 or not user:
        return Decimal("0"), None, None

    wallet, _ = Wallet.objects.select_for_update().get_or_create(user=user)
    wallet.balance += amount
    wallet.save(update_fields=["balance", "updated_at"])
    wallet_txn = _record_wallet_transaction(
        wallet=wallet,
        amount=amount,
        transaction_type=WalletTransaction.TYPE_CREDIT,
        source=source,
        description=description,
        order=order,
        return_request=return_request,
        metadata=metadata,
    )
    return amount, wallet, wallet_txn


def debit_wallet(*, user, amount, source, description, order=None, metadata=None):
    amount = Decimal(amount or "0")
    if amount <= 0 or not user:
        return Decimal("0"), None, None

    wallet, _ = Wallet.objects.select_for_update().get_or_create(user=user)
    if wallet.balance < amount:
        raise OrderCancellationError(
            "Wallet balance is insufficient for this purchase.",
            status_code=409,
            code="wallet_insufficient",
        )

    wallet.balance -= amount
    wallet.save(update_fields=["balance", "updated_at"])
    wallet_txn = _record_wallet_transaction(
        wallet=wallet,
        amount=amount,
        transaction_type=WalletTransaction.TYPE_DEBIT,
        source=source,
        description=description,
        order=order,
        metadata=metadata,
    )
    return amount, wallet, wallet_txn


def _lock_products(order_items):
    product_ids = {item.product_id for item in order_items}
    return {
        product.id: product
        for product in OrderItem._meta.get_field("product").related_model.objects.select_for_update().filter(
            id__in=product_ids
        )
    }


def _restore_inventory(order_items):
    products = _lock_products(order_items)
    for item in order_items:
        product = products[item.product_id]
        product.stock += item.quantity
        if product.stock > 0:
            product.available = True
        product.save(update_fields=["stock", "available"])


def _lock_order_context(order_id):
    order = (
        Order.objects.select_for_update()
        .select_related("user", "cancelled_by")
        .get(id=order_id)
    )
    order_items = list(
        order.items.select_for_update().select_related("product").all()
    )
    assignment = (
        DeliveryAssignment.objects.select_for_update()
        .filter(order=order)
        .first()
    )
    payouts = {
        payout.order_item_id: payout
        for payout in SellerPayout.objects.select_for_update().filter(order_item__order=order)
    }
    return order, order_items, assignment, payouts


def _resolve_order_status(order, order_items, assignment, payouts):
    if order.status in {
        Order.STATUS_CANCELLED,
        Order.STATUS_SHIPPED,
        Order.STATUS_OUT_FOR_DELIVERY,
        Order.STATUS_DELIVERED,
    }:
        return order.status

    active_items = [item for item in order_items if item.status != OrderItem.STATUS_CANCELLED]
    if not active_items:
        return Order.STATUS_CANCELLED

    payout_statuses = [payouts[item.id].delivery_status for item in active_items if item.id in payouts]

    if assignment and assignment.status == DeliveryAssignment.STATUS_DELIVERED:
        return Order.STATUS_DELIVERED
    if assignment and assignment.status == DeliveryAssignment.STATUS_OUT_FOR_DELIVERY:
        return Order.STATUS_OUT_FOR_DELIVERY
    if assignment and assignment.status == DeliveryAssignment.STATUS_PICKED_UP:
        return Order.STATUS_SHIPPED

    if any(status == SellerPayout.DELIVERY_DELIVERED for status in payout_statuses):
        return Order.STATUS_DELIVERED
    if any(status == SellerPayout.DELIVERY_OUT_FOR_DELIVERY for status in payout_statuses):
        return Order.STATUS_OUT_FOR_DELIVERY
    if any(
        status in {
            SellerPayout.DELIVERY_SHIPPED,
            SellerPayout.DELIVERY_HANDED_TO_HUB,
            SellerPayout.DELIVERY_AT_HUB,
        }
        for status in payout_statuses
    ):
        return Order.STATUS_SHIPPED
    if payout_statuses and all(status == SellerPayout.DELIVERY_PACKED for status in payout_statuses):
        return Order.STATUS_PACKED
    if assignment:
        return Order.STATUS_CONFIRMED
    return Order.STATUS_PLACED


def _refund_to_wallet(order, amount):
    if amount <= 0 or order.payment_method == Order.PAYMENT_COD or not order.paid or not order.user:
        return Decimal("0"), None

    refunded_amount, wallet, _ = credit_wallet(
        user=order.user,
        amount=amount,
        source=WalletTransaction.SOURCE_REFUND,
        description=f"Refund from Order #{order.id}",
        order=order,
        metadata={"order_id": order.id},
    )
    if refunded_amount > 0:
        order.wallet_amount_refunded = (order.wallet_amount_refunded or Decimal("0")) + refunded_amount
        order.save(update_fields=["wallet_amount_refunded", "updated_at"])
    return refunded_amount, wallet


def _calculate_refundable_amount(order, cancelled_items, *, remaining_active_items):
    refunded_items_total = sum(
        (
            _item_refund_amount(item, quantity_to_cancel=getattr(item, "_cancel_quantity", item.quantity))
            for item in cancelled_items
        ),
        Decimal("0"),
    )
    refunded_delivery_charge = Decimal("0")

    if not remaining_active_items:
        refunded_delivery_charge = order.delivery_charge or Decimal("0")

    return refunded_items_total + refunded_delivery_charge


def _record_history(order, *, from_status, to_status, actor=None, reason="", order_item=None, metadata=None):
    OrderStatusHistory.objects.create(
        order=order,
        order_item=order_item,
        from_status=from_status or "",
        to_status=to_status,
        changed_by=actor,
        reason=reason,
        metadata=metadata or {},
    )


@transaction.atomic
def cancel_order(*, order_id, actor, reason=""):
    try:
        order, order_items, assignment, payouts = _lock_order_context(order_id)
    except Order.DoesNotExist as exc:
        raise OrderCancellationError("Order not found.", status_code=404, code="order_not_found") from exc

    if order.status == Order.STATUS_CANCELLED:
        raise OrderCancellationError("Order is already cancelled.", status_code=409, code="already_cancelled")

    active_items = [item for item in order_items if item.status != OrderItem.STATUS_CANCELLED]
    if not active_items:
        raise OrderCancellationError("Order has no active items left to cancel.", status_code=409, code="no_active_items")

    current_status = _resolve_order_status(order, order_items, assignment, payouts)
    order.status = current_status
    if current_status == Order.STATUS_PARTIALLY_CANCELLED:
        current_status = Order.STATUS_CONFIRMED

    if not Order.is_cancellable_status(current_status):
        raise OrderCancellationError(
            f"Order cannot be cancelled once it is {current_status.replace('_', ' ')}.",
            status_code=409,
            code="order_not_cancellable",
        )

    refundable_amount = _calculate_refundable_amount(
        order,
        active_items,
        remaining_active_items=[],
    )
    try:
        refunded_amount, wallet = _refund_to_wallet(order, refundable_amount)
    except Exception as exc:
        raise OrderCancellationError(
            "Refund could not be added to wallet. Cancellation was not completed.",
            status_code=500,
            code="refund_failed",
        ) from exc

    _restore_inventory(active_items)

    cancelled_at = timezone.now()
    for item in active_items:
        item.status = OrderItem.STATUS_CANCELLED
        item.is_cancelled = True
        item.cancelled_at = cancelled_at
        item.cancelled_by = actor
        item.cancellation_reason = reason
        item.save(
            update_fields=[
                "status",
                "is_cancelled",
                "cancelled_at",
                "cancelled_by",
                "cancellation_reason",
            ]
        )
        _record_history(
            order,
            from_status=current_status,
            to_status=OrderItem.STATUS_CANCELLED,
            actor=actor,
            reason=reason,
            order_item=item,
            metadata={"scope": "item"},
        )

    previous_status = current_status
    order.status = Order.STATUS_CANCELLED
    order.is_cancelled = True
    order.cancelled_at = cancelled_at
    order.cancelled_by = actor
    order.cancellation_reason = reason
    order.total_amount = Decimal("0")
    order.save(
        update_fields=[
            "status",
            "is_cancelled",
            "cancelled_at",
            "cancelled_by",
            "cancellation_reason",
            "total_amount",
            "updated_at",
        ]
    )
    _record_history(
        order,
        from_status=previous_status,
        to_status=Order.STATUS_CANCELLED,
        actor=actor,
        reason=reason,
        metadata={
            "scope": "order",
            "refunded_amount": str(refunded_amount),
            "delivery_charge_refunded": str(order.delivery_charge or Decimal("0")),
        },
    )

    if refunded_amount > 0 and order.user:
        transaction.on_commit(lambda: refund_processed_email(order.user, order, refunded_amount))

    return CancellationResult(
        order=order,
        refunded_amount=refunded_amount,
        wallet_balance=wallet.balance if wallet else Decimal("0"),
    )


@transaction.atomic
def cancel_order_item(*, order_item_id, actor, reason="", quantity_to_cancel=None):
    try:
        order_item = (
            OrderItem.objects.select_for_update()
            .select_related("order", "product", "order__user")
            .get(id=order_item_id)
        )
    except OrderItem.DoesNotExist as exc:
        raise OrderCancellationError("Order item not found.", status_code=404, code="order_item_not_found") from exc

    order = (
        Order.objects.select_for_update()
        .select_related("user")
        .get(id=order_item.order_id)
    )
    order_items = list(order.items.select_for_update().select_related("product").all())
    assignment = DeliveryAssignment.objects.select_for_update().filter(order=order).first()
    payouts = {
        payout.order_item_id: payout
        for payout in SellerPayout.objects.select_for_update().filter(order_item__order=order)
    }

    if order_item.status == OrderItem.STATUS_CANCELLED:
        raise OrderCancellationError("Order item is already cancelled.", status_code=409, code="already_cancelled")

    quantity_to_cancel = int(quantity_to_cancel or order_item.quantity)
    if quantity_to_cancel <= 0:
        raise OrderCancellationError("Select at least one quantity to cancel.", status_code=400, code="invalid_cancel_quantity")
    if quantity_to_cancel > order_item.quantity:
        raise OrderCancellationError("Selected quantity exceeds ordered quantity.", status_code=400, code="invalid_cancel_quantity")

    current_status = _resolve_order_status(order, order_items, assignment, payouts)
    if not Order.is_cancellable_status(current_status):
        raise OrderCancellationError(
            f"Order item cannot be cancelled once the order is {current_status.replace('_', ' ')}.",
            status_code=409,
            code="order_item_not_cancellable",
        )

    remaining_active_items = [
        item
        for item in order_items
        if item.id != order_item.id and item.status != OrderItem.STATUS_CANCELLED
    ]
    if order_item.quantity > quantity_to_cancel:
        remaining_active_items = remaining_active_items + [order_item]
    order_item._cancel_quantity = quantity_to_cancel
    refundable_amount = _calculate_refundable_amount(
        order,
        [order_item],
        remaining_active_items=remaining_active_items,
    )
    try:
        refunded_amount, wallet = _refund_to_wallet(order, refundable_amount)
    except Exception as exc:
        raise OrderCancellationError(
            "Refund could not be added to wallet. Cancellation was not completed.",
            status_code=500,
            code="refund_failed",
        ) from exc

    cancelled_at = timezone.now()
    if quantity_to_cancel == order_item.quantity:
        _restore_inventory([order_item])
        order_item.status = OrderItem.STATUS_CANCELLED
        order_item.is_cancelled = True
        order_item.cancelled_at = cancelled_at
        order_item.cancelled_by = actor
        order_item.cancellation_reason = reason
        order_item.save(
            update_fields=[
                "status",
                "is_cancelled",
                "cancelled_at",
                "cancelled_by",
                "cancellation_reason",
            ]
        )
        cancelled_item = order_item
    else:
        cancelled_item = OrderItem.objects.create(
            order=order,
            product=order_item.product,
            variant=order_item.variant,
            price=order_item.price,
            gst_rate=order_item.gst_rate,
            gst_amount=order_item.gst_amount,
            quantity=quantity_to_cancel,
            status=OrderItem.STATUS_CANCELLED,
            is_cancelled=True,
            cancelled_at=cancelled_at,
            cancelled_by=actor,
            cancellation_reason=reason,
        )
        order_item.quantity -= quantity_to_cancel
        order_item.save(update_fields=["quantity"])
        _restore_inventory([cancelled_item])

    _record_history(
        order,
        from_status=current_status,
        to_status=OrderItem.STATUS_CANCELLED,
        actor=actor,
        reason=reason,
        order_item=cancelled_item,
        metadata={
            "scope": "item",
            "cancelled_quantity": quantity_to_cancel,
            "refunded_amount": str(refunded_amount),
            "delivery_charge_refunded": str((order.delivery_charge or Decimal("0")) if not remaining_active_items else Decimal("0")),
        },
    )

    previous_status = current_status
    has_remaining_active_items = bool(remaining_active_items)
    order.status = Order.STATUS_PARTIALLY_CANCELLED if has_remaining_active_items else Order.STATUS_CANCELLED
    order.is_cancelled = not has_remaining_active_items
    order.total_amount = order.get_total_cost()
    if not has_remaining_active_items:
        order.cancelled_at = cancelled_at
        order.cancelled_by = actor
        order.cancellation_reason = reason
    order.save(
        update_fields=[
            "status",
            "is_cancelled",
            "total_amount",
            "cancelled_at",
            "cancelled_by",
            "cancellation_reason",
            "updated_at",
        ]
    )
    _record_history(
        order,
        from_status=previous_status,
        to_status=order.status,
        actor=actor,
        reason=reason,
        metadata={
            "scope": "order",
            "refunded_amount": str(refunded_amount),
        },
    )

    if refunded_amount > 0 and order.user:
        transaction.on_commit(lambda: refund_processed_email(order.user, order, refunded_amount))

    return CancellationResult(
        order=order,
        refunded_amount=refunded_amount,
        wallet_balance=wallet.balance if wallet else Decimal("0"),
    )
