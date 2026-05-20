from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


def create_hub_delivery_rows(apps, schema_editor):
    SellerPayout = apps.get_model("sellers", "SellerPayout")
    HubProductDelivery = apps.get_model("sellers", "HubProductDelivery")

    hub_payouts = SellerPayout.objects.filter(delivery_mode="hub_delivery")
    for payout in hub_payouts:
        HubProductDelivery.objects.get_or_create(
            order_item_id=payout.order_item_id,
            defaults={
                "seller_id": payout.seller_id,
                "seller_payout_id": payout.id,
                "hub_name": "",
                "hub_address": "",
                "status": payout.delivery_status,
                "status_note": payout.delivery_status_note,
                "updated_by_id": payout.delivery_status_updated_by_id,
                "updated_at": payout.delivery_status_updated_at,
            },
        )


def delete_hub_delivery_rows(apps, schema_editor):
    HubProductDelivery = apps.get_model("sellers", "HubProductDelivery")
    HubProductDelivery.objects.all().delete()


class Migration(migrations.Migration):

    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ("orders", "0008_deliveryassignment"),
        ("sellers", "0007_sellerprofile_extended_registration_fields"),
    ]

    operations = [
        migrations.CreateModel(
            name="HubProductDelivery",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("hub_name", models.CharField(blank=True, max_length=120)),
                ("hub_address", models.TextField(blank=True)),
                (
                    "status",
                    models.CharField(
                        choices=[
                            ("pending", "Pending"),
                            ("handed_to_hub", "Handed over to hub"),
                            ("at_hub", "Received at hub"),
                            ("out_for_delivery", "Out for delivery"),
                            ("delivered", "Delivered"),
                        ],
                        default="pending",
                        max_length=30,
                    ),
                ),
                ("status_note", models.CharField(blank=True, max_length=255)),
                ("updated_at", models.DateTimeField(blank=True, null=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                (
                    "order_item",
                    models.OneToOneField(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="hub_delivery",
                        to="orders.orderitem",
                    ),
                ),
                (
                    "seller",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="hub_deliveries",
                        to="sellers.sellerprofile",
                    ),
                ),
                (
                    "seller_payout",
                    models.OneToOneField(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="hub_delivery_record",
                        to="sellers.sellerpayout",
                    ),
                ),
                (
                    "updated_by",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="updated_hub_delivery_status",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
            ],
            options={
                "verbose_name": "Hub product delivery",
                "verbose_name_plural": "Hub product deliveries",
                "ordering": ("-created_at",),
            },
        ),
        migrations.RunPython(create_hub_delivery_rows, delete_hub_delivery_rows),
    ]
