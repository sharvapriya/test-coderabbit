import random

from django.conf import settings
from django.db import migrations, models
from django.utils import timezone


def _generate_unique_code(used_codes):
    for _ in range(1000):
        code = f"{random.randint(0, 999999):06d}"
        if code not in used_codes:
            used_codes.add(code)
            return code
    raise RuntimeError("Could not generate unique 6-digit code")


def seed_existing_profiles(apps, schema_editor):
    SellerProfile = apps.get_model("sellers", "SellerProfile")

    used_registration_ids = set(
        SellerProfile.objects.exclude(registration_id__isnull=True)
        .exclude(registration_id="")
        .values_list("registration_id", flat=True)
    )
    used_seller_ids = set(
        SellerProfile.objects.exclude(seller_id__isnull=True)
        .exclude(seller_id="")
        .values_list("seller_id", flat=True)
    )

    now = timezone.now()

    for profile in SellerProfile.objects.all():
        updated_fields = []

        if not profile.registration_id:
            profile.registration_id = _generate_unique_code(used_registration_ids)
            updated_fields.append("registration_id")

        if profile.approval_status == "pending":
            profile.approval_status = "approved"
            updated_fields.append("approval_status")

        if profile.approval_status == "approved":
            if not profile.seller_id:
                profile.seller_id = _generate_unique_code(used_seller_ids)
                updated_fields.append("seller_id")
            if not profile.approved_at:
                profile.approved_at = now
                updated_fields.append("approved_at")

        if updated_fields:
            profile.save(update_fields=updated_fields)


class Migration(migrations.Migration):

    dependencies = [
        ("sellers", "0005_completedsellerpayout_and_more"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.AddField(
            model_name="sellerprofile",
            name="approval_status",
            field=models.CharField(
                choices=[
                    ("pending", "Pending approval"),
                    ("approved", "Approved"),
                    ("rejected", "Rejected"),
                ],
                default="pending",
                max_length=20,
            ),
        ),
        migrations.AddField(
            model_name="sellerprofile",
            name="approved_at",
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="sellerprofile",
            name="approved_by",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=models.SET_NULL,
                related_name="approved_seller_profiles",
                to=settings.AUTH_USER_MODEL,
            ),
        ),
        migrations.AddField(
            model_name="sellerprofile",
            name="registration_id",
            field=models.CharField(blank=True, max_length=6, null=True, unique=True),
        ),
        migrations.AddField(
            model_name="sellerprofile",
            name="seller_id",
            field=models.CharField(blank=True, max_length=6, null=True, unique=True),
        ),
        migrations.RunPython(seed_existing_profiles, migrations.RunPython.noop),
    ]
