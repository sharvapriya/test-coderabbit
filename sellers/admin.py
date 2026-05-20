from django.contrib import admin, messages
from django.contrib.admin.helpers import ACTION_CHECKBOX_NAME
from django.core.cache import cache
from django.db import transaction
from django.db.models import Count, OuterRef, Q, Subquery
from django.template.response import TemplateResponse
from django.utils import timezone
from django.utils.html import format_html
from django.utils.translation import gettext_lazy as _
from django.db.models.signals import post_save
from django.dispatch import receiver

from orders.utils.email import handle_order_status_change
from products.admin_forms import ProductRejectionForm
from products.models import Product
from django.contrib.admin.helpers import ACTION_CHECKBOX_NAME

from .models import (
    Payout,
    PayoutConfiguration,
    CompletedSellerPayout,
    HubProductDelivery,
    SellerLedger,
    SellerNotification,
    SellerOrderPayout,
    SellerPayout,
    SellerProduct,
    SellerProfile,
    SellerWallet,
    TransactionLog,
)
from .services import LedgerService, PayoutService, WalletService


@admin.register(SellerProfile)
class SellerProfileAdmin(admin.ModelAdmin):
    list_display = (
        "business_name",
        "brand_name",
        "user",
        "registration_id",
        "approval_status",
        "has_signature",
        # "terms_accepted",
        "seller_id",
        "approved_at",
    )
    list_filter = ("approval_status", "approved_at", "terms_accepted")
    search_fields = (
        "business_name",
        "registration_id",
        "seller_id",
        "pan_card_number",
        "contact_email",
        "user__username",
        "user__email",
    )
    list_editable = ("approval_status",)
    list_select_related = ("user", "approved_by")
    list_per_page = 50
    show_full_result_count = False
    # readonly_fields = ("registration_id", "seller_id", "approved_at", "approved_by", "terms_accepted_at")
    readonly_fields = (
        "registration_id",
        "seller_id",
        "approved_at",
        "approved_by",
        "terms_accepted_at",
        "signature_preview",
    )
    actions = ("approve_profiles",)
    filter_horizontal = ("product_categories",)
    fieldsets = (
        (
            "Seller Registration",
            {
                "fields": (
                    "user",
                    "business_name",
                    "brand_name",
                    "phone",
                    "alternate_phone",
                    "contact_person_name",
                    "contact_email",
                    "website",
                    "seller_signature",
                    "signature_preview",
                    "approval_status",
                    "approved_by",
                    "approved_at",
                    "registration_id",
                    "seller_id",
                )
            },
        ),
        (
            "Business Documents",
            {
                "fields": (
                    "pan_card_number",
                    "business_pan_card_number",
                    "aadhar_number",
                    "gst_number",
                )
            },
        ),
        (
            "Business Details",
            {
                "fields": (
                    "supplier_details",
                    "registered_office_address",
                    "product_categories",
                    "payout_upi_id",
                    "payout_phonepay_gpay_number",
                    "payout_account_name",
                    "payout_account_number",
                    "payout_ifsc",
                    "terms_accepted",
                    "terms_accepted_at",
                )
            },
        ),
    )

    @admin.display(boolean=True, description="Signature")
    def has_signature(self, obj):
        return bool(obj.seller_signature)

    @admin.display(description="Signature preview")
    def signature_preview(self, obj):
        if not obj.seller_signature:
            return "No signature uploaded"
        cache_buster = ""
        if obj.updated_at:
            cache_buster = f"?v={int(obj.updated_at.timestamp())}"
        return format_html(
            '<img src="{}" style="max-height: 120px; max-width: 220px; border-radius: 8px; border: 1px solid #e5e7eb;" />',
            f"{obj.seller_signature.url}{cache_buster}",
        )

    @admin.action(description="Approve selected seller registrations")
    # def approve_profiles(self, request, queryset):
    #     approved_count = 0
    #     for profile in queryset.exclude(approval_status=SellerProfile.STATUS_APPROVED):
    #         profile.approval_status = SellerProfile.STATUS_APPROVED
    #         profile.approved_by = request.user
    #         profile.save(update_fields=["approval_status", "approved_by", "seller_id", "approved_at", "updated_at"])
    #         approved_count += 1
    #     self.message_user(request, f"Approved {approved_count} registration(s).")
    
    
    def approve_profiles(self, request, queryset):
        approved_count = 0
        for profile in queryset.exclude(approval_status=SellerProfile.STATUS_APPROVED):
            profile.approval_status = SellerProfile.STATUS_APPROVED
            profile.approved_by = request.user
            profile.save(update_fields=["approval_status", "approved_by", "seller_id", "approved_at", "updated_at"])
    
    
            approved_count += 1
    
        self.message_user(request, f"Approved {approved_count} registration(s).")
    
    
    
    
    
    # def save_model(self, request, obj, form, change):
    #     if "approval_status" in form.changed_data and obj.approval_status == SellerProfile.STATUS_APPROVED:
    #         obj.approved_by = request.user
    #     super().save_model(request, obj, form, change)
    def save_model(self, request, obj, form, change):
        if "approval_status" in form.changed_data and obj.approval_status == SellerProfile.STATUS_APPROVED:
            obj.approved_by = request.user

        super().save_model(request, obj, form, change)



@admin.register(SellerProduct)
class SellerProductAdmin(admin.ModelAdmin):
    list_display = (
        "product",
        "seller",
        "product_status",
        "rejection_reason",
        "base_price",
        "effective_price",
        "discount_status",
        "delivery_mode",
        "delivery_type",
        "estimated_delivery_charge",
        "updated_at",
    )
    list_filter = ("product__status", "delivery_mode", "delivery_type")
    search_fields = ("product__name", "seller__business_name")
    list_select_related = ("product", "seller")
    list_per_page = 50
    show_full_result_count = False
    actions = ("approve_products", "reject_products")

    @admin.display(description="Base Price", ordering="product__price")
    def base_price(self, obj):
        return obj.product.price

    @admin.display(description="Approval", ordering="product__status")
    def product_status(self, obj):
        return obj.product.get_status_display()

    @admin.display(description="Rejection reason")
    def rejection_reason(self, obj):
        return obj.product.rejection_reason or "-"

    @admin.display(description="Effective Price")
    def effective_price(self, obj):
        return obj.product.discounted_price

    @admin.display(description="Discount")
    def discount_status(self, obj):
        if not obj.product.has_discount:
            return "No"
        return f"{obj.product.discount_percent_value:g}% off"

    @admin.action(description="Approve selected seller products")
    def approve_products(self, request, queryset):
        approved_count = 0
        for seller_product in queryset.select_related("product"):
            product = seller_product.product
            if product.status == Product.STATUS_APPROVED:
                continue
            product.approve(save=True)
            approved_count += 1
        self.message_user(request, f"Approved {approved_count} product(s).")

    @admin.action(description="Reject selected seller products")
    def reject_products(self, request, queryset):
        form = None
        if "apply" in request.POST:
            form = ProductRejectionForm(request.POST)
            if form.is_valid():
                reason = form.cleaned_data["rejection_reason"].strip()
                rejected_count = 0
                for seller_product in queryset.select_related("product"):
                    product = seller_product.product
                    if product.status == Product.STATUS_REJECTED:
                        continue
                    product.reject(reason=reason, save=True)
                    rejected_count += 1
                self.message_user(request, f"Rejected {rejected_count} product(s).")
                return None
        if form is None:
            form = ProductRejectionForm(
                # initial={"_selected_action": request.POST.getlist(ACTION_CHECKBOX_NAME)}
                initial={"_selected_action": request.POST.getlist(ACTION_CHECKBOX_NAME)}
            )

        context = {
            **self.admin_site.each_context(request),
            "opts": self.model._meta,
            "title": _("Reject selected seller products"),
            "products": queryset,
            "form": form,
            "action_checkbox_name": ACTION_CHECKBOX_NAME,
        }
        return TemplateResponse(request, "admin/products/reject_selected_products.html", context)


@admin.register(SellerPayout)
class SellerPayoutAdmin(admin.ModelAdmin):
    list_display = (
        "payout_id",
        "seller",
        "order_item_id",
        "order_id",
        "product_name",
        "delivery_mode",
        "delivery_status",
        "courier_number",
        "gross_amount",
        "payout_percentage",
        "payout_amount",
        "status",
        "paid_at",
    )
    list_display_links = ("payout_id",) 
    list_editable = ("delivery_status",)
    list_filter = ("status", "delivery_mode")
    search_fields = (
        "seller__business_name",
        "order_item__order__full_name",
        "order_item__product__name",
    )
    list_per_page = 50
    show_full_result_count = False
    readonly_fields = (
        "delivery_status_updated_by",
        "delivery_status_updated_at",
        "product_image_preview",
        "seller_name",
        "customer_delivery_address",
    )
    actions = ("release_payouts",)

    fieldsets = (
        (
            "Payout Details",
            {
                "fields": (
                    "seller",
                    "order_item",
                    "delivery_mode",
                    "gross_amount",
                    "payout_percentage",
                    "payout_amount",
                    "status",
                )
            },
        ),
        (
            "Delivery",
            {
                "fields": (
                    "delivery_status",
                    "delivery_status_note",
                    "courier_number",
                    "courier_slip",
                    "delivery_status_updated_by",
                    "delivery_status_updated_at",
                )
            },
        ),
        (
            "Order Context",
            {
                "fields": (
                    "product_image_preview",
                    "seller_name",
                    "customer_delivery_address",
                )
            },
        ),
    )

    def get_queryset(self, request):
        qs = super().get_queryset(request)
        return (
            qs.filter(delivery_mode=SellerProduct.OWN_DELIVERY)
            .exclude(order_item__order__status="cancelled")
            .exclude(order_item__order__order_status="cancelled")
            .exclude(delivery_status=SellerPayout.DELIVERY_DELIVERED)
            .select_related("seller", "order_item__product", "order_item__order")
        )

    @admin.display(description="Payout ID", ordering="id")
    def payout_id(self, obj):
        return obj.id

    @admin.display(description="Order Item ID", ordering="order_item__id")
    def order_item_id(self, obj):
        return obj.order_item_id

    @admin.display(description="Order ID", ordering="order_item__order__display_order_id")
    def order_id(self, obj):
        return obj.order_item.order.display_order_id

    @admin.display(description="Product", ordering="order_item__product__name")
    def product_name(self, obj):
        return obj.order_item.product.name

    @admin.display(description="Product image")
    def product_image_preview(self, obj):
        image = getattr(obj.order_item.product, "image", None)
        if not image:
            return "No image"
        return format_html(
            '<img src="{}" style="max-height: 120px; max-width: 120px; '
            'border-radius: 10px; border: 1px solid #e5e7eb;" />',
            image.url,
        )

    @admin.display(description="Seller")
    def seller_name(self, obj):
        seller = getattr(obj, "seller", None)
        return seller.business_name if seller else "-"

    @admin.display(description="Customer delivery address")
    def customer_delivery_address(self, obj):
        order = getattr(obj.order_item, "order", None)
        if not order:
            return "-"
        return f"{order.full_name} | {order.email} | {order.address}"

    def save_model(self, request, obj, form, change):
        delivery_status_changed = change and "delivery_status" in form.changed_data
        if delivery_status_changed:
            obj.delivery_status_updated_by = request.user
            obj.delivery_status_updated_at = timezone.now()
            previous_order_status = obj.order_item.order.status
        super().save_model(request, obj, form, change)
        if delivery_status_changed:
            order = obj.order_item.order
            if order.status not in {"cancelled", "partially_cancelled"}:
                order.status = order.resolve_fulfillment_status()
                if order.status != previous_order_status:
                    order.save(update_fields=["status", "updated_at"])
                    transaction.on_commit(lambda: handle_order_status_change(order))

    @admin.action(description="Release payout for selected entries")
    def release_payouts(self, request, queryset):
        released = 0
        for seller in {payout.seller for payout in queryset.select_related("seller")}:
            try:
                PayoutService().release_available_balance(
                    seller=seller,
                    idempotency_key=f"admin-payout:{seller.id}:{timezone.now().timestamp()}",
                )
                released += 1
            except Exception as exc:
                self.message_user(request, f"{seller.business_name}: {exc}", level=messages.ERROR)
        self.message_user(request, f"Triggered payout for {released} seller(s).")


@admin.register(HubProductDelivery)
class HubProductDeliveryAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "seller",
        "order_item_id",
        "order_id",
        "product_name",
        "hub_name",
        "status",
        "payout_status",
        "updated_at",
    )
    list_editable = ("status",)
    list_filter = ("status", "hub_name", "updated_at")
    # list_filter = ("status", "updated_at")
    search_fields = (
        "seller__business_name",
        "order_item__order__display_order_id",
        "order_item__order__full_name",
        "order_item__product__name",
        "hub_name",
    )
    list_per_page = 50
    show_full_result_count = False
    readonly_fields = (
        "seller",
        "order_item",
        "seller_payout",
        "updated_by",
        "updated_at",
        "product_image_preview",
        "customer_delivery_address",
    )

    fieldsets = (
        (
            "Hub Delivery Context",
            {
                "fields": (
                    "seller",
                    "order_item",
                    "seller_payout",
                    "hub_name",
                    "hub_address",
                )
            },
        ),
        (
            "Delivery Update",
            {
                "fields": (
                    "status",
                    "status_note",
                    "updated_by",
                    "updated_at",
                )
            },
        ),
        (
            "Order Context",
            {
                "fields": (
                    "product_image_preview",
                    "customer_delivery_address",
                )
            },
        ),
    )

    def get_queryset(self, request):
        return super().get_queryset(request).exclude(
            order_item__order__status="cancelled"
        ).exclude(
            order_item__order__order_status="cancelled"
        ).select_related(
            "seller",
            "order_item__product",
            "order_item__order",
            "seller_payout",
        )

    @admin.display(description="Order Item ID", ordering="order_item__id")
    def order_item_id(self, obj):
        return obj.order_item_id

    @admin.display(description="Order ID", ordering="order_item__order__display_order_id")
    def order_id(self, obj):
        return obj.order_item.order.display_order_id

    @admin.display(description="Product", ordering="order_item__product__name")
    def product_name(self, obj):
        return obj.order_item.product.name

    @admin.display(description="Payout status", ordering="seller_payout__status")
    def payout_status(self, obj):
        return obj.seller_payout.get_status_display()

    @admin.display(description="Product image")
    def product_image_preview(self, obj):
        image = getattr(obj.order_item.product, "image", None)
        if not image:
            return "No image"
        return format_html(
            '<img src="{}" style="max-height: 120px; max-width: 120px; '
            'border-radius: 10px; border: 1px solid #e5e7eb;" />',
            image.url,
        )

    @admin.display(description="Customer delivery address")
    def customer_delivery_address(self, obj):
        order = getattr(obj.order_item, "order", None)
        if not order:
            return "-"
        return f"{order.full_name} | {order.email} | {order.address}"

    def save_model(self, request, obj, form, change):
        delivery_status_changed = change and any(
            field in form.changed_data for field in ("status", "status_note")
        )
        if delivery_status_changed:
            obj.updated_by = request.user
            obj.updated_at = timezone.now()
            previous_order_status = obj.order_item.order.status

        super().save_model(request, obj, form, change)

        if delivery_status_changed:
            payout = obj.seller_payout
            payout.delivery_status = obj.status
            payout.delivery_status_note = obj.status_note
            payout.delivery_status_updated_by = obj.updated_by
            payout.delivery_status_updated_at = obj.updated_at

            if obj.status == SellerPayout.DELIVERY_DELIVERED and payout.status != SellerPayout.STATUS_PAID:
                payout.status = SellerPayout.STATUS_PROCESSING
            elif payout.status != SellerPayout.STATUS_PAID:
                payout.status = SellerPayout.STATUS_PENDING

            payout.save(
                update_fields=[
                    "delivery_status",
                    "delivery_status_note",
                    "delivery_status_updated_by",
                    "delivery_status_updated_at",
                    "status",
                ]
            )
            order = obj.order_item.order
            if order.status not in {"cancelled", "partially_cancelled"}:
                order.status = order.resolve_fulfillment_status()
                if order.status != previous_order_status:
                    order.save(update_fields=["status", "updated_at"])
                    transaction.on_commit(lambda: handle_order_status_change(order))

            message = (
                f"Hub delivery status updated for order #{obj.order_item.order.display_order_id} "
                f"({obj.order_item.product.name}) to {payout.get_delivery_status_display()}."
            )
            SellerNotification.objects.update_or_create(
                recipient=obj.seller.user,
                order_item=obj.order_item,
                notification_type=SellerNotification.TYPE_DELIVERY_UPDATE,
                defaults={"message": message, "is_read": False},
            )


@admin.register(CompletedSellerPayout)
class CompletedSellerPayoutAdmin(admin.ModelAdmin):
    list_display = (
        "payout_id",
        "seller",
        "order_item_id",
        "order_id",
        "product_name",
        "delivery_mode",
        "courier_number",
        "payout_amount",
        "status",
        "delivery_status_updated_at",
    )
    search_fields = (
        "seller__business_name",
        "order_item__order__display_order_id",
        "order_item__order__full_name",
        "order_item__product__name",
        "courier_number",
    )
    list_filter = ("status",)
    list_per_page = 50
    show_full_result_count = False
    actions = ("release_payouts",)
    readonly_fields = ("product_image_preview", "seller_name", "customer_delivery_address")
    fieldsets = (
        (
            "Payout Details",
            {
                "fields": (
                    "seller",
                    "order_item",
                    "delivery_mode",
                    "gross_amount",
                    "payout_percentage",
                    "payout_amount",
                    "status",
                    "paid_at",
                )
            },
        ),
        (
            "Delivery",
            {
                "fields": (
                    "delivery_status",
                    "delivery_status_note",
                    "courier_number",
                    "courier_slip",
                    "delivery_status_updated_at",
                )
            },
        ),
        (
            "Order Context",
            {
                "fields": (
                    "product_image_preview",
                    "seller_name",
                    "customer_delivery_address",
                )
            },
        ),
    )

    def get_queryset(self, request):
        qs = super().get_queryset(request)
        return qs.filter(
            # delivery_mode=SellerProduct.OWN_DELIVERY,
            delivery_status=SellerPayout.DELIVERY_DELIVERED,
        ).exclude(
            order_item__order__status="cancelled",
        ).exclude(
            order_item__order__order_status="cancelled",
        ).select_related("seller", "order_item__product", "order_item__order")

    @admin.display(description="Payout ID", ordering="id")
    def payout_id(self, obj):
        return obj.id

    @admin.display(description="Order Item ID", ordering="order_item__id")
    def order_item_id(self, obj):
        return obj.order_item_id

    @admin.display(description="Order ID", ordering="order_item__order__display_order_id")
    def order_id(self, obj):
        return obj.order_item.order.display_order_id

    @admin.display(description="Product", ordering="order_item__product__name")
    def product_name(self, obj):
        return obj.order_item.product.name

    @admin.display(description="Product image")
    def product_image_preview(self, obj):
        image = getattr(obj.order_item.product, "image", None)
        if not image:
            return "No image"
        return format_html(
            '<img src="{}" style="max-height: 120px; max-width: 120px; '
            'border-radius: 10px; border: 1px solid #e5e7eb;" />',
            image.url,
        )

    @admin.display(description="Seller")
    def seller_name(self, obj):
        seller = getattr(obj, "seller", None)
        return seller.business_name if seller else "-"

    @admin.display(description="Customer delivery address")
    def customer_delivery_address(self, obj):
        order = getattr(obj.order_item, "order", None)
        if not order:
            return "-"
        return f"{order.full_name} | {order.email} | {order.address}"

    @admin.action(description="Release payout for selected completed orders")
    def release_payouts(self, request, queryset):
        released = 0
        for seller in {payout.seller for payout in queryset.select_related("seller")}:
            try:
                PayoutService().release_available_balance(
                    seller=seller,
                    idempotency_key=f"admin-payout:{seller.id}:{timezone.now().timestamp()}",
                )
                released += 1
            except Exception as exc:
                self.message_user(request, f"{seller.business_name}: {exc}", level=messages.ERROR)
        self.message_user(request, f"Triggered payout for {released} seller(s).")


@admin.register(PayoutConfiguration)
class PayoutConfigurationAdmin(admin.ModelAdmin):
    list_display = (
        "name",
        "is_active",
        "platform_commission_rate",
        "payment_gateway_fee_rate",
        "gst_rate",
        "tds_rate",
        "additional_hold_days",
        "default_return_window_days",
    )
    list_editable = (
        "is_active",
        "platform_commission_rate",
        "payment_gateway_fee_rate",
        "gst_rate",
        "tds_rate",
        "additional_hold_days",
        "default_return_window_days",
    )


@admin.register(SellerOrderPayout)
class SellerOrderPayoutAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "seller",
        "order",
        "status",
        "gross_amount",
        "net_amount",
        "delivered_at",
        "available_on",
        "paid_at",
    )
    list_filter = ("status",)
    search_fields = ("seller__business_name","order__display_order_id" , "last_reference_id")
    readonly_fields = ("breakdown", "delivered_at", "return_window_closed_at", "available_on", "paid_at")
    list_select_related = ("seller", "order")
    list_per_page = 50
    show_full_result_count = False


@admin.register(SellerLedger)
class SellerLedgerAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "seller",
        "order",
        "transaction_type",
        "component",
        "status",
        "amount",
        "reference_id",
        "created_at",
    )
    list_filter = ("transaction_type", "component", "status")
    search_fields = ("seller__business_name", "order__id", "reference_id", "idempotency_key", "notes")
    readonly_fields = ("idempotency_key", "metadata", "created_at")
    list_select_related = ("seller", "order")
    list_per_page = 50
    show_full_result_count = False

    def save_model(self, request, obj, form, change):
        if change:
            return super().save_model(request, obj, form, change)
        entry = LedgerService().create_manual_adjustment(
            seller=obj.seller,
            amount=obj.amount,
            transaction_type=obj.transaction_type,
            reason=obj.notes or "Manual admin adjustment",
            actor=request.user,
            reference_id=obj.reference_id or None,
            status=obj.status,
        )
        obj.pk = entry.pk


@admin.register(SellerWallet)
class SellerWalletAdmin(admin.ModelAdmin):
    list_display = (
        "seller",
        "pending_balance",
        "hold_balance",
        "available_balance",
        "paid_balance",
        "updated_at",
    )
    search_fields = ("seller__business_name", "seller__user__username")
    list_select_related = ("seller__user",)
    list_per_page = 50
    show_full_result_count = False
    actions = ("recalculate_wallets", "release_available_balance")

    @admin.action(description="Recalculate selected wallets from ledger")
    def recalculate_wallets(self, request, queryset):
        count = 0
        for wallet in queryset.select_related("seller"):
            WalletService.recalculate_wallet(wallet.seller)
            count += 1
        self.message_user(request, f"Recalculated {count} wallet(s).")

    @admin.action(description="Trigger payout for selected wallets")
    def release_available_balance(self, request, queryset):
        count = 0
        for wallet in queryset.select_related("seller"):
            PayoutService().release_available_balance(
                seller=wallet.seller,
                idempotency_key=f"admin-payout:{wallet.seller_id}:{timezone.now().timestamp()}",
            )
            count += 1
        self.message_user(request, f"Triggered {count} payout(s).")


@admin.register(Payout)
class PayoutAdmin(admin.ModelAdmin):
    list_display = ("id", "seller", "amount", "status", "reference", "processed_at", "created_at")
    list_filter = ("status",)
    search_fields = ("seller__business_name", "reference", "idempotency_key")
    readonly_fields = ("breakdown", "failure_reason", "processed_at")
    list_select_related = ("seller",)
    list_per_page = 50
    show_full_result_count = False


@admin.register(TransactionLog)
class TransactionLogAdmin(admin.ModelAdmin):
    list_display = ("id", "action", "seller", "order", "payout", "reference_id", "created_at")
    list_filter = ("action",)
    search_fields = ("seller__business_name", "order__id", "reference_id", "idempotency_key", "reason")
    readonly_fields = ("metadata",)
    list_select_related = ("seller", "order", "payout")
    list_per_page = 50
    show_full_result_count = False


# Custom payout management view
from django.contrib.admin.sites import AdminSite
from django.contrib.admin.views.decorators import staff_member_required
from django.utils.decorators import method_decorator
from django.views.decorators.cache import never_cache

@staff_member_required
@never_cache
def payout_management_view(request):
    cache_key = "admin_sellers_payout_management_v1"
    seller_data = cache.get(cache_key)
    if seller_data is None:
        latest_payout_reference = Payout.objects.filter(
            seller=OuterRef("pk")
        ).order_by("-created_at")
        sellers = (
            SellerProfile.objects.filter(
                approval_status=SellerProfile.STATUS_APPROVED
            )
            .select_related("user")
            .prefetch_related("wallet")
            .annotate(
                total_payouts=Count(
                    "seller_wallet_payouts",
                    filter=Q(seller_wallet_payouts__status=Payout.STATUS_COMPLETED),
                ),
                last_payout_reference=Subquery(latest_payout_reference.values("reference")[:1]),
                last_payout_processed_at=Subquery(latest_payout_reference.values("processed_at")[:1]),
                last_payout_amount=Subquery(latest_payout_reference.values("amount")[:1]),
            )
        )

        seller_data = []
        for seller in sellers:
            wallet = getattr(seller, "wallet", None)
            pending_balance = getattr(wallet, "pending_balance", Decimal("0.00"))
            hold_balance = getattr(wallet, "hold_balance", Decimal("0.00"))
            available_balance = getattr(wallet, "available_balance", Decimal("0.00"))
            paid_balance = getattr(wallet, "paid_balance", Decimal("0.00"))
            seller_data.append({
                "seller": seller,
                "pending_balance": pending_balance,
                "hold_balance": hold_balance,
                "available_balance": available_balance,
                "paid_balance": paid_balance,
                "total_earnings": pending_balance + hold_balance + available_balance + paid_balance,
                "last_payout": {
                    "reference": seller.last_payout_reference or "Pending reference",
                    "processed_at": seller.last_payout_processed_at,
                    "amount": seller.last_payout_amount,
                } if seller.last_payout_reference or seller.last_payout_processed_at or seller.last_payout_amount else None,
                "total_payouts": seller.total_payouts,
            })

        seller_data.sort(key=lambda x: x["available_balance"], reverse=True)
        cache.set(cache_key, seller_data, 120)
    
    context = {
        'seller_data': seller_data,
        'title': 'Seller Payout Management',
        'site_header': AdminSite().site_header,
        'site_title': AdminSite().site_title,
        'has_permission': True,
        'is_nav_sidebar_enabled': True,
    }
    
    from django.shortcuts import render
    return render(request, 'admin/sellers/payout_management.html', context)

# Also add a release payout view
@method_decorator(staff_member_required)
def release_payout_view(request, seller_id):
    try:
        seller = SellerProfile.objects.get(id=seller_id, approval_status=SellerProfile.STATUS_APPROVED)
        payout = PayoutService().release_available_balance(
            seller=seller,
            idempotency_key=f"admin-manual:{seller.id}:{timezone.now().timestamp()}",
        )
        messages.success(request, f"Payout released for {seller.business_name}. Amount: ₹{payout.amount}")
    except SellerProfile.DoesNotExist:
        messages.error(request, "Seller not found or not approved.")
    except Exception as e:
        messages.error(request, f"Failed to release payout: {str(e)}")
    
    from django.shortcuts import redirect
    return redirect('admin:sellers_payout_management')


