from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


def migrate_order_statuses(apps, schema_editor):
    Order = apps.get_model("orders", "Order")
    OrderItem = apps.get_model("orders", "OrderItem")

    Order.objects.filter(status="active").update(status="placed")
    Order.objects.filter(status="partially_cancelled").update(status="partially_cancelled")
    Order.objects.filter(status="cancelled").update(status="cancelled")

    OrderItem.objects.filter(cancellation_reason__isnull=True).update(cancellation_reason="")


class Migration(migrations.Migration):

    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ("orders", "0013_order_and_item_cancellation"),
    ]

    operations = [
        migrations.AddField(
            model_name="order",
            name="cancelled_at",
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="order",
            name="cancelled_by",
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="cancelled_orders", to=settings.AUTH_USER_MODEL),
        ),
        migrations.AddField(
            model_name="order",
            name="cancellation_reason",
            field=models.CharField(blank=True, default="", max_length=255),
        ),
        migrations.AddField(
            model_name="orderitem",
            name="cancelled_by",
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="cancelled_order_items", to=settings.AUTH_USER_MODEL),
        ),
        migrations.AddField(
            model_name="orderitem",
            name="cancellation_reason",
            field=models.CharField(blank=True, default="", max_length=255),
        ),
        migrations.AlterField(
            model_name="order",
            name="status",
            field=models.CharField(
                choices=[
                    ("placed", "Placed"),
                    ("confirmed", "Confirmed"),
                    ("packed", "Packed"),
                    ("shipped", "Shipped"),
                    ("out_for_delivery", "Out for delivery"),
                    ("delivered", "Delivered"),
                    ("partially_cancelled", "Partially cancelled"),
                    ("cancelled", "Cancelled"),
                ],
                default="placed",
                max_length=30,
            ),
        ),
        migrations.CreateModel(
            name="OrderStatusHistory",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("from_status", models.CharField(blank=True, max_length=30)),
                ("to_status", models.CharField(max_length=30)),
                ("reason", models.CharField(blank=True, max_length=255)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("metadata", models.JSONField(blank=True, default=dict)),
                ("changed_by", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="order_status_updates", to=settings.AUTH_USER_MODEL)),
                ("order", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="status_history", to="orders.order")),
                ("order_item", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.CASCADE, related_name="status_history", to="orders.orderitem")),
            ],
            options={
                "ordering": ("-created_at", "-id"),
            },
        ),
        migrations.RunPython(migrate_order_statuses, migrations.RunPython.noop),
    ]
