from django.conf import settings
from django.utils import timezone
from accounts.models import Address, Profile


def site_context(request):
    account_profile_address = ""
    account_profile_address_short = ""
    if getattr(request, "user", None) and request.user.is_authenticated:
        default_address = (
            Address.objects.filter(user=request.user, is_default=True)
            .only("address_line", "city", "state", "country", "pincode")
            .first()
        )
        if default_address and default_address.formatted_address:
            account_profile_address = default_address.formatted_address
        else:
            profile = (
                Profile.objects.filter(user=request.user)
                .only("address_line", "city", "state", "country", "pincode")
                .first()
            )
            if profile and profile.formatted_address:
                account_profile_address = profile.formatted_address

        if account_profile_address:
            primary_address_part = account_profile_address.split(",")[0].strip()
            short_source = primary_address_part or account_profile_address
            account_profile_address_short = (
                short_source[:30] + "..." if len(short_source) > 30 else short_source
            )

    return {
        "site_business_name": settings.SITE_BUSINESS_NAME,
        "site_support_email": settings.SITE_SUPPORT_EMAIL,
        "site_support_phone": settings.SITE_SUPPORT_PHONE,
        "site_address_lines": settings.SITE_ADDRESS_LINES,
        "site_service_regions": settings.SITE_SERVICE_REGIONS,
        "site_shipping_processing_time": settings.SITE_SHIPPING_PROCESSING_TIME,
        "site_shipping_timeline": settings.SITE_SHIPPING_TIMELINE,
        "site_shipping_charges": settings.SITE_SHIPPING_CHARGES,
        "site_refund_timeline": settings.SITE_REFUND_TIMELINE,
        "site_return_window_days": settings.SITE_RETURN_WINDOW_DAYS,
        "site_current_year": timezone.now().year,
        "account_profile_address": account_profile_address,
        "account_profile_address_short": account_profile_address_short,
    }
