from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ("orders", "0006_order_total_amount"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name="PaymentTransaction",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                (
                    "payment_method",
                    models.CharField(
                        choices=[("cod", "Cash on delivery"), ("online", "Online payment")],
                        max_length=20,
                    ),
                ),
                (
                    "gateway",
                    models.CharField(
                        choices=[("cod", "Cash on delivery"), ("razorpay", "Razorpay")],
                        max_length=20,
                    ),
                ),
                (
                    "status",
                    models.CharField(
                        choices=[("initiated", "Initiated"), ("success", "Success"), ("failed", "Failed")],
                        default="initiated",
                        max_length=20,
                    ),
                ),
                ("amount", models.DecimalField(decimal_places=2, max_digits=12)),
                ("currency", models.CharField(default="INR", max_length=10)),
                ("gateway_order_id", models.CharField(blank=True, max_length=120)),
                ("gateway_payment_id", models.CharField(blank=True, max_length=120)),
                ("gateway_signature", models.CharField(blank=True, max_length=255)),
                ("failure_reason", models.CharField(blank=True, max_length=255)),
                ("raw_response", models.JSONField(blank=True, default=dict)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                (
                    "order",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="payment_transactions",
                        to="orders.order",
                    ),
                ),
                (
                    "user",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="payment_transactions",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
            ],
            options={"ordering": ("-created_at",)},
        ),
    ]
