from decimal import Decimal

from django.core.management.base import BaseCommand
from django.core.exceptions import ValidationError

from orders.models import OrderItem
from products.models import Product
from sellers.models import SellerLedger
from sellers.services import LedgerService, PayoutCalculator, WalletService, q


class Command(BaseCommand):
    help = "Repair legacy GST data for products, order items, and seller ledger entries."

    def handle(self, *args, **options):
        calculator = PayoutCalculator()
        ledger_service = LedgerService(calculator=calculator)
        seller_cache = {}
        order_cache = {}
        touched_pairs = set()
        touched_sellers = set()
        products_updated = 0
        order_items_updated = 0
        ledger_entries_updated = 0
        skipped_order_items = 0
        skipped_summaries = 0

        for product in Product.objects.select_related("category").all():
            expected_rate = product.effective_gst_rate
            expected_hsn = product.effective_hsn_code
            update_fields = []
            if q(product.gst_rate or Decimal("0.00")) != expected_rate:
                product.gst_rate = expected_rate
                update_fields.append("gst_rate")
            if not product.hsn_code and expected_hsn:
                product.hsn_code = expected_hsn
                update_fields.append("hsn_code")
            if update_fields:
                product.save(update_fields=update_fields + ["updated"])
                products_updated += 1

        for order_item in (
            OrderItem.objects.select_related("order", "product__category", "product__seller_product__seller")
            .order_by("id")
        ):
            seller = ledger_service._resolve_seller(order_item)
            if not seller:
                continue

            seller_cache.setdefault(seller.id, seller)
            order_cache.setdefault(order_item.order_id, order_item.order)

            expected_rate = calculator._resolved_gst_rate_for_item(order_item)
            expected_unit_gst = order_item.product.gst_amount_for_price(order_item.price or Decimal("0.00"))
            order_item_fields = []
            if q(order_item.gst_rate or Decimal("0.00")) != expected_rate:
                order_item.gst_rate = expected_rate
                order_item_fields.append("gst_rate")
            if q(order_item.gst_amount or Decimal("0.00")) != expected_unit_gst:
                order_item.gst_amount = expected_unit_gst
                order_item_fields.append("gst_amount")
            if order_item_fields:
                order_item.save(update_fields=order_item_fields)
                order_items_updated += 1

            try:
                breakdown = calculator.calculate_for_order_item(order_item)
            except ValidationError:
                skipped_order_items += 1
                continue
            expected_amounts = {
                SellerLedger.COMPONENT_PRODUCT_PRICE: breakdown.product_price,
                SellerLedger.COMPONENT_COMMISSION: breakdown.platform_commission,
                SellerLedger.COMPONENT_GATEWAY_FEE: breakdown.payment_gateway_fee,
                SellerLedger.COMPONENT_SHIPPING: breakdown.shipping_charges,
                SellerLedger.COMPONENT_DISCOUNT: breakdown.seller_discount,
                SellerLedger.COMPONENT_GST: breakdown.gst,
                SellerLedger.COMPONENT_TDS: breakdown.tds,
            }
            placement_entries = SellerLedger.objects.filter(
                seller=seller,
                order=order_item.order,
                reference_id=f"order-item:{order_item.id}",
                metadata__event="placement",
            )

            placement_changed = False
            for entry in placement_entries:
                update_fields = []
                expected_amount = expected_amounts.get(entry.component)
                if expected_amount is not None and q(entry.amount) != expected_amount:
                    entry.amount = expected_amount
                    update_fields.append("amount")

                updated_metadata = dict(entry.metadata or {})
                updated_metadata["delivery_type"] = breakdown.delivery_type
                updated_metadata["breakdown"] = breakdown.as_dict()
                if updated_metadata != (entry.metadata or {}):
                    entry.metadata = updated_metadata
                    update_fields.append("metadata")

                if update_fields:
                    entry.save(update_fields=update_fields)
                    ledger_entries_updated += 1
                    placement_changed = True

            if order_item_fields or placement_changed:
                ledger_service._sync_legacy_payout(order_item, breakdown)
                touched_pairs.add((seller.id, order_item.order_id))
                touched_sellers.add(seller.id)

        for seller_id, order_id in touched_pairs:
            try:
                ledger_service._refresh_order_payout_summary(
                    seller=seller_cache[seller_id],
                    order=order_cache[order_id],
                    reference_id=f"repair-gst:{order_id}",
                )
            except ValidationError:
                skipped_summaries += 1

        for seller_id in touched_sellers:
            WalletService.recalculate_wallet(seller_cache[seller_id])

        self.stdout.write(
            self.style.SUCCESS(
                "Repaired GST data: "
                f"{products_updated} product(s), "
                f"{order_items_updated} order item(s), "
                f"{ledger_entries_updated} ledger entry(s), "
                f"{skipped_order_items} skipped order item(s), "
                f"{skipped_summaries} skipped summary refresh(es)."
            )
        )
