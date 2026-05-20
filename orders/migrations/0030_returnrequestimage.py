from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("orders", "0029_orderitem_gst_amount_orderitem_gst_rate_and_more"),
    ]

    operations = [
        migrations.CreateModel(
            name="ReturnRequestImage",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("image", models.ImageField(upload_to="return_requests/%Y/%m/%d/")),
                ("uploaded_at", models.DateTimeField(auto_now_add=True)),
                (
                    "return_request",
                    models.ForeignKey(
                        on_delete=models.deletion.CASCADE,
                        related_name="images",
                        to="orders.returnrequest",
                    ),
                ),
            ],
            options={
                "ordering": ("uploaded_at",),
            },
        ),
    ]
