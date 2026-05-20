from django.conf import settings
from django.core.mail import EmailMessage


def send_restock_email(user, product):
    recipient_email = getattr(user, "email", "").strip()
    if not recipient_email:
        return False

    site_url = getattr(settings, "SITE_URL", "https://www.mykartstore.com").rstrip("/")
    product_url = f"{site_url}{product.get_absolute_url()}"
    subject = f"{product.name} is back in stock at MyKartStore"
    body = (
        f"Hello {user.username},\n\n"
        f"The product you asked us to watch is back in stock:\n"
        f"{product.name}\n\n"
        f"You can view it here:\n{product_url}\n\n"
        f"For more information and further support, feel free to ask {settings.SUPPORT_EMAIL}."
    )

    from_email = settings.CUSTOMER_NOTIFICATIONS_EMAIL
    if settings.EMAIL_HOST_USER and from_email != settings.EMAIL_HOST_USER:
        from_email = settings.EMAIL_HOST_USER

    try:
        EmailMessage(
            subject,
            body,
            from_email,
            [recipient_email],
            reply_to=settings.DEFAULT_REPLY_TO_EMAIL,
        ).send(fail_silently=False)
        return True
    except Exception:
        return False
