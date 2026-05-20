from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, ROUND_HALF_UP
import base64
import json
from urllib import error, request
import uuid

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone

from orders.models import DeliveryAssignment, Order, OrderItem, ReturnRequest

from .models import (
    Payout,
    PayoutConfiguration,
    SellerLedger,
    SellerNotification,
    SellerOrderPayout,
    SellerPayout,
    SellerProfile,
    SellerProduct,
    SellerWallet,
    TransactionLog,
)
from .utils.payout_emails import (
    send_payout_released_email,
    send_payout_failed_email,
    send_balance_available_email,
)


TWOPLACES = Decimal("0.01")
ZERO = Decimal("0.00")
LEGACY_DEFAULT_GST_RATE = Decimal("18.00")


def q(value: Decimal | int | str) -> Decimal:
    return Decimal(value).quantize(TWOPLACES, rounding=ROUND_HALF_UP)


def _setting_decimal(name: str, default: str) -> Decimal:
    return q(getattr(settings, name, default))


def _setting_int(name: str, default: int) -> int:
    return int(getattr(settings, name, default))


def get_active_payout_config() -> dict:
    config = PayoutConfiguration.get_solo()
    return {
        "platform_commission_rate": q(config.platform_commission_rate or _setting_decimal("SELLER_PLATFORM_COMMISSION_RATE", "10.00")),
        "payment_gateway_fee_rate": q(config.payment_gateway_fee_rate or _setting_decimal("SELLER_PAYMENT_GATEWAY_FEE_RATE", "2.00")),
        "gst_rate": q(config.gst_rate or _setting_decimal("SELLER_GST_RATE", "18.00")),
        "tds_rate": q(config.tds_rate or _setting_decimal("SELLER_TDS_RATE", "1.00")),
        "additional_hold_days": config.additional_hold_days or _setting_int("SELLER_PAYOUT_ADDITIONAL_HOLD_DAYS", 7),
        "default_return_window_days": config.default_return_window_days or _setting_int("SELLER_RETURN_WINDOW_DAYS", 7),
        "default_delivery_charge": _setting_decimal("SELLER_DEFAULT_DELIVERY_CHARGE", "50.00"),
        "return_extra_delivery_charge": _setting_decimal("SELLER_RETURN_EXTRA_DELIVERY_CHARGE", "50.00"),
    }


@dataclass(frozen=True)
class CalculationBreakdown:
    seller_id: int
    order_id: int
    order_item_id: int | None
    product_price: Decimal
    taxable_product_price: Decimal
    delivery_charge: Decimal
    delivery_type: str
    payout_amount: Decimal
    product_discount: Decimal = ZERO
    coupon_discount: Decimal = ZERO
    platform_commission: Decimal = ZERO
    payment_gateway_fee: Decimal = ZERO
    shipping_charges: Decimal = ZERO
    seller_discount: Decimal = ZERO
    gst: Decimal = ZERO
    tds: Decimal = ZERO
    return_window_days: int = 7
    hold_days: int = 7
    config_snapshot: dict | None = None

    def as_dict(self) -> dict:
        return {
            "seller_id": self.seller_id,
            "order_id": self.order_id,
            "order_item_id": self.order_item_id,
            "product_price": str(self.product_price),
            "taxable_product_price": str(self.taxable_product_price),
            "delivery_charge": str(self.delivery_charge),
            "delivery_type": self.delivery_type,
            "payout_amount": str(self.payout_amount),
            "product_discount": str(self.product_discount),
            "coupon_discount": str(self.coupon_discount),
            "platform_commission": str(self.platform_commission),
            "payment_gateway_fee": str(self.payment_gateway_fee),
            "shipping_charges": str(self.shipping_charges),
            "seller_discount": str(self.seller_discount),
            "gst": str(self.gst),
            "tds": str(self.tds),
            "return_window_days": self.return_window_days,
            "hold_days": self.hold_days,
            "config_snapshot": {
                key: str(value) if isinstance(value, Decimal) else value
                for key, value in (self.config_snapshot or {}).items()
            },
        }


class PayoutCalculator:
    def __init__(self, config: dict | None = None):
        self.config = config or get_active_payout_config()

    def _resolve_seller_product(self, order_item: OrderItem):
        return getattr(order_item.product, "seller_product", None)

    def _resolve_delivery_type(self, order_item: OrderItem) -> str:
        seller_product = self._resolve_seller_product(order_item)
        if order_item.order.delivery_type:
            return order_item.order.delivery_type
        if seller_product and seller_product.delivery_type:
            return seller_product.delivery_type
        if seller_product and seller_product.delivery_mode == SellerProduct.OWN_DELIVERY:
            return SellerProduct.DELIVERY_TYPE_OWN
        return SellerProduct.DELIVERY_TYPE_PLATFORM

    def _active_order_total(self, order: Order) -> Decimal:
        total = sum((item.get_cost() for item in order.items.exclude(status=OrderItem.STATUS_CANCELLED)), ZERO)
        return q(total)

    def _gross_product_price_for_item(self, order_item: OrderItem) -> Decimal:
        return q((order_item.price or ZERO) * order_item.quantity)

    def _taxable_product_price_for_item(self, order_item: OrderItem) -> Decimal:
        return q((order_item.price or ZERO) * order_item.quantity)

    def _delivery_charge_for_item(self, order_item: OrderItem, delivery_type: str) -> Decimal:
        if delivery_type == SellerProduct.DELIVERY_TYPE_OWN:
            return ZERO
        configured_charge = q(self.config["default_delivery_charge"])
        if configured_charge <= ZERO:
            return ZERO
        charge = configured_charge
        if charge > self._taxable_product_price_for_item(order_item):
            raise ValidationError("Delivery charge cannot exceed product price.")
        return charge

    def _product_discount_for_item(self, order_item: OrderItem) -> Decimal:
        gross_product_price = self._gross_product_price_for_item(order_item)
        sale_price_before_coupon = q(order_item.get_cost())
        if gross_product_price <= sale_price_before_coupon:
            return ZERO
        return q(gross_product_price - sale_price_before_coupon)

    def _coupon_discount_for_item(self, order_item: OrderItem) -> Decimal:
        return q(order_item.get_discount_share())

    def _resolved_gst_rate_for_item(self, order_item: OrderItem) -> Decimal:
        category_rate = q(getattr(getattr(order_item.product, "category", None), "gst_rate", ZERO) or ZERO)
        product_rate = q(getattr(order_item.product, "gst_rate", ZERO) or ZERO)
        order_item_rate = q(getattr(order_item, "gst_rate", ZERO) or ZERO)

        if (
            category_rate > ZERO
            and category_rate != LEGACY_DEFAULT_GST_RATE
            and order_item_rate in {ZERO, LEGACY_DEFAULT_GST_RATE}
            and product_rate in {category_rate, LEGACY_DEFAULT_GST_RATE}
        ):
            return category_rate
        if order_item_rate > ZERO:
            return order_item_rate
        if product_rate > ZERO:
            return product_rate
        if category_rate > ZERO:
            return category_rate
        return q(self.config["gst_rate"])

    def _resolved_gst_total_for_item(
        self,
        order_item: OrderItem,
        *,
        taxable_product_price: Decimal,
        gst_rate: Decimal,
    ) -> Decimal:
        if gst_rate <= ZERO:
            expected_gst_total = ZERO
        else:
            expected_gst_total = q(
                (taxable_product_price * gst_rate) / (Decimal("100") + gst_rate)
            )
        stored_gst_total = q((getattr(order_item, "gst_amount", ZERO) or ZERO) * order_item.quantity)
        if stored_gst_total > ZERO and abs(stored_gst_total - expected_gst_total) <= TWOPLACES:
            return stored_gst_total
        return expected_gst_total

    def _breakdown_from_dict(self, raw: dict | None) -> CalculationBreakdown | None:
        if not raw:
            return None
        return CalculationBreakdown(
            seller_id=int(raw["seller_id"]),
            order_id=int(raw["order_id"]),
            order_item_id=int(raw["order_item_id"]) if raw.get("order_item_id") else None,
            product_price=q(raw.get("product_price", "0")),
            taxable_product_price=q(raw.get("taxable_product_price", raw.get("product_price", "0"))),
            delivery_charge=q(raw.get("delivery_charge", "0")),
            delivery_type=raw.get("delivery_type", SellerProduct.DELIVERY_TYPE_PLATFORM),
            payout_amount=q(raw.get("payout_amount", "0")),
            product_discount=q(raw.get("product_discount", "0")),
            coupon_discount=q(raw.get("coupon_discount", "0")),
            platform_commission=q(raw.get("platform_commission", "0")),
            payment_gateway_fee=q(raw.get("payment_gateway_fee", "0")),
            shipping_charges=q(raw.get("shipping_charges", "0")),
            seller_discount=q(
                raw.get(
                    "seller_discount",
                    q(raw.get("product_discount", "0")) + q(raw.get("coupon_discount", "0")),
                )
            ),
            gst=q(raw.get("gst", "0")),
            tds=q(raw.get("tds", "0")),
            return_window_days=int(raw.get("return_window_days", self.config["default_return_window_days"])),
            hold_days=int(raw.get("hold_days", self.config["additional_hold_days"])),
            config_snapshot=raw.get("config_snapshot") or {},
        )

    def calculate_for_order_item(self, order_item: OrderItem) -> CalculationBreakdown:
        seller_product = self._resolve_seller_product(order_item)
        if not seller_product:
            raise ValidationError("Seller product metadata is required for payout calculation.")

        product_price = self._gross_product_price_for_item(order_item)
        delivery_type = self._resolve_delivery_type(order_item)
        delivery_charge = self._delivery_charge_for_item(order_item, delivery_type)
        product_discount = self._product_discount_for_item(order_item)
        coupon_discount = self._coupon_discount_for_item(order_item)
        seller_discount = q(product_discount + coupon_discount)
        taxable_product_price = q(product_price - seller_discount)
        if taxable_product_price < ZERO:
            raise ValidationError("Discounted product price cannot be negative.")
        platform_commission = q((taxable_product_price * self.config["platform_commission_rate"]) / Decimal("100"))
        payment_gateway_fee = ZERO
        if order_item.order.payment_method != Order.PAYMENT_COD:
            payment_gateway_fee = q((taxable_product_price * self.config["payment_gateway_fee_rate"]) / Decimal("100"))
        shipping_charges = delivery_charge
        
        gst_rate = self._resolved_gst_rate_for_item(order_item)
        gst = self._resolved_gst_total_for_item(
            order_item,
            taxable_product_price=taxable_product_price,
            gst_rate=gst_rate,
        )
        tds = q((taxable_product_price * self.config["tds_rate"]) / Decimal("100"))
        payout_amount = q(
            taxable_product_price
            - platform_commission
            - payment_gateway_fee
            - shipping_charges
            - gst
            - tds
        )
        if payout_amount < ZERO:
            raise ValidationError("Calculated payout cannot be negative.")
        return CalculationBreakdown(
            seller_id=seller_product.seller_id,
            order_id=order_item.order_id,
            order_item_id=order_item.id,
            product_price=product_price,
            taxable_product_price=taxable_product_price,
            delivery_charge=delivery_charge,
            delivery_type=delivery_type,
            payout_amount=payout_amount,
            product_discount=product_discount,
            coupon_discount=coupon_discount,
            platform_commission=platform_commission,
            payment_gateway_fee=payment_gateway_fee,
            shipping_charges=shipping_charges,
            seller_discount=seller_discount,
            gst=gst,
            tds=tds,
            return_window_days=order_item.order.return_window_days or self.config["default_return_window_days"],
            hold_days=self.config["additional_hold_days"],
            config_snapshot=self.config,
        )

    def aggregate_for_seller_order(self, seller: SellerProfile, order: Order) -> dict:
        items = order.items.filter(
            product__seller_product__seller=seller,
        ).exclude(status=OrderItem.STATUS_CANCELLED).select_related("product", "order")
        placement_entries = SellerLedger.objects.filter(
            seller=seller,
            order=order,
            metadata__event="placement",
        ).order_by("id")
        stored_breakdowns = {}
        for entry in placement_entries:
            order_item_id = entry.metadata.get("order_item_id")
            if order_item_id and order_item_id not in stored_breakdowns:
                breakdown = self._breakdown_from_dict(entry.metadata.get("breakdown"))
                if breakdown:
                    stored_breakdowns[order_item_id] = breakdown
        total_product_price = ZERO
        total_taxable_product_price = ZERO
        total_platform_commission = ZERO
        total_gateway_fee = ZERO
        total_delivery_charge = ZERO
        total_discount = ZERO
        total_gst = ZERO
        total_tds = ZERO
        total_payout = ZERO
        delivery_type = order.delivery_type or SellerProduct.DELIVERY_TYPE_PLATFORM
        for item in items:
            breakdown = stored_breakdowns.get(item.id) or self.calculate_for_order_item(item)
            total_product_price = q(total_product_price + breakdown.product_price)
            total_taxable_product_price = q(total_taxable_product_price + breakdown.taxable_product_price)
            total_platform_commission = q(total_platform_commission + breakdown.platform_commission)
            total_gateway_fee = q(total_gateway_fee + breakdown.payment_gateway_fee)
            total_delivery_charge = q(total_delivery_charge + breakdown.delivery_charge)
            total_discount = q(total_discount + breakdown.seller_discount)
            total_gst = q(total_gst + breakdown.gst)
            total_tds = q(total_tds + breakdown.tds)
            total_payout = q(total_payout + breakdown.payout_amount)
            delivery_type = breakdown.delivery_type
        return {
            "seller_id": seller.id,
            "order_id": order.id,
            "item_count": items.count(),
            "delivery_type": delivery_type,
            "product_price": str(total_product_price),
            "taxable_product_price": str(total_taxable_product_price),
            "delivery_charge": str(total_delivery_charge),
            "shipping_charges": str(total_delivery_charge),
            "payout_amount": str(total_payout),
            "platform_commission": str(total_platform_commission),
            "payment_gateway_fee": str(total_gateway_fee),
            "seller_discount": str(total_discount),
            "gst": str(total_gst),
            "tds": str(total_tds),
            "return_window_days": order.return_window_days or self.config["default_return_window_days"],
            "hold_days": self.config["additional_hold_days"],
        }

    def calculate_approximate_payout(
        self,
        *,
        price: Decimal,
        delivery_type: str,
        estimated_delivery_charge: Decimal | None = None,
        gst_rate: Decimal | None = None,
    ) -> Decimal:
        price = q(price or ZERO)
        if delivery_type == SellerProduct.DELIVERY_TYPE_OWN:
            delivery_charge = ZERO
        else:
            delivery_charge = q(self.config["default_delivery_charge"])
        if delivery_charge > price:
            raise ValidationError("Estimated delivery charge cannot exceed product price.")
        platform_commission = q((price * self.config["platform_commission_rate"]) / Decimal("100"))
        payment_gateway_fee = q((price * self.config["payment_gateway_fee_rate"]) / Decimal("100"))
        effective_gst_rate = q(gst_rate if gst_rate is not None else self.config["gst_rate"])
        if effective_gst_rate <= ZERO:
            gst = ZERO
        else:
            gst = q((price * effective_gst_rate) / (Decimal("100") + effective_gst_rate))
        tds = q((price * self.config["tds_rate"]) / Decimal("100"))
        approximate = q(price - platform_commission - payment_gateway_fee - delivery_charge - gst - tds)
        if approximate < ZERO:
            raise ValidationError("Estimated delivery charge cannot exceed product price.")
        return approximate


class WalletService:
    @staticmethod
    @transaction.atomic
    def recalculate_wallet(seller: SellerProfile) -> SellerWallet:
        wallet, _ = SellerWallet.objects.select_for_update().get_or_create(seller=seller)
        status_totals = {
            SellerLedger.STATUS_PENDING: ZERO,
            SellerLedger.STATUS_HOLD: ZERO,
            SellerLedger.STATUS_AVAILABLE: ZERO,
            SellerLedger.STATUS_PAID: ZERO,
        }
        for entry in SellerLedger.objects.filter(seller=seller):
            status_totals[entry.status] = q(status_totals[entry.status] + entry.signed_amount)

        wallet.pending_balance = status_totals[SellerLedger.STATUS_PENDING]
        wallet.hold_balance = status_totals[SellerLedger.STATUS_HOLD]
        wallet.available_balance = status_totals[SellerLedger.STATUS_AVAILABLE]
        wallet.paid_balance = status_totals[SellerLedger.STATUS_PAID]
        wallet.save()

        TransactionLog.objects.create(
            seller=seller,
            action=TransactionLog.ACTION_WALLET_RECALCULATED,
            metadata={
                "pending_balance": str(wallet.pending_balance),
                "hold_balance": str(wallet.hold_balance),
                "available_balance": str(wallet.available_balance),
                "paid_balance": str(wallet.paid_balance),
            },
        )
        return wallet

    @staticmethod
    def get_financial_snapshot(seller: SellerProfile) -> dict:
        wallet = WalletService.recalculate_wallet(seller)
        pending_payout = q(wallet.pending_balance + wallet.hold_balance + wallet.available_balance)
        paid_payout = q(wallet.paid_balance)
        wallet_balance = q(pending_payout + paid_payout)
        return {
            "wallet": wallet,
            "pending_payout": pending_payout,
            "paid_payout": paid_payout,
            "wallet_balance": wallet_balance,
        }


class LedgerService:
    def __init__(self, calculator: PayoutCalculator | None = None):
        self.calculator = calculator or PayoutCalculator()

    def _resolve_seller(self, order_item: OrderItem) -> SellerProfile | None:
        seller_product = getattr(order_item.product, "seller_product", None)
        if not seller_product:
            return None
        return seller_product.seller

    def _log(self, *, action: str, seller: SellerProfile | None = None, order: Order | None = None, payout: Payout | None = None, ledger_entry: SellerLedger | None = None, reference_id: str = "", idempotency_key: str = "", reason: str = "", metadata: dict | None = None) -> TransactionLog:
        return TransactionLog.objects.create(
            seller=seller,
            order=order,
            payout=payout,
            ledger_entry=ledger_entry,
            action=action,
            reference_id=reference_id,
            idempotency_key=idempotency_key,
            reason=reason,
            metadata=metadata or {},
        )

    def _sync_legacy_payout(self, order_item: OrderItem, breakdown: CalculationBreakdown):
        SellerPayout.objects.filter(order_item=order_item).update(
            delivery_type=breakdown.delivery_type,
            delivery_charge=breakdown.delivery_charge,
            payout_amount=breakdown.payout_amount,
            payout_status=SellerPayout.PAYOUT_STATUS_PENDING,
            razorpay_payout_id="",
            status=SellerPayout.STATUS_PENDING,
        )

    @transaction.atomic
    def register_order_item(self, order_item: OrderItem, *, idempotency_key: str | None = None) -> list[SellerLedger]:
        seller = self._resolve_seller(order_item)
        if not seller:
            return []
        reference_id = f"order-item:{order_item.id}"
        if SellerLedger.objects.filter(reference_id=reference_id, metadata__event="placement").exists():
            return list(SellerLedger.objects.filter(reference_id=reference_id))

        breakdown = self.calculator.calculate_for_order_item(order_item)
        event_key = idempotency_key or f"{reference_id}:placement"
        entries = [
            {
                "transaction_type": SellerLedger.TYPE_CREDIT,
                "amount": breakdown.product_price,
                "component": SellerLedger.COMPONENT_PRODUCT_PRICE,
            },
            {
                "transaction_type": SellerLedger.TYPE_DEBIT,
                "amount": breakdown.platform_commission,
                "component": SellerLedger.COMPONENT_COMMISSION,
            },
            {
                "transaction_type": SellerLedger.TYPE_DEBIT,
                "amount": breakdown.payment_gateway_fee,
                "component": SellerLedger.COMPONENT_GATEWAY_FEE,
            },
            {
                "transaction_type": SellerLedger.TYPE_DEBIT,
                "amount": breakdown.shipping_charges,
                "component": SellerLedger.COMPONENT_SHIPPING,
            },
            {
                "transaction_type": SellerLedger.TYPE_DEBIT,
                "amount": breakdown.seller_discount,
                "component": SellerLedger.COMPONENT_DISCOUNT,
            },
            {
                "transaction_type": SellerLedger.TYPE_DEBIT,
                "amount": breakdown.gst,
                "component": SellerLedger.COMPONENT_GST,
            },
            {
                "transaction_type": SellerLedger.TYPE_DEBIT,
                "amount": breakdown.tds,
                "component": SellerLedger.COMPONENT_TDS,
            },
        ]

        created_entries = []
        for entry_data in entries:
            if entry_data["amount"] <= ZERO:
                continue
            entry = SellerLedger.objects.create(
                seller=seller,
                order=order_item.order,
                transaction_type=entry_data["transaction_type"],
                amount=entry_data["amount"],
                component=entry_data["component"],
                status=SellerLedger.STATUS_PENDING,
                reference_id=reference_id,
                idempotency_key=f"{event_key}:{entry_data['component']}",
                notes="Order registered for payout",
                metadata={
                    "event": "placement",
                    "order_item_id": order_item.id,
                    "delivery_type": breakdown.delivery_type,
                    "breakdown": breakdown.as_dict(),
                },
            )
            created_entries.append(entry)
            self._log(
                action=TransactionLog.ACTION_LEDGER_CREATED,
                seller=seller,
                order=order_item.order,
                ledger_entry=entry,
                reference_id=reference_id,
                idempotency_key=entry.idempotency_key,
                metadata=entry.metadata,
            )

        self._sync_legacy_payout(order_item, breakdown)
        self._refresh_order_payout_summary(seller=seller, order=order_item.order, reference_id=reference_id)
        WalletService.recalculate_wallet(seller)
        return created_entries

    def _resolve_delivery_timestamp(self, seller: SellerProfile, order: Order):
        try:
            assignment = order.delivery_assignment
        except DeliveryAssignment.DoesNotExist:
            assignment = None

        if assignment and assignment.status == DeliveryAssignment.STATUS_DELIVERED and assignment.delivered_at:
            return assignment.delivered_at

        seller_payouts = seller.payouts.filter(
            order_item__order=order,
            delivery_status=SellerPayout.DELIVERY_DELIVERED,
            delivery_status_updated_at__isnull=False,
        )
        if seller_payouts.exists():
            return seller_payouts.order_by("-delivery_status_updated_at").first().delivery_status_updated_at
        return None

    @transaction.atomic
    def _refresh_order_payout_summary(self, *, seller: SellerProfile, order: Order, reference_id: str = "") -> SellerOrderPayout:
        summary, _ = SellerOrderPayout.objects.select_for_update().get_or_create(
            seller=seller,
            order=order,
            defaults={
                "status": SellerOrderPayout.STATUS_PENDING,
                "return_window_days": order.return_window_days or self.calculator.config["default_return_window_days"],
                "hold_days": self.calculator.config["additional_hold_days"],
            },
        )
        aggregated = self.calculator.aggregate_for_seller_order(seller, order)
        summary.gross_amount = q(aggregated["product_price"])
        summary.net_amount = q(aggregated["payout_amount"])
        summary.breakdown = aggregated
        summary.delivered_at = self._resolve_delivery_timestamp(seller, order)
        summary.return_window_days = aggregated["return_window_days"]
        summary.hold_days = aggregated["hold_days"]
        if summary.delivered_at:
            summary.return_window_closed_at = summary.delivered_at + timezone.timedelta(days=summary.return_window_days)
            summary.available_on = summary.return_window_closed_at + timezone.timedelta(days=summary.hold_days)
        summary.last_reference_id = reference_id

        if order.order_status == Order.ORDER_STATUS_CANCELLED or order.status == Order.STATUS_CANCELLED:
            summary.status = SellerOrderPayout.STATUS_CANCELLED
        else:
            current_statuses = set(
                SellerLedger.objects.filter(seller=seller, order=order).values_list("status", flat=True).distinct()
            )
            if current_statuses == {SellerLedger.STATUS_PAID}:
                summary.status = SellerOrderPayout.STATUS_PAID
                summary.paid_at = summary.paid_at or timezone.now()
            elif current_statuses == {SellerLedger.STATUS_AVAILABLE}:
                summary.status = SellerOrderPayout.STATUS_AVAILABLE
            elif current_statuses == {SellerLedger.STATUS_HOLD}:
                summary.status = SellerOrderPayout.STATUS_HOLD
            elif current_statuses:
                summary.status = SellerOrderPayout.STATUS_PENDING

        summary.save()
        return summary

    @transaction.atomic
    def transition_status(self, *, seller: SellerProfile, order: Order, from_status: str, to_status: str, reason: str, reference_id: str | None = None) -> int:
        if order.order_status == Order.ORDER_STATUS_CANCELLED or order.status == Order.STATUS_CANCELLED:
            return 0
        reference_id = reference_id or f"transition:{order.id}:{from_status}:{to_status}"
        updated = SellerLedger.objects.filter(seller=seller, order=order, status=from_status).update(status=to_status)
        if updated:
            self._log(
                action=TransactionLog.ACTION_LEDGER_STATUS_UPDATED,
                seller=seller,
                order=order,
                reference_id=reference_id,
                reason=reason,
                metadata={"from_status": from_status, "to_status": to_status, "updated_entries": updated},
            )
            self._refresh_order_payout_summary(seller=seller, order=order, reference_id=reference_id)
            WalletService.recalculate_wallet(seller)
        return updated

    @transaction.atomic
    def process_eligibility_transitions(self) -> list[dict]:
        transitions = []
        now = timezone.now()
        for summary in SellerOrderPayout.objects.select_related("seller", "order").all():
            order = summary.order
            if order.order_status in {Order.ORDER_STATUS_CANCELLED, Order.ORDER_STATUS_RETURNED} or order.status == Order.STATUS_CANCELLED:
                continue
            try:
                assignment = order.delivery_assignment
            except DeliveryAssignment.DoesNotExist:
                assignment = None
            if assignment and assignment.status in {DeliveryAssignment.STATUS_DELIVERY_FAILED, DeliveryAssignment.STATUS_RETURNED}:
                continue

            delivered_at = self._resolve_delivery_timestamp(summary.seller, order)
            if delivered_at and summary.status == SellerOrderPayout.STATUS_PENDING:
                summary.delivered_at = delivered_at
                summary.return_window_closed_at = delivered_at + timezone.timedelta(days=summary.return_window_days)
                summary.available_on = summary.return_window_closed_at + timezone.timedelta(days=summary.hold_days)
                summary.save(update_fields=["delivered_at", "return_window_closed_at", "available_on", "updated_at"])
                if summary.return_window_closed_at and now >= summary.return_window_closed_at:
                    moved = self.transition_status(
                        seller=summary.seller,
                        order=order,
                        from_status=SellerLedger.STATUS_PENDING,
                        to_status=SellerLedger.STATUS_HOLD,
                        reason="Return window closed",
                    )
                    if moved:
                        transitions.append({"order_id": order.id, "seller_id": summary.seller_id, "to_status": SellerLedger.STATUS_HOLD})
            summary.refresh_from_db()
            if summary.status == SellerOrderPayout.STATUS_HOLD and summary.available_on and now >= summary.available_on:
                moved = self.transition_status(
                    seller=summary.seller,
                    order=order,
                    from_status=SellerLedger.STATUS_HOLD,
                    to_status=SellerLedger.STATUS_AVAILABLE,
                    reason="Additional hold completed",
                )
                if moved:
                    transitions.append({"order_id": order.id, "seller_id": summary.seller_id, "to_status": SellerLedger.STATUS_AVAILABLE})
                    order_item = order.items.filter(product__seller_product__seller=summary.seller).first()
                    if order_item:
                        SellerNotification.objects.get_or_create(
                            recipient=summary.seller.user,
                            order_item=order_item,
                            notification_type=SellerNotification.TYPE_BALANCE_AVAILABLE,
                            defaults={"message": f"Order #{order.id} earnings are now available."},
                        )
        return transitions

    @transaction.atomic
    def handle_cancellation(self, order: Order, *, idempotency_key: str | None = None) -> list[SellerLedger]:
        reference_id = f"cancel-order:{order.id}"
        if SellerLedger.objects.filter(reference_id=reference_id).exists():
            return list(SellerLedger.objects.filter(reference_id=reference_id))

        created_entries = []
        source_entries = SellerLedger.objects.filter(order=order, metadata__event="placement").select_related("seller")
        for source in source_entries:
            status = source.status if source.status != SellerLedger.STATUS_PAID else SellerLedger.STATUS_AVAILABLE
            reverse_type = SellerLedger.TYPE_DEBIT if source.transaction_type == SellerLedger.TYPE_CREDIT else SellerLedger.TYPE_CREDIT
            entry = SellerLedger.objects.create(
                seller=source.seller,
                order=order,
                transaction_type=reverse_type,
                amount=source.amount,
                component=source.component,
                status=status,
                reference_id=reference_id,
                idempotency_key=f"{idempotency_key or reference_id}:{source.id}",
                notes="Order cancelled reversal",
                metadata={
                    "event": "cancellation",
                    "source_ledger_id": source.id,
                    "order_item_id": source.metadata.get("order_item_id"),
                },
            )
            created_entries.append(entry)
            self._log(
                action=TransactionLog.ACTION_LEDGER_CREATED,
                seller=source.seller,
                order=order,
                ledger_entry=entry,
                reference_id=reference_id,
                idempotency_key=entry.idempotency_key,
                reason="Order cancelled",
                metadata=entry.metadata,
            )
            SellerPayout.objects.filter(order_item_id=source.metadata.get("order_item_id")).update(
                status=SellerPayout.STATUS_FAILED,
                payout_status=SellerPayout.PAYOUT_STATUS_PENDING,
            )
            self._refresh_order_payout_summary(seller=source.seller, order=order, reference_id=reference_id)
            WalletService.recalculate_wallet(source.seller)
        return created_entries

    @transaction.atomic
    def process_return(self, return_request: ReturnRequest, *, idempotency_key: str | None = None) -> list[SellerLedger]:
        reference_id = f"return:{return_request.id}"
        if SellerLedger.objects.filter(reference_id=reference_id).exists():
            return list(SellerLedger.objects.filter(reference_id=reference_id))

        order_item = return_request.order.items.filter(product=return_request.product).select_related("product", "order").first()
        if not order_item:
            return []
        seller = self._resolve_seller(order_item)
        if not seller:
            return []

        breakdown = self.calculator.calculate_for_order_item(order_item)
        ratio_base = max(q(order_item.get_cost()), Decimal("1.00"))
        ratio = q((return_request.refund_amount or ratio_base) / ratio_base)
        if ratio > Decimal("1.00"):
            ratio = Decimal("1.00")
        if ratio <= ZERO:
            ratio = Decimal("1.00")

        existing_paid_entry = SellerLedger.objects.filter(
            seller=seller,
            order=order_item.order,
            metadata__order_item_id=order_item.id,
            status=SellerLedger.STATUS_PAID,
        ).exists()
        current_status = SellerLedger.STATUS_AVAILABLE if existing_paid_entry else (
            SellerLedger.objects.filter(
                seller=seller,
                order=order_item.order,
                metadata__order_item_id=order_item.id,
            ).exclude(status=SellerLedger.STATUS_PAID).values_list("status", flat=True).first() or SellerLedger.STATUS_PENDING
        )

        created_entries = []
        original_entries = SellerLedger.objects.filter(
            seller=seller,
            order=order_item.order,
            metadata__event="placement",
            metadata__order_item_id=order_item.id,
        )
        for original_entry in original_entries:
            reverse_type = (
                SellerLedger.TYPE_DEBIT
                if original_entry.transaction_type == SellerLedger.TYPE_CREDIT
                else SellerLedger.TYPE_CREDIT
            )
            amount = q(original_entry.amount * ratio)
            if amount <= ZERO:
                continue
            entry = SellerLedger.objects.create(
                seller=seller,
                order=order_item.order,
                transaction_type=reverse_type,
                amount=amount,
                component=SellerLedger.COMPONENT_RETURN if original_entry.component == SellerLedger.COMPONENT_PRODUCT_PRICE else original_entry.component,
                status=current_status,
                reference_id=reference_id,
                idempotency_key=f"{idempotency_key or reference_id}:{original_entry.id}",
                notes="Return reversal",
                metadata={
                    "event": "return",
                    "order_item_id": order_item.id,
                    "return_request_id": return_request.id,
                    "source_ledger_id": original_entry.id,
                    "ratio": str(ratio),
                },
            )
            created_entries.append(entry)
            self._log(
                action=TransactionLog.ACTION_RETURN_PROCESSED,
                seller=seller,
                order=order_item.order,
                ledger_entry=entry,
                reference_id=reference_id,
                idempotency_key=entry.idempotency_key,
                reason=return_request.reason,
                metadata=entry.metadata,
            )

        extra_return_charge = ZERO
        if breakdown.delivery_type != SellerProduct.DELIVERY_TYPE_OWN:
            extra_return_charge = q(self.calculator.config["return_extra_delivery_charge"] * ratio)
        if extra_return_charge > ZERO:
            entry = SellerLedger.objects.create(
                seller=seller,
                order=order_item.order,
                transaction_type=SellerLedger.TYPE_DEBIT,
                amount=extra_return_charge,
                component=SellerLedger.COMPONENT_RETURN_SHIPPING,
                status=current_status,
                reference_id=reference_id,
                idempotency_key=f"{idempotency_key or reference_id}:extra_return_shipping",
                notes="Extra return shipping deduction",
                metadata={
                    "event": "return",
                    "order_item_id": order_item.id,
                    "return_request_id": return_request.id,
                    "extra_return_charge": str(extra_return_charge),
                },
            )
            created_entries.append(entry)
            self._log(
                action=TransactionLog.ACTION_RETURN_PROCESSED,
                seller=seller,
                order=order_item.order,
                ledger_entry=entry,
                reference_id=reference_id,
                idempotency_key=entry.idempotency_key,
                reason=return_request.reason,
                metadata=entry.metadata,
            )
        return_request.order.order_status = Order.ORDER_STATUS_RETURNED
        return_request.order.save(update_fields=["order_status", "updated_at"])
        self._refresh_order_payout_summary(seller=seller, order=return_request.order, reference_id=reference_id)
        WalletService.recalculate_wallet(seller)
        SellerNotification.objects.get_or_create(
            recipient=seller.user,
            order_item=order_item,
            notification_type=SellerNotification.TYPE_DEDUCTION_APPLIED,
            defaults={"message": f"Return deduction applied for order #{order_item.order_id}."},
        )
        return created_entries

    @transaction.atomic
    def create_manual_adjustment(self, *, seller: SellerProfile, amount: Decimal, transaction_type: str, reason: str, actor=None, reference_id: str | None = None, status: str = SellerLedger.STATUS_AVAILABLE) -> SellerLedger:
        if amount <= ZERO:
            raise ValidationError("Adjustment amount must be positive.")
        reference_id = reference_id or f"manual-adjustment:{uuid.uuid4().hex[:12]}"
        entry = SellerLedger.objects.create(
            seller=seller,
            transaction_type=transaction_type,
            amount=q(amount),
            component=SellerLedger.COMPONENT_ADJUSTMENT,
            status=status,
            reference_id=reference_id,
            idempotency_key=f"{reference_id}:adjustment",
            notes=reason,
            metadata={"event": "manual_adjustment", "actor_id": getattr(actor, "id", None)},
        )
        self._log(
            action=TransactionLog.ACTION_MANUAL_ADJUSTMENT,
            seller=seller,
            ledger_entry=entry,
            reference_id=reference_id,
            reason=reason,
            metadata=entry.metadata,
        )
        WalletService.recalculate_wallet(seller)
        return entry


class RazorpayPayoutError(Exception):
    pass


class RazorpayPayoutClient:
    endpoint = "https://api.razorpay.com/v1/payouts"

    def create_payout(self, *, seller: SellerProfile, amount: Decimal, payout: Payout) -> dict:
        payload = {
            "account_number": getattr(settings, "RAZORPAY_SOURCE_ACCOUNT_NUMBER", ""),
            "amount": int(q(amount) * 100),
            "currency": "INR",
            "mode": "UPI" if seller.payout_upi_id else "NEFT",
            "purpose": "payout",
            "queue_if_low_balance": True,
            "reference_id": payout.idempotency_key[:40],
            "narration": f"Seller payout {seller.seller_id or seller.id}",
            "notes": {
                "seller_id": seller.seller_id or str(seller.id),
                "payout_id": str(payout.id),
            },
            "fund_account": {
                "account_type": "bank_account",
                "bank_account": {
                    "name": seller.payout_account_name,
                    "ifsc": seller.payout_ifsc,
                    "account_number": seller.payout_account_number,
                },
                "contact": {
                    "name": seller.contact_person_name,
                    "email": seller.contact_email,
                    "contact": seller.phone or "9999999999",
                    "type": "vendor",
                },
            },
        }
        if seller.payout_upi_id:
            payload["fund_account"] = {
                "account_type": "vpa",
                "vpa": {"address": seller.payout_upi_id},
                "contact": {
                    "name": seller.contact_person_name,
                    "email": seller.contact_email,
                    "contact": seller.phone or "9999999999",
                    "type": "vendor",
                },
            }

        raw = json.dumps(payload).encode("utf-8")
        auth = base64.b64encode(f"{settings.RAZORPAY_KEY_ID}:{settings.RAZORPAY_KEY_SECRET}".encode("utf-8")).decode("utf-8")
        req = request.Request(
            self.endpoint,
            data=raw,
            method="POST",
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Basic {auth}",
            },
        )
        try:
            with request.urlopen(req, timeout=30) as response:
                body = json.loads(response.read().decode("utf-8"))
        except error.HTTPError as exc:
            body = exc.read().decode("utf-8", errors="ignore")
            raise RazorpayPayoutError(f"Razorpay payout failed: {exc.code} {body}") from exc
        except error.URLError as exc:
            raise RazorpayPayoutError(f"Razorpay payout failed: {exc.reason}") from exc

        status_map = {
            "processed": Payout.STATUS_COMPLETED,
            "queued": Payout.STATUS_PROCESSING,
            "pending": Payout.STATUS_PROCESSING,
            "rejected": Payout.STATUS_FAILED,
            "cancelled": Payout.STATUS_FAILED,
        }
        return {
            "reference": body.get("id", ""),
            "status": status_map.get(body.get("status"), Payout.STATUS_PROCESSING),
            "processed_at": timezone.now(),
            "raw_response": body,
        }


class MockRazorpayPayoutClient:
    def create_payout(self, *, seller: SellerProfile, amount: Decimal, payout: Payout) -> dict:
        return {
            "reference": f"mock_rzp_{payout.id}",
            "status": Payout.STATUS_COMPLETED,
            "processed_at": timezone.now(),
            "raw_response": {"mock": True},
        }


class PayoutService:
    def __init__(self, ledger_service: LedgerService | None = None, gateway_client=None):
        self.ledger_service = ledger_service or LedgerService()
        if gateway_client is not None:
            self.gateway_client = gateway_client
        elif getattr(settings, "SELLER_RAZORPAY_PAYOUT_MODE", "mock") == "live":
            self.gateway_client = RazorpayPayoutClient()
        else:
            self.gateway_client = MockRazorpayPayoutClient()

    @transaction.atomic
    def release_available_balance(self, *, seller: SellerProfile, idempotency_key: str | None = None) -> Payout:
        seller = SellerProfile.objects.select_for_update().get(pk=seller.pk)
        snapshot = WalletService.get_financial_snapshot(seller)
        available_balance = snapshot["wallet"].available_balance
        if available_balance <= ZERO:
            raise ValidationError("Seller has no available balance to pay out.")

        payout = Payout.objects.create(
            seller=seller,
            amount=available_balance,
            status=Payout.STATUS_INITIATED,
            idempotency_key=idempotency_key or f"payout:{seller.id}:{uuid.uuid4().hex}",
            breakdown={
                "available_balance_before": str(available_balance),
                "pending_payout_before": str(snapshot["pending_payout"]),
                "paid_payout_before": str(snapshot["paid_payout"]),
                "generated_at": timezone.now().isoformat(),
            },
        )
        self.ledger_service._log(
            action=TransactionLog.ACTION_PAYOUT_INITIATED,
            seller=seller,
            payout=payout,
            reference_id=f"payout:{payout.id}",
            idempotency_key=payout.idempotency_key,
            metadata=payout.breakdown,
        )
        payout.status = Payout.STATUS_PROCESSING
        payout.save(update_fields=["status", "updated_at"])

        available_entries = list(
            SellerLedger.objects.select_for_update().filter(
                seller=seller,
                status=SellerLedger.STATUS_AVAILABLE,
            )
        )
        if not available_entries:
            payout.status = Payout.STATUS_FAILED
            payout.failure_reason = "Available wallet balance is stale."
            payout.save(update_fields=["status", "failure_reason", "updated_at"])
            raise ValidationError("Available wallet balance is stale. Recalculate and try again.")

        try:
            gateway_response = self.gateway_client.create_payout(
                seller=seller,
                amount=payout.amount,
                payout=payout,
            )
        except Exception as exc:
            payout.status = Payout.STATUS_FAILED
            payout.failure_reason = str(exc)
            payout.processed_at = timezone.now()
            payout.save(update_fields=["status", "failure_reason", "processed_at", "updated_at"])
            self.ledger_service._log(
                action=TransactionLog.ACTION_PAYOUT_FAILED,
                seller=seller,
                payout=payout,
                reference_id=f"payout:{payout.id}",
                idempotency_key=payout.idempotency_key,
                reason=str(exc),
            )
            return payout

        payout.reference = gateway_response["reference"]
        payout.status = gateway_response["status"]
        payout.processed_at = gateway_response["processed_at"]
        payout.breakdown["gateway_response"] = gateway_response.get("raw_response", {})
        payout.save(update_fields=["reference", "status", "processed_at", "breakdown", "updated_at"])

        if payout.status == Payout.STATUS_FAILED:
            payout.failure_reason = "Gateway returned a failed payout status."
            payout.save(update_fields=["failure_reason", "updated_at"])
            self.ledger_service._log(
                action=TransactionLog.ACTION_PAYOUT_FAILED,
                seller=seller,
                payout=payout,
                reference_id=payout.reference,
                idempotency_key=payout.idempotency_key,
                reason=payout.failure_reason,
            )
            return payout

        if payout.status == Payout.STATUS_COMPLETED:
            order_item_ids = []
            for entry in available_entries:
                entry.status = SellerLedger.STATUS_PAID
                entry.payout = payout
                entry.save(update_fields=["status", "payout"])
                order_item_id = entry.metadata.get("order_item_id")
                if order_item_id:
                    order_item_ids.append(order_item_id)

            SellerPayout.objects.filter(order_item_id__in=order_item_ids).update(
                status=SellerPayout.STATUS_PAID,
                payout_status=SellerPayout.PAYOUT_STATUS_PAID,
                razorpay_payout_id=payout.reference,
                paid_at=payout.processed_at,
            )
            for summary in SellerOrderPayout.objects.select_for_update().filter(
                seller=seller,
                status=SellerOrderPayout.STATUS_AVAILABLE,
            ):
                summary.status = SellerOrderPayout.STATUS_PAID
                summary.paid_at = payout.processed_at
                summary.save(update_fields=["status", "paid_at", "updated_at"])
            WalletService.recalculate_wallet(seller)
            self.ledger_service._log(
                action=TransactionLog.ACTION_PAYOUT_COMPLETED,
                seller=seller,
                payout=payout,
                reference_id=payout.reference,
                idempotency_key=payout.idempotency_key,
                metadata={"amount": str(payout.amount), "ledger_entries": len(available_entries)},
            )

            notification_item = OrderItem.objects.filter(id__in=order_item_ids).first()
            if notification_item:
                SellerNotification.objects.create(
                    recipient=seller.user,
                    order_item=notification_item,
                    notification_type=SellerNotification.TYPE_PAYOUT_COMPLETED,
                    message=f"Payout of INR {payout.amount} completed. Reference: {payout.reference}.",
                )
            
            # Send email notification
            try:
                send_payout_released_email(seller, payout)
            except Exception as e:
                # Log but don't fail the payout if email fails
                self.ledger_service._log(
                    action=TransactionLog.ACTION_PAYOUT_COMPLETED,
                    seller=seller,
                    payout=payout,
                    reason=f"Email notification failed: {str(e)}",
                )
        elif payout.status == Payout.STATUS_FAILED:
            # Send failure notification email
            try:
                send_payout_failed_email(seller, payout)
            except Exception:
                pass  # Silently fail, already logged in transaction log
        
        return payout
