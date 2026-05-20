from django.db import transaction
from orders.models import Order

def run():
    batch_size = 200

    qs = Order.objects.filter(public_id__isnull=True).order_by('id')

    total = qs.count()
    processed = 0

    while qs.exists():
        batch = list(qs[:batch_size])

        with transaction.atomic():
            for order in batch:
                order.assign_public_id()

            Order.objects.bulk_update(
                batch,
                ['public_id', 'public_id_year', 'public_id_sequence']
            )

        processed += len(batch)
        print(f"Processed: {processed}/{total}")

    print("✅ Backfill completed safely")