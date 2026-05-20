"""
Send payout summary emails to sellers.
Sends periodic summaries of payouts in the past N days.
"""
from django.core.management.base import BaseCommand
from django.utils import timezone
from sellers.models import SellerProfile
from sellers.utils.payout_emails import send_payout_summary_email


class Command(BaseCommand):
    help = "Send payout summary emails to sellers"

    def add_arguments(self, parser):
        parser.add_argument(
            '--days',
            type=int,
            default=30,
            help='Number of days to include in summary (default: 30)',
        )
        parser.add_argument(
            '--seller-id',
            type=int,
            help='Send summary only to specific seller ID',
        )
        parser.add_argument(
            '--dry-run',
            action='store_true',
            dest='dry_run',
            help='Show what would be sent without actually sending',
        )

    def handle(self, *args, **options):
        days = options.get('days', 30)
        seller_id = options.get('seller_id')
        dry_run = options.get('dry_run', False)
        
        self.stdout.write(f"Sending payout summaries (last {days} days)...")
        
        if dry_run:
            self.stdout.write(self.style.WARNING("DRY RUN MODE - No emails will be sent"))
        
        # Get sellers to send summaries to
        sellers = SellerProfile.objects.filter(approval_status=SellerProfile.STATUS_APPROVED)
        if seller_id:
            sellers = sellers.filter(id=seller_id)
        
        sent_count = 0
        for seller in sellers:
            try:
                if not dry_run:
                    send_payout_summary_email(seller, summary_period_days=days)
                sent_count += 1
                self.stdout.write(
                    self.style.SUCCESS(f"✓ {seller.business_name} ({seller.id})")
                )
            except Exception as e:
                self.stdout.write(
                    self.style.ERROR(f"✗ {seller.business_name} ({seller.id}): {str(e)}")
                )
        
        self.stdout.write(self.style.SUCCESS(f"\nSent {sent_count} email(s)"))
