from django.conf import settings

from django.core.mail import EmailMessage





def _with_support_footer(body):

    support_footer = (

        f"For more information and further support, feel free to ask {settings.SUPPORT_EMAIL}."

    )

    if support_footer in body:

        return body

    return f"{body.rstrip()}\n\n{support_footer}"





def build_email_message(subject, body, recipient_list, from_email, reply_to=None):

    return EmailMessage(

        subject,

        _with_support_footer(body),

        from_email,

        recipient_list,

        reply_to=reply_to or settings.DEFAULT_REPLY_TO_EMAIL,

    )





def send_welcome_email(user):

    email = build_email_message(

        "Welcome to MyKartStore",

        (

            f"Dear {user.username},\n\n"

            "Welcome to MyKartStore!\n\n"

            "We are delighted to have you as part of our community. "

            "Your account has been created successfully, and you can now explore "

            "a wide range of products, manage your orders, and enjoy a seamless shopping experience.\n\n"

            "At MyKartStore, we are committed to providing you with quality service "

            "and a secure platform for all your shopping needs.\n\n"

            "If you have any questions or require assistance, please feel free to "

            "reach out to our support team.\n\n"

            "Thank you for choosing MyKartStore.\n\n"

            "Best Regards,\n"

            "MyKartStore Team"

        ),

        [user.email],

        settings.ACCOUNT_NOTIFICATIONS_EMAIL,

    )

    email.send(fail_silently=False)


def send_password_changed_email(recipient_email):

    email = build_email_message(

        "Your MyKartStore Password Has Been Changed",

        (

            "Dear User,\n\n"

            "This is to inform you that your MyKartStore account password "

            "has been changed successfully.\n\n"

            "If you made this change, no further action is required.\n\n"

            "However, if you did not initiate this password change, we strongly "

            "recommend that you reset your password immediately and contact our "

            "support team for further assistance.\n\n"

            "Your account security is very important to us.\n\n"

            "Best Regards,\n"

            "MyKartStore Team"

        ),

        [recipient_email],

        settings.ACCOUNT_NOTIFICATIONS_EMAIL,

    )

    email.send(fail_silently=False)
