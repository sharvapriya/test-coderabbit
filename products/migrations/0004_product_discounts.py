from decimal import Decimal

from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("products", "0003_stockalertsubscription"),
    ]

    operations = [
        migrations.AddField(
            model_name="product",
            name="discount_percent",
            field=models.DecimalField(
                blank=True,
                decimal_places=2,
                default=Decimal("0.00"),
                max_digits=5,
            ),
        ),
        migrations.AddField(
            model_name="product",
            name="discount_amount",
            field=models.DecimalField(
                blank=True,
                decimal_places=2,
                default=Decimal("0.00"),
                max_digits=10,
            ),
        ),
    ]
