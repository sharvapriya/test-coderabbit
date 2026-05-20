from django.db.models.signals import post_delete, post_save, pre_save
from django.dispatch import receiver
from django.utils import timezone

from accounts.models import Notification
from orders.utils.seller_emails import notify_product_status_update

from .models import Product, ProductVariant, StockAlertSubscription
from .utils.email import send_restock_email


def _is_restockable(product):
    return product.status == Product.STATUS_APPROVED and product.is_in_stock


def _mark_stock_alerts_pending(product):
    StockAlertSubscription.objects.filter(product=product).update(
        is_notified=False,
        notified_at=None,
    )


def _send_restock_alerts(product):
    subscriptions = list(
        StockAlertSubscription.objects.filter(
            product=product,
            is_notified=False,
            user__email__gt="",
        ).select_related("user")
    )
    if not subscriptions:
        return

    notified_ids = []
    notified_at = timezone.now()
    notifications_to_create = []
    for subscription in subscriptions:
        user = subscription.user
        # Send email
        email_sent = send_restock_email(user, product)
        
        # Create in-app notification
        title = f"{product.name} is back in stock!"
        message = f"Good news! The product you were waiting for is now available. Check it out and place your order."
        notifications_to_create.append(
            Notification(
                user=user,
                notification_type=Notification.TYPE_STOCK_RESTOCK,
                title=title,
                message=message,
            )
        )
        
        if email_sent:
            notified_ids.append(subscription.id)

    # Bulk create notifications
    if notifications_to_create:
        Notification.objects.bulk_create(notifications_to_create)

    if notified_ids:
        StockAlertSubscription.objects.filter(id__in=notified_ids).update(
            is_notified=True,
            notified_at=notified_at,
        )


def _sync_restock_alerts(product, *, was_restockable):
    product.refresh_from_db()
    is_restockable = _is_restockable(product)

    if is_restockable and not was_restockable:
        _send_restock_alerts(product)
    elif not is_restockable:
        _mark_stock_alerts_pending(product)


@receiver(pre_save, sender=Product)
def capture_previous_product_status(sender, instance, **kwargs):
    if not instance.pk:
        instance._previous_status = None
        instance._was_restockable = False
        return

    previous_product = sender.objects.get(pk=instance.pk)
    instance._previous_status = previous_product.status
    instance._was_restockable = _is_restockable(previous_product)


@receiver(post_save, sender=Product)
def send_product_status_notification(sender, instance, created, **kwargs):
    previous_status = getattr(instance, "_previous_status", None)
    if not created and previous_status == Product.STATUS_PENDING:
        if instance.status in {Product.STATUS_APPROVED, Product.STATUS_REJECTED}:
            notify_product_status_update(instance)

    _sync_restock_alerts(
        instance,
        was_restockable=getattr(instance, "_was_restockable", False),
    )


@receiver(pre_save, sender=ProductVariant)
def capture_previous_variant_stock_state(sender, instance, **kwargs):
    if not instance.product_id:
        instance._was_restockable = False
        return

    product = Product.objects.get(pk=instance.product_id)
    instance._was_restockable = _is_restockable(product)


@receiver(post_save, sender=ProductVariant)
def sync_variant_restock_alerts(sender, instance, **kwargs):
    _sync_restock_alerts(
        instance.product,
        was_restockable=getattr(instance, "_was_restockable", False),
    )


@receiver(post_delete, sender=ProductVariant)
def sync_variant_restock_alerts_on_delete(sender, instance, **kwargs):
    if instance.product_id:
        _sync_restock_alerts(instance.product, was_restockable=True)
