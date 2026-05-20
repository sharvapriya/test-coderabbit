from django.core.management.base import BaseCommand

from sellers.services import LedgerService


class Command(BaseCommand):
    help = "Move seller ledger balances from pending to hold to available based on delivery and hold rules."

    def handle(self, *args, **options):
        transitions = LedgerService().process_eligibility_transitions()
        self.stdout.write(self.style.SUCCESS(f"Processed {len(transitions)} payout transition(s)."))
