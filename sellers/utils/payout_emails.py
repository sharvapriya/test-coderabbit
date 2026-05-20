"""Email utilities for seller payout notifications."""
from decimal import Decimal
from django.core.mail import send_mail
from django.template.loader import render_to_string
from django.conf import settings
from django.utils import timezone


def send_payout_released_email(seller, payout):
    """
    Send email notification when payout is released.
    
    Args:
        seller: SellerProfile instance
        payout: Payout instance
    """
    context = {
        'seller_name': seller.business_name,
        'seller_id': seller.seller_id or seller.id,
        'amount': payout.amount,
        'currency': 'INR',
        'reference': payout.reference,
        'created_at': payout.created_at.strftime('%d %b %Y, %H:%M'),
        'status': payout.get_status_display(),
        'dashboard_url': f"{settings.SITE_URL}/seller/wallet/",
    }
    
    subject = f"Payout Released - ₹{payout.amount} - Reference: {payout.reference}"
    
    try:
        html_message = render_to_string('sellers/emails/payout_released.html', context)
    except Exception:
        html_message = None
    
    message = f"""
Hello {seller.business_name},

Your payout has been released successfully!

Amount: ₹{payout.amount}
Reference ID: {payout.reference}
Status: {payout.get_status_display()}
Date: {context['created_at']}

You can track your payout status in your dashboard: {context['dashboard_url']}

Best regards,
MyKartStore Team
"""
    
    send_mail(
        subject=subject,
        message=message,
        from_email=settings.DEFAULT_FROM_EMAIL,
        recipient_list=[seller.contact_email],
        html_message=html_message,
        fail_silently=True,
    )


def send_payout_failed_email(seller, payout):
    """
    Send email notification when payout fails.
    
    Args:
        seller: SellerProfile instance
        payout: Payout instance
    """
    context = {
        'seller_name': seller.business_name,
        'seller_id': seller.seller_id or seller.id,
        'amount': payout.amount,
        'currency': 'INR',
        'reference': payout.reference,
        'created_at': payout.created_at.strftime('%d %b %Y, %H:%M'),
        'failure_reason': payout.failure_reason or 'Unknown error',
        'dashboard_url': f"{settings.SITE_URL}/seller/wallet/",
        'support_email': getattr(settings, 'SUPPORT_EMAIL', 'support@mykartstore.com'),
    }
    
    subject = f"Payout Failed - ₹{payout.amount} - Reference: {payout.reference}"
    
    try:
        html_message = render_to_string('sellers/emails/payout_failed.html', context)
    except Exception:
        html_message = None
    
    message = f"""
Hello {seller.business_name},

Unfortunately, your payout could not be processed.

Amount: ₹{payout.amount}
Reference ID: {payout.reference}
Failure Reason: {context['failure_reason']}
Date Attempted: {context['created_at']}

The amount remains in your account and will be available for the next payout attempt.

Please contact our support team if you have any questions: {context['support_email']}

Best regards,
MyKartStore Team
"""
    
    send_mail(
        subject=subject,
        message=message,
        from_email=settings.DEFAULT_FROM_EMAIL,
        recipient_list=[seller.contact_email],
        html_message=html_message,
        fail_silently=True,
    )


def send_balance_available_email(seller, available_balance):
    """
    Send email notification when balance becomes available for payout.
    
    Args:
        seller: SellerProfile instance
        available_balance: Decimal amount available
    """
    context = {
        'seller_name': seller.business_name,
        'seller_id': seller.seller_id or seller.id,
        'amount': available_balance,
        'currency': 'INR',
        'dashboard_url': f"{settings.SITE_URL}/seller/wallet/",
    }
    
    subject = f"Payout Available - ₹{available_balance} ready for withdrawal"
    
    try:
        html_message = render_to_string('sellers/emails/balance_available.html', context)
    except Exception:
        html_message = None
    
    message = f"""
Hello {seller.business_name},

Great news! Your balance is now available for payout.

Available Balance: ₹{available_balance}

You can now request a payout from your dashboard: {context['dashboard_url']}

Best regards,
MyKartStore Team
"""
    
    send_mail(
        subject=subject,
        message=message,
        from_email=settings.DEFAULT_FROM_EMAIL,
        recipient_list=[seller.contact_email],
        html_message=html_message,
        fail_silently=True,
    )


def send_payout_summary_email(seller, summary_period_days=30):
    """
    Send periodic payout summary email to seller.
    
    Args:
        seller: SellerProfile instance
        summary_period_days: Number of days to include in summary
    """
    from sellers.models import Payout
    from datetime import timedelta
    
    cutoff_date = timezone.now() - timedelta(days=summary_period_days)
    payouts = Payout.objects.filter(
        seller=seller,
        created_at__gte=cutoff_date,
        status=Payout.STATUS_COMPLETED,
    ).order_by('-created_at')
    
    if not payouts.exists():
        return
    
    total_amount = sum(p.amount for p in payouts) or Decimal('0.00')
    
    context = {
        'seller_name': seller.business_name,
        'seller_id': seller.seller_id or seller.id,
        'period_days': summary_period_days,
        'total_payouts': payouts.count(),
        'total_amount': total_amount,
        'currency': 'INR',
        'payouts': payouts[:10],  # Show last 10
        'dashboard_url': f"{settings.SITE_URL}/seller/payout-history/",
    }
    
    subject = f"Payout Summary - Last {summary_period_days} days"
    
    try:
        html_message = render_to_string('sellers/emails/payout_summary.html', context)
    except Exception:
        html_message = None
    
    message = f"""
Hello {seller.business_name},

Here's your payout summary for the last {summary_period_days} days:

Total Payouts: {context['total_payouts']}
Total Amount: ₹{context['total_amount']}

View detailed history: {context['dashboard_url']}

Best regards,
MyKartStore Team
"""
    
    send_mail(
        subject=subject,
        message=message,
        from_email=settings.DEFAULT_FROM_EMAIL,
        recipient_list=[seller.contact_email],
        html_message=html_message,
        fail_silently=True,
    )
