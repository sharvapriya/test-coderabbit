from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("sellers", "0016_payout_sellers_pay_seller__676e49_idx_and_more"),
    ]

    operations = [
        migrations.AddField(
            model_name="sellerprofile",
            name="brand_name",
            field=models.CharField(blank=True, max_length=120),
        ),
        migrations.AlterField(
            model_name="sellerprofile",
            name="registration_id",
            field=models.CharField(blank=True, max_length=18, null=True, unique=True),
        ),
    ]
