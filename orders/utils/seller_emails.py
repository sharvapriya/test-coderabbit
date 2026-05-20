import logging

from django.conf import settings
from django.core.mail import EmailMessage


logger = logging.getLogger(__name__)

SELLER_FROM_EMAIL = "business@mykartstore.com"
SELLER_REPLY_TO_EMAIL = "support@mykartstore.com"
SELLER_BUSINESS_EMAIL = "business@mykartstore.com"


def _delivery_from_email():
    smtp_user = (getattr(settings, "EMAIL_HOST_USER", "") or "").strip()
    if smtp_user and smtp_user.lower() != SELLER_FROM_EMAIL.lower():
        logger.warning(
            "Seller email using authenticated SMTP sender instead of requested business mailbox",
            extra={"requested_from": SELLER_FROM_EMAIL, "smtp_user": smtp_user},
        )
        return smtp_user
    return SELLER_FROM_EMAIL


def _with_support_footer(body):
    support_footer = f"For more information and further support, feel free to ask {settings.SUPPORT_EMAIL}."
    if support_footer in body:
        return body
    return f"{body.rstrip()}\n\n{support_footer}"


def send_seller_email(subject, body, to_email):
    email = EmailMessage(
        subject=subject,
        body=_with_support_footer(body),
        from_email=_delivery_from_email(),
        to=[to_email],
        reply_to=[SELLER_REPLY_TO_EMAIL],
    )
    try:
        sent_count = email.send(fail_silently=False)
        logger.info("Seller email sent", extra={"subject": subject, "to_email": to_email, "sent_count": sent_count})
        return sent_count
    except Exception:
        logger.exception("Seller email failed", extra={"subject": subject, "to_email": to_email})
        raise


def _seller_recipient_email(seller):
    contact_email = getattr(seller, "contact_email", "") or ""
    if contact_email:
        return contact_email

    user = getattr(seller, "user", None)
    return getattr(user, "email", "") or ""


def notify_new_seller_registration(seller):

    return send_seller_email(

        "New Seller Registration",

        (

            "📢 **New Seller Registration Alert**\n\n"

            f"A new seller registration has been received from "
            f"**{seller.business_name}**.\n\n"

            "The seller has successfully completed and submitted the "
            "**seller registration application** on **MyKart Store**.\n\n"

            "The application is currently awaiting **verification and approval** "
            "from the administration team.\n\n"

            "Please review the submitted seller details, verify the provided "
            "documents, and proceed with the necessary onboarding and approval process.\n\n"

            "Timely verification will help ensure a smooth onboarding experience "
            "for the seller.\n\n"

            "**Best Regards,**\n"
            "MyKart Store Team"

        ),

        SELLER_BUSINESS_EMAIL,

    )

def notify_seller_registration_received(seller):

    seller_email = _seller_recipient_email(seller)

    if not seller_email:

        logger.warning(
            "Skipped seller registration confirmation email because recipient was missing",
            extra={"seller_id": seller.id}
        )

        return 0

    return send_seller_email(

        "Seller Registration Submitted Successfully",

        (

            f"Dear {seller.business_name},\n\n"

            "Thank you for registering as a seller with **MyKart Store**.\n\n"

            "Your seller registration has been **submitted successfully** and is currently "
            "**under review**.\n\n"

            f"**Registration ID:** {seller.registration_id}\n\n"

            "Our verification team will carefully review your application details "
            "and notify you once the approval process has been completed.\n\n"

            "We appreciate your interest in partnering with **MyKart Store** "
            "and look forward to supporting your business journey.\n\n"

            "**Best Regards,**\n"
            "MyKart Store Team"

        ),

        seller_email,

    )

def notify_seller_registration_id_generated(seller):

    return send_seller_email(

        "Seller Registration ID Generated",

        (

            "🆔 **Seller Registration ID Generated Successfully**\n\n"

            f"A registration ID has been successfully generated for seller "
            f"**{seller.business_name}**.\n\n"

            f"**Registration ID:** {seller.registration_id}\n\n"

            "The seller application has now been officially recorded in the system "
            "and is available for **review, verification, and further processing**.\n\n"

            "Please use the generated registration ID for future communication, "
            "tracking, and approval-related activities.\n\n"

            "**Best Regards,**\n"
            "MyKart Store Team"

        ),

        SELLER_BUSINESS_EMAIL,

    )


def notify_seller_application_status_update(seller):

    status = "Approved" if seller.is_approved else "Rejected"

    return send_seller_email(

        f"Seller Application {status}",

        (

            f"📌 **Seller Application Status Update**\n\n"

            f"The seller application submitted by "
            f"**{seller.business_name}** has been "
            f"**{status.upper()}**.\n\n"

            +

            (

                "✅ The seller has successfully met all required verification "
                "and approval criteria.\n\n"

                "The seller account can now proceed with onboarding activities "
                "and product publishing on **MyKart Store**.\n\n"

                if seller.is_approved else

                "❌ The seller application did not meet the required approval "
                "criteria during the verification process.\n\n"

                "Please review the application details and records for additional "
                "information regarding the rejection.\n\n"

            )

            +

            "Kindly refer to the seller dashboard or internal records for "
            "**complete application details and status history**.\n\n"

            "**Best Regards,**\n"
            "MyKart Store Team"

        ),

        SELLER_BUSINESS_EMAIL,

    )

def notify_seller_application_status_to_seller(seller):

    seller_email = _seller_recipient_email(seller)

    if not seller_email:

        logger.warning(
            "Skipped seller application decision email because recipient was missing",
            extra={"seller_id": seller.id}
        )

        return 0

    status = "Approved" if seller.is_approved else "Rejected"

    return send_seller_email(

        f"Seller Application {status}",

        (

            f"Dear {seller.business_name},\n\n"

            f"We would like to inform you that your seller application "
            f"has been **{status.upper()}**.\n\n"

            +

            (

                "🎉 **Congratulations!** Your seller account has been "
                "**approved successfully**.\n\n"

                "You can now start publishing products, managing inventory, "
                "and selling through **MyKart Store**.\n\n"

                if seller.is_approved else

                "Unfortunately, your application did not meet our current "
                "**approval requirements**.\n\n"

                "For additional clarification or support, please contact our "
                "**support team**.\n\n"

            )

            +

            "Thank you for choosing **MyKart Store**.\n\n"

            "**Best Regards,**\n"
            "MyKart Store Team"

        ),

        seller_email,

    )


def notify_product_published(product, seller):

    seller_email = _seller_recipient_email(seller)

    if not seller_email:

        logger.warning(
            "Skipped product published seller email because recipient was missing",
            extra={"product_id": product.id}
        )

        return 0

    return send_seller_email(

        "Product Published Successfully",

        (

            f"Dear {seller.business_name},\n\n"

            f"We are pleased to inform you that your product "
            f"**'{product.name}'** has been **published successfully** "
            "on **MyKart Store**.\n\n"

            "Your product is now **live and visible to customers** "
            "for purchase.\n\n"

            "You can manage your product details, pricing, inventory, "
            "and customer orders through your **Seller Dashboard**.\n\n"

            "Thank you for partnering with **MyKart Store**.\n\n"

            "**Best Regards,**\n"
            "MyKart Store Team"

        ),

        seller_email,

    )


def notify_product_status_update(product):

    seller_product = getattr(product, "seller_product", None)
    seller = getattr(seller_product, "seller", None)
    seller_email = _seller_recipient_email(seller)

    if not seller_email:

        logger.warning(
            "Skipped product status email because recipient was missing",
            extra={"product_id": product.id},
        )

        return 0

    final_status = "Approved" if product.status == product.STATUS_APPROVED else "Rejected"

    body_lines = [

        "📦 **Product Status Update Notification**\n",

        f"Dear Seller,\n\n"

        f"We would like to inform you that the status of your product "
        f"**'{product.name}'** has been updated successfully.\n\n",

        f"**Final Status:** {final_status.upper()}\n",

    ]

    if product.rejection_reason:

        body_lines.append(

            f"**Rejection Reason:** {product.rejection_reason}\n\n"

            "Please review the above reason carefully and make the necessary "
            "changes before resubmitting the product for approval.\n"

        )

    else:

        body_lines.append(

            "✅ Your product has successfully passed the verification and "
            "approval process.\n\n"

            "The product is now available for customers to view and purchase "
            "on **MyKart Store**.\n"

        )

    body_lines.append(

        "\nThank you for partnering with **MyKart Store**.\n\n"

        "**Best Regards,**\n"
        "MyKart Store Team"

    )

    return send_seller_email(

        f"Product {final_status}",

        "\n".join(body_lines),

        seller_email,

    )


def notify_new_order_received(order, seller):

    seller_email = _seller_recipient_email(seller)

    if not seller_email:

        logger.warning(
            "Skipped new order seller email because recipient was missing",
            extra={"order_id": order.id}
        )

        return 0

    return send_seller_email(

        "New Order Received",

        (

            "🛒 **New Order Notification**\n\n"

            f"Dear {seller.business_name},\n\n"

            "You have received a **new customer order** on "
            "**MyKart Store**.\n\n"

            f"**Order ID:** #{order.id}\n\n"

            "Please review the order details in your seller dashboard and "
            "begin processing the shipment at the earliest.\n\n"

            "Timely order processing and delivery help improve customer "
            "satisfaction and seller performance.\n\n"

            "Thank you for selling with **MyKart Store**.\n\n"

            "**Best Regards,**\n"
            "MyKart Store Team"

        ),

        seller_email,

    )

