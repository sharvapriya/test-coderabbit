from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("orders", "0030_returnrequestimage"),
    ]

    operations = [
        migrations.AlterField(
            model_name="returnrequest",
            name="status",
            field=models.CharField(
                choices=[
                    ("pending", "Pending"),
                    ("approved", "Approved"),
                    ("picked_up", "Picked Up"),
                    ("refunded", "Refunded"),
                    ("rejected", "Rejected"),
                    ("withdrawn", "Withdrawn"),
                    ("shipped_by_buyer", "Shipped by Buyer"),
                    ("received_by_seller", "Received by Seller"),
                    ("refund_completed", "Refund Completed"),
                ],
                default="pending",
                max_length=20,
            ),
        ),
    ]
