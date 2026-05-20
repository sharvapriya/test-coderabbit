from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ("products", "0007_productvariant"),
        ("cart", "0001_initial"),
    ]

    operations = [
        migrations.AddField(
            model_name="cartitem",
            name="variant",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.CASCADE,
                related_name="cart_items",
                to="products.productvariant",
            ),
        ),
    ]
