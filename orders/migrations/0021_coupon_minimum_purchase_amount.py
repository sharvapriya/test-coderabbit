from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("orders", "0019_order_delivery_charge_order_delivery_type_and_more"),
    ]

    operations = [
        migrations.AddField(
            model_name="coupon",
            name="minimum_purchase_amount",
            field=models.DecimalField(decimal_places=2, default=0, max_digits=10),
        ),
    ]