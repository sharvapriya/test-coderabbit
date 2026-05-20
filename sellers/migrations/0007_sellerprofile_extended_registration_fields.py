from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("products", "0001_initial"),
        ("sellers", "0006_sellerprofile_approval_and_ids"),
    ]

    operations = [
        migrations.AddField(
            model_name="sellerprofile",
            name="alternate_phone",
            field=models.CharField(blank=True, max_length=30),
        ),
        migrations.AddField(
            model_name="sellerprofile",
            name="contact_email",
            field=models.EmailField(default="", max_length=254),
            preserve_default=False,
        ),
        migrations.AddField(
            model_name="sellerprofile",
            name="contact_person_name",
            field=models.CharField(default="", max_length=150),
            preserve_default=False,
        ),
        migrations.AddField(
            model_name="sellerprofile",
            name="msme_details",
            field=models.TextField(blank=True),
        ),
        migrations.AddField(
            model_name="sellerprofile",
            name="pan_card_number",
            field=models.CharField(default="", max_length=10),
            preserve_default=False,
        ),
        migrations.AddField(
            model_name="sellerprofile",
            name="pan_card_photo",
            field=models.ImageField(default="", upload_to="seller_documents/pan_cards/"),
            preserve_default=False,
        ),
        migrations.AddField(
            model_name="sellerprofile",
            name="product_categories",
            field=models.ManyToManyField(blank=True, related_name="seller_profiles", to="products.category"),
        ),
        migrations.AddField(
            model_name="sellerprofile",
            name="registered_office_address",
            field=models.TextField(default=""),
            preserve_default=False,
        ),
        migrations.AddField(
            model_name="sellerprofile",
            name="supplier_details",
            field=models.TextField(default=""),
            preserve_default=False,
        ),
        migrations.AddField(
            model_name="sellerprofile",
            name="terms_accepted",
            field=models.BooleanField(default=False),
        ),
        migrations.AddField(
            model_name="sellerprofile",
            name="terms_accepted_at",
            field=models.DateTimeField(blank=True, null=True),
        ),
    ]
