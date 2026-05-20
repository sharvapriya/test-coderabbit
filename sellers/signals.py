from decimal import Decimal

from django.contrib.auth import get_user_model
from django.db import transaction
from django.db.models.signals import post_save, pre_save
from django.dispatch import receiver

from orders.models import Order, OrderItem, ReturnRequest
from orders.utils.seller_emails import (
    notify_new_order_received,
    notify_new_seller_registration,
    notify_seller_application_status_to_seller,
    notify_seller_application_status_update,
    notify_seller_registration_id_generated,
    notify_seller_registration_received,
)

from .models import HubProductDelivery, SellerNotification, SellerPayout, SellerProduct, SellerProfile
from .services import LedgerService


def _get_or_create_platform_hub_profile():
    User = get_user_model()
    staff_user = User.objects.filter(is_staff=True, is_active=True).order_by("id").first()
    if not staff_user:
        return None
    profile, _ = SellerProfile.objects.get_or_create(
        user=staff_user,
        defaults={
            "business_name": "Platform Hub",
            "phone": "",
            "payout_account_name": "Platform Hub",
            "payout_account_number": "HUB-ACCOUNT",
            "payout_ifsc": "HUB0000000",
            "approval_status": SellerProfile.STATUS_APPROVED,
        },
    )
    if profile.approval_status != SellerProfile.STATUS_APPROVED:
        profile.approval_status = SellerProfile.STATUS_APPROVED
        profile.save(update_fields=["approval_status", "seller_id", "approved_at", "updated_at"])
    return profile
@receiver(pre_save, sender=SellerProfile)
def capture_previous_seller_profile_state(sender, instance, **kwargs):
    if not instance.pk:
        instance._previous_approval_status = None
        instance._previous_registration_id = None
        return

    previous = sender.objects.filter(pk=instance.pk).values("approval_status", "registration_id").first() or {}
    instance._previous_approval_status = previous.get("approval_status")
    instance._previous_registration_id = previous.get("registration_id")


@receiver(post_save, sender=SellerProfile)
def send_seller_profile_notifications(sender, instance, created, **kwargs):
    previous_approval_status = getattr(instance, "_previous_approval_status", None)
    previous_registration_id = getattr(instance, "_previous_registration_id", None)

    if created:
        transaction.on_commit(lambda: notify_new_seller_registration(instance))
        transaction.on_commit(lambda: notify_seller_registration_received(instance))
        if instance.registration_id:
            transaction.on_commit(lambda: notify_seller_registration_id_generated(instance))
        return

    if not previous_registration_id and instance.registration_id:
        transaction.on_commit(lambda: notify_seller_registration_id_generated(instance))

    if (
        previous_approval_status != instance.approval_status
        and instance.approval_status in {SellerProfile.STATUS_APPROVED, SellerProfile.STATUS_REJECTED}
    ):
        transaction.on_commit(lambda: notify_seller_application_status_update(instance))
        transaction.on_commit(lambda: notify_seller_application_status_to_seller(instance))

@receiver(post_save, sender=OrderItem)
def create_seller_payout_for_order_item(sender, instance, created, **kwargs):
    if not created:
        return

    seller_product = getattr(instance.product, "seller_product", None)
    if seller_product and instance.order.delivery_type != seller_product.delivery_type:
        instance.order.delivery_type = seller_product.delivery_type
        instance.order.save(update_fields=["delivery_type", "updated_at"])

    if SellerPayout.objects.filter(order_item=instance).exists():
        return

    gross_amount = instance.get_cost()
    if seller_product:
        seller_profile = seller_product.seller
        delivery_mode = seller_product.delivery_mode
        payout_rate = seller_product.get_payout_rate()
        payout_amount = seller_product.calculate_payout_amount(gross_amount)
    else:
        seller_profile = _get_or_create_platform_hub_profile()
        if not seller_profile:
            return
        delivery_mode = SellerProduct.HUB_DELIVERY
        payout_rate = Decimal("100.00")
        payout_amount = gross_amount

    payout = SellerPayout.objects.create(
        seller=seller_profile,
        order_item=instance,
        delivery_mode=delivery_mode,
        delivery_type=(
            seller_product.delivery_type
            if seller_product and seller_product.delivery_type
            else SellerProduct.DELIVERY_TYPE_OWN if delivery_mode == SellerProduct.OWN_DELIVERY else SellerProduct.DELIVERY_TYPE_PLATFORM
        ),
        delivery_charge=instance.order.delivery_charge if delivery_mode != SellerProduct.OWN_DELIVERY else Decimal("0.00"),
        gross_amount=gross_amount,
        payout_percentage=payout_rate,
        payout_amount=payout_amount,
    )

    if delivery_mode == SellerProduct.HUB_DELIVERY:
        HubProductDelivery.objects.get_or_create(
            order_item=instance,
            defaults={
                "seller": seller_profile,
                "seller_payout": payout,
                "hub_name": getattr(seller_product, "hub_name", "") if seller_product else "Platform Hub",
                "hub_address": getattr(seller_product, "hub_address", "") if seller_product else "",
            },
        )

    if delivery_mode == SellerProduct.OWN_DELIVERY:
        seller_message = (
            f"{instance.product.name}. "
            f"Qty: {instance.quantity}. Order {instance.order.display_order_id}. "
            f"Customer: {instance.order.full_name}, {instance.order.email}. "
            f"Address: {instance.order.address}."
        )
    else:
        seller_message = (
            f"{instance.product.name}. "
            f"Quantity: {instance.quantity}. Order {instance.order.display_order_id}."
        )
    message_max_length = SellerNotification._meta.get_field("message").max_length
    SellerNotification.objects.get_or_create(
        recipient=seller_profile.user,
        order_item=instance,
        notification_type=SellerNotification.TYPE_SELLER_ORDER,
        defaults={"message": seller_message[:message_max_length]},
    )
    transaction.on_commit(lambda: notify_new_order_received(instance.order, seller_profile))

    User = get_user_model()
    admin_users = User.objects.filter(is_staff=True, is_active=True)
    admin_message = (
        f"Order #{instance.order_id}: {instance.product.name} assigned to "
        f"seller {seller_profile.business_name}."
    )
    for admin_user in admin_users:
        SellerNotification.objects.get_or_create(
            recipient=admin_user,
            order_item=instance,
            notification_type=SellerNotification.TYPE_ADMIN_ORDER,
            defaults={"message": admin_message},
        )

    LedgerService().register_order_item(instance)


@receiver(post_save, sender=ReturnRequest)
def process_return_request_for_ledger(sender, instance, created, **kwargs):
    if instance.status not in {ReturnRequest.STATUS_APPROVED, ReturnRequest.STATUS_REFUNDED}:
        return
    LedgerService().process_return(instance, idempotency_key=f"return-request:{instance.id}:{instance.status}")


@receiver(post_save, sender=Order)
def process_order_cancellation_for_ledger(sender, instance, created, **kwargs):
    if instance.status != Order.STATUS_CANCELLED and instance.order_status != Order.ORDER_STATUS_CANCELLED:
        return
    LedgerService().handle_cancellation(instance, idempotency_key=f"order-cancelled:{instance.id}")






