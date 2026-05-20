from django.db.models.signals import post_save, pre_save
from django.dispatch import receiver

from orders.models import Order
from orders.utils.email import handle_order_status_change


@receiver(pre_save, sender=Order)
def capture_previous_order_status(sender, instance, **kwargs):
    if not instance.pk:
        instance._previous_status = None
        return

    previous_status = (
        sender.objects.filter(pk=instance.pk).values_list("status", flat=True).first()
    )
    instance._previous_status = previous_status


@receiver(post_save, sender=Order)
def send_order_status_notification(sender, instance, created, **kwargs):
    if created:
        return
    
    if getattr(instance, "_skip_status_email_signal", False):
        return


    previous_status = getattr(instance, "_previous_status", None)
    if previous_status == instance.status:
        return

    handle_order_status_change(instance)
