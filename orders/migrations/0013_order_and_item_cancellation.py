from django.db import migrations, models


def set_existing_statuses(apps, schema_editor):
    Order = apps.get_model("orders", "Order")
    OrderItem = apps.get_model("orders", "OrderItem")
    Order.objects.filter(status__isnull=True).update(status="active")
    OrderItem.objects.filter(status__isnull=True).update(status="active")


class Migration(migrations.Migration):

    dependencies = [
        ("orders", "0012_review_reviewimage"),
    ]

    operations = [
        migrations.AddField(
            model_name="order",
            name="status",
            field=models.CharField(
                choices=[
                    ("active", "Active"),
                    ("partially_cancelled", "Partially cancelled"),
                    ("cancelled", "Cancelled"),
                ],
                default="active",
                max_length=30,
            ),
        ),
        migrations.AddField(
            model_name="orderitem",
            name="cancelled_at",
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="orderitem",
            name="status",
            field=models.CharField(
                choices=[("active", "Active"), ("cancelled", "Cancelled")],
                default="active",
                max_length=20,
            ),
        ),
        migrations.RunPython(set_existing_statuses, migrations.RunPython.noop),
    ]
