from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("sellers", "0014_sellerprofile_seller_signature"),
    ]

    operations = [
        migrations.AddField(
            model_name="sellerprofile",
            name="payout_phonepay_gpay_number",
            field=models.CharField(blank=True, max_length=15),
        ),
    ]
