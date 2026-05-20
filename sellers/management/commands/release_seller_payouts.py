"""
Release available payouts for sellers in bulk.
Processes and releases payouts for sellers with available balance.
"""
from decimal import Decimal
from django.core.management.base import BaseCommand
from django.utils import timezone
from sellers.models import SellerProfile
from sellers.services import PayoutService, WalletService


class Command(BaseCommand):
    help = "Release available payouts for sellers"

    def add_arguments(self, parser):
        parser.add_argument(
            '--seller-id',
            type=int,
            help='Release payout only for specific seller ID',
        )
        parser.add_argument(
            '--min-balance',
            type=float,
            default=0,
            help='Only release payouts if available balance >= this amount',
        )
        parser.add_argument(
            '--dry-run',
            action='store_true',
            dest='dry_run',
            help='Show what would be released without actually releasing',
        )

    def handle(self, *args, **options):
        seller_id = options.get('seller_id')
        min_balance = Decimal(str(options.get('min_balance', 0)))
        dry_run = options.get('dry_run', False)
        
        self.stdout.write("Releasing seller payouts...")
        
        if dry_run:
            self.stdout.write(self.style.WARNING("DRY RUN MODE - No payouts will be released"))
        
        # Get sellers
        sellers = SellerProfile.objects.filter(approval_status=SellerProfile.STATUS_APPROVED)
        if seller_id:
            sellers = sellers.filter(id=seller_id)
        
        payout_service = PayoutService()
        released_count = 0
        total_amount = Decimal('0.00')
        
        for seller in sellers:
            try:
                snapshot = WalletService.get_financial_snapshot(seller)
                available = snapshot['wallet'].available_balance
                
                if available < min_balance:
                    self.stdout.write(
                        f"⊘ {seller.business_name}: Insufficient balance (₹{available})"
                    )
                    continue
                
                if not dry_run:
                    payout = payout_service.release_available_balance(
                        seller=seller,
                        idempotency_key=f"cli-payout:{seller.id}:{timezone.now().timestamp()}",
                    )
                    self.stdout.write(
                        self.style.SUCCESS(
                            f"✓ {seller.business_name}: ₹{payout.amount} "
                            f"({payout.get_status_display()}) - {payout.reference}"
                        )
                    )
                    released_count += 1
                    total_amount += payout.amount
                else:
                    self.stdout.write(
                        f"→ {seller.business_name}: Would release ₹{available}"
                    )
                    released_count += 1
                    total_amount += available
                    
            except Exception as e:
                self.stdout.write(
                    self.style.ERROR(f"✗ {seller.business_name}: {str(e)}")
                )
        
        self.stdout.write(
            self.style.SUCCESS(f"\nReleased {released_count} payout(s) - Total: ₹{total_amount}")
        )
