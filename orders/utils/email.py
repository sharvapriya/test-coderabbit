from decimal import Decimal



from django.conf import settings

from django.core.mail import EmailMessage



from orders.models import Order





def _recipient_email(user, order):

    if user and getattr(user, "email", ""):

        return user.email

    return order.email





def _user_name(user, order):

    if user:

        full_name = getattr(user, "get_full_name", lambda: "")().strip()

        if full_name:

            return full_name

        username = getattr(user, "username", "").strip()

        if username:

            return username

    return order.full_name.strip() or "Customer"





def _format_amount(amount):

    normalized = (amount or Decimal("0")).quantize(Decimal("0.01"))

    return f"Rs.{normalized}"





def _support_footer():

    return f"For more information and further support, feel free to ask {settings.SUPPORT_EMAIL}."





def _build_order_email(subject, body, recipient_email):

    # Some SMTP providers reject messages when the From address does not match

    # the authenticated mailbox. Fall back to the SMTP user so delivery works

    # until a dedicated notifications mailbox is authenticated separately.

    from_email = settings.CUSTOMER_NOTIFICATIONS_EMAIL

    if settings.EMAIL_HOST_USER and from_email != settings.EMAIL_HOST_USER:

        from_email = settings.EMAIL_HOST_USER



    return EmailMessage(

        subject,

        body,

        from_email,

        [recipient_email],

        reply_to=settings.DEFAULT_REPLY_TO_EMAIL,

    )





def _send_customer_order_email(user, order, *, subject, message, amount=None):

    recipient_email = _recipient_email(user, order)

    if not recipient_email:

        return False



    body_lines = [

        f"Hello {_user_name(user, order)}:",

        "",

        f"Order ID: {order.id}",

        message,

    ]

    if amount is not None:

        body_lines.extend(["", f"Amount: {_format_amount(amount)}"])



    body_lines.extend(

        [

            "",

            _support_footer(),

        ]

    )



    try:

        email = _build_order_email(subject, "\n".join(body_lines), recipient_email)

        email.send(fail_silently=False)

        return True

    except Exception:

        return False


def order_placed_email(user, order):

    return _send_customer_order_email(

        user,

        order,

        subject=f"MyKart Store Order #{order.id} Placed Successfully",

        message=(

            "Thank you for shopping with MyKart Store.\n\n"

            f"We are pleased to inform you that your order #{order.id} "

            "has been placed successfully and is currently being processed by our team.\n\n"

            "You will receive further updates regarding shipping and delivery status shortly.\n\n"

            "We appreciate your trust in MyKart Store and look forward to serving you again.\n\n"

            "Best Regards,\n"

            "MyKart Store Team"

        ),

        amount=order.total_amount or order.get_total_cost(),

    )


def payment_confirmation_email(user, order):

    return _send_customer_order_email(

        user,

        order,

        subject=f"MyKart Store Payment Confirmed for Order #{order.id}",

        message=(

            f"We have successfully received your payment for order #{order.id}.\n\n"

            "Your transaction has been confirmed, and your order is now being prepared for shipment.\n\n"

            "Thank you for choosing MyKart Store. We truly value your business.\n\n"

            "Best Regards,\n"

            "MyKart Store Team"

        ),

        amount=order.total_amount or order.get_total_cost(),

    )


def order_shipped_email(user, order):

    return _send_customer_order_email(

        user,

        order,

        subject=f"MyKart Store Order #{order.id} Has Been Shipped",

        message=(

            f"We are happy to inform you that your order #{order.id} "

            "has been shipped successfully.\n\n"

            "Your package is now on its way and will be delivered to your registered address soon.\n\n"

            "You will receive another notification once your order has been delivered.\n\n"

            "Thank you for shopping with MyKart Store.\n\n"

            "Best Regards,\n"

            "MyKart Store Team"

        ),

    )


def order_delivered_email(user, order):

    return _send_customer_order_email(

        user,

        order,

        subject=f"MyKart Store Order #{order.id} Delivered Successfully",

        message=(

            f"We are pleased to inform you that your order #{order.id} "

            "has been delivered successfully.\n\n"

            "We hope you enjoy your purchase and are satisfied with our service.\n\n"

            "Thank you for choosing MyKart Store. We look forward to serving you again in the future.\n\n"

            "Best Regards,\n"

            "MyKart Store Team"

        ),

    )


def return_requested_email(user, order):

    return _send_customer_order_email(

        user,

        order,

        subject=f"MyKart Store Return Request Received for Order #{order.id}",

        message=(

            f"We have successfully received your return request for order #{order.id}.\n\n"

            "Our support team will review your request and process it according to our return policy.\n\n"

            "You will receive further updates regarding the status of your return shortly.\n\n"

            "Thank you for your patience and understanding.\n\n"

            "Best Regards,\n"

            "MyKart Store Team"

        ),

    )


def refund_processed_email(user, order, amount):

    return _send_customer_order_email(

        user,

        order,

        subject=f"MyKart Store Refund Processed for Order #{order.id}",

        message=(

            f"We would like to inform you that the refund for order #{order.id} "

            "has been processed successfully.\n\n"

            f"The refunded amount of ₹{amount} will be credited to your original "

            "payment method within the standard processing time of your bank or payment provider.\n\n"

            "If you have any questions or concerns, please feel free to contact our support team.\n\n"

            "Thank you for choosing MyKart Store.\n\n"

            "Best Regards,\n"

            "MyKart Store Team"

        ),

        amount=amount,

    )


def handle_order_status_change(order):

    user = getattr(order, "user", None)

    status_handlers = {

        Order.STATUS_PLACED: order_placed_email,

        Order.STATUS_PAID: payment_confirmation_email,

        Order.STATUS_SHIPPED: order_shipped_email,

        Order.STATUS_DELIVERED: order_delivered_email,

        Order.STATUS_RETURNED: return_requested_email,

    }



    handler = status_handlers.get(order.status)

    if handler:

        return handler(user, order)



    if order.status == Order.STATUS_REFUNDED:

        return refund_processed_email(user, order, order.total_amount or order.get_total_cost())



    return False

