from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("products", "0005_productimage"),
    ]

    operations = [
        migrations.AddField(
            model_name="product",
            name="brand",
            field=models.CharField(blank=True, max_length=120),
        ),
        migrations.AddField(
            model_name="productimage",
            name="sort_order",
            field=models.PositiveSmallIntegerField(default=0),
        ),
    ]
