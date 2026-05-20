"""
Process payout eligibility transitions.
Automatically transitions earnings through the payout status lifecycle.
"""
from django.core.management.base import BaseCommand
from django.utils import timezone
from sellers.services import LedgerService


class Command(BaseCommand):
    help = "Process automatic payout eligibility transitions (pending → hold → available)"

    def add_arguments(self, parser):
        parser.add_argument(
            '--dry-run',
            action='store_true',
            dest='dry_run',
            help='Show what would be done without making changes',
        )

    def handle(self, *args, **options):
        service = LedgerService()
        dry_run = options.get('dry_run', False)
        
        self.stdout.write("Processing payout eligibility transitions...")
        
        if dry_run:
            self.stdout.write(self.style.WARNING("DRY RUN MODE - No changes will be made"))
        
        transitions = service.process_eligibility_transitions()
        
        if transitions:
            self.stdout.write(self.style.SUCCESS(f"✓ Processed {len(transitions)} transitions"))
            for transition in transitions:
                self.stdout.write(
                    f"  - Order #{transition['order_id']} (Seller #{transition['seller_id']}): "
                    f"→ {transition['to_status']}"
                )
        else:
            self.stdout.write("No transitions to process.")
        
        self.stdout.write(self.style.SUCCESS("Completed successfully!"))
