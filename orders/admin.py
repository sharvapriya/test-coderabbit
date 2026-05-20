from django.contrib import admin

from django.utils import timezone

from django.utils.html import format_html



from .models import (

    Coupon,

    DeliveryAssignment,

    Order,

    OrderItem,

    OrderStatusHistory,

    PaymentTransaction,

    ReturnRequest,

    ReturnRequestImage,

    Review,

    ReviewImage,

    ReviewReport,

    Wallet,

    WalletTransaction,

)

from .services import credit_wallet

from .utils.email import refund_processed_email

from django.db import transaction 





class OrderItemInline(admin.TabularInline):

    model = OrderItem

    raw_id_fields = ["product"]

    fields = ("id", "product", "price", "quantity", "status", "cancelled_at")

    readonly_fields = ("id", "status", "cancelled_at")

    extra = 0

@admin.register(OrderItem)

class OrderItemAdmin(admin.ModelAdmin):

    list_display = ("id", "product_image", "order", "product", "quantity", "price", "status", "cancelled_at")

    list_filter = ("status", "cancelled_at")

    search_fields = ("id", "order__public_id" , "product__name", "order__full_name")

    readonly_fields = ("cancelled_at",)

    list_select_related = ("order", "product")
    list_per_page = 50
    show_full_result_count = False

    @admin.display(description="Product Image")
    def product_image(self, obj):

        image = getattr(getattr(obj, "product", None), "image", None)

        if image:

            return format_html(

                '<img src="{}" style="max-height: 50px; max-width: 50px; border-radius: 4px;" />',

                image.url,

            )

        return "-"





class PaymentTransactionInline(admin.TabularInline):

    model = PaymentTransaction

    fields = (

        "id",

        "status",

        "gateway",

        "payment_method",

        "amount",

        "gateway_order_id",

        "gateway_payment_id",

        "failure_reason",

        "created_at",

    )

    readonly_fields = fields

    extra = 0

    can_delete = False





@admin.register(Order)

class OrderAdmin(admin.ModelAdmin):

    list_display = [

        "display_id",

        "user",

        "full_name",

        "email",

        "status",

        "payment_method",

        "paid",

        "coupon_code",

        "discount_amount",

        "wallet_amount_used",

        "gateway_amount_paid",

        "wallet_amount_refunded",

        # "delivery_charge",

        # "delivery_type",

        "order_status",

        "total_amount",

        "created_at",

    ]

    list_filter = ["status", "order_status", "delivery_type", "payment_method", "paid", "created_at"]

    search_fields = ["public_id","id","full_name", "email", "user__username", "user__email"]
    list_select_related = ("user",)
    list_per_page = 50
    show_full_result_count = False

    inlines = [OrderItemInline, PaymentTransactionInline]

    readonly_fields = ("created_at", "cancelled_at", "cancelled_by", "cancellation_reason")

     

    # ✅ ADD THIS FUNCTION

    def display_id(self, obj):

        return obj.display_order_id



    display_id.short_description = "Order ID"



@admin.register(OrderStatusHistory)

class OrderStatusHistoryAdmin(admin.ModelAdmin):

    list_display = ("id", "order", "order_item_id_display", "product_image", "from_status", "to_status", "changed_by", "created_at")

    list_filter = ("to_status", "created_at")

    search_fields = ("order__id", "order_item__id", "reason", "changed_by__username")

    readonly_fields = ("order", "order_item", "from_status", "to_status", "reason", "changed_by", "created_at", "metadata")

    list_select_related = ("order", "order_item__product", "changed_by")
    list_per_page = 50
    show_full_result_count = False

    def get_queryset(self, request):

        queryset = super().get_queryset(request)

        return queryset.filter(to_status=Order.STATUS_CANCELLED)

    def has_add_permission(self, request):

        return False

    @admin.display(description="Order Item")
    def order_item_id_display(self, obj):

        return obj.order_item_id or "-"

    @admin.display(description="Product Image")
    def product_image(self, obj):

        image = getattr(getattr(getattr(obj, "order_item", None), "product", None), "image", None)

        if image:

            return format_html(

                '<img src="{}" style="max-height: 50px; max-width: 50px; border-radius: 4px;" />',

                image.url,

            )

        return "-"





@admin.register(PaymentTransaction)

class PaymentTransactionAdmin(admin.ModelAdmin):

    list_display = (

        "id",

        "order",

        "user",

        "status",

        "gateway",

        "payment_method",

        "amount",

        "gateway_payment_id",

        "created_at",

    )

    list_filter = ("status", "gateway", "payment_method", "created_at")

    search_fields = ("id","order__public_id" , "gateway_order_id", "gateway_payment_id", "user__username")
    list_select_related = ("order", "user")
    list_per_page = 50
    show_full_result_count = False

    readonly_fields = ("created_at", "updated_at")





# @admin.register(DeliveryAssignment)

# class DeliveryAssignmentAdmin(admin.ModelAdmin):

#     list_display = (

#         "id",

#         "order",

#         "delivery_agent",

#         "status",

#         "cod_payment_status",

#         "cod_collected_amount",

#         "updated_at",

#     )

#     list_filter = ("status", "cod_payment_status", "updated_at")

#     search_fields = ("order__public_id", "delivery_agent__username", "order__full_name")

#     readonly_fields = ("created_at", "updated_at", "delivered_at", "cod_collected_at")





@admin.register(Coupon)

class CouponAdmin(admin.ModelAdmin):

    list_display = [

        "code",

        "discount_percent",

        "seller",

        "product",

        "coupon_status",

        "valid_from",

        "valid_to",

    ]

    search_fields = ["code", "seller__business_name", "product__name"]

    list_filter = ["active", "valid_from", "valid_to", "seller"]
    list_select_related = ("seller", "product")
    list_per_page = 50
    show_full_result_count = False



    @admin.display(description="Status")

    def coupon_status(self, obj):

        now = timezone.now()

        if not obj.active:

            return "Expired"

        if obj.valid_to and now > obj.valid_to:

            return "Expired"

        return "Active"





def _credit_return_to_wallet(return_request):

    refunded_amount, _, _ = credit_wallet(

        user=return_request.user,

        amount=return_request.refund_amount,

        source=WalletTransaction.SOURCE_REFUND,

        description=f"Refund from Order #{return_request.order_id}",

        order=return_request.order,

        return_request=return_request,

        metadata={"return_request_id": return_request.id},

    )

    if refunded_amount > 0:

        return_request.order.wallet_amount_refunded += refunded_amount

        return_request.order.save(update_fields=["wallet_amount_refunded", "updated_at"])

        refund_processed_email(return_request.user, return_request.order, return_request.refund_amount)

    return refunded_amount





def approve_return_request(modeladmin, request, queryset):

    """Admin action to approve return request"""

    queryset.filter(status=ReturnRequest.STATUS_PENDING).update(status=ReturnRequest.STATUS_APPROVED)



def process_refund_request(modeladmin, request, queryset):

    """Mark selected return requests as refund completed and credit wallet."""

    with transaction.atomic():   # ✅ ADD THIS BLOCK (only change needed)



        for return_request in queryset.select_related("order", "user"):

            if return_request.status == ReturnRequest.STATUS_REFUND_COMPLETED:

                continue



            return_request.status = ReturnRequest.STATUS_REFUND_COMPLETED

            return_request.save(update_fields=["status", "updated_at"])



            _credit_return_to_wallet(return_request)



    for return_request in queryset.select_related("order", "user"):

        if return_request.status == ReturnRequest.STATUS_REFUND_COMPLETED:

            continue

        return_request.status = ReturnRequest.STATUS_REFUND_COMPLETED

        return_request.save(update_fields=["status", "updated_at"])

        _credit_return_to_wallet(return_request)



def reject_return_request(modeladmin, request, queryset):

    """Admin action to reject return request"""

    queryset.filter(status=ReturnRequest.STATUS_PENDING).update(status=ReturnRequest.STATUS_REJECTED)


def optimized_process_refund_request(modeladmin, request, queryset):

    """Mark selected return requests as refund completed and credit wallet."""

    pending_requests = list(
        queryset.select_related("order", "user").exclude(
            status=ReturnRequest.STATUS_REFUND_COMPLETED
        )
    )

    with transaction.atomic():
        for return_request in pending_requests:
            return_request.status = ReturnRequest.STATUS_REFUND_COMPLETED
            return_request.save(update_fields=["status", "updated_at"])
            _credit_return_to_wallet(return_request)


process_refund_request = optimized_process_refund_request







approve_return_request.short_description = "Approve selected return requests"

reject_return_request.short_description = "Reject selected return requests"

process_refund_request.short_description = "Process Refund for selected requests"








class ReturnRequestImageInline(admin.TabularInline):
    model = ReturnRequestImage
    extra = 0
    readonly_fields = ("uploaded_at", "image_preview")
    fields = ("image", "image_preview", "uploaded_at")

    @admin.display(description="Preview")
    def image_preview(self, obj):
        if obj.image:
            return format_html(
                '<img src="{}" style="max-height: 100px; max-width: 100px; border-radius: 5px;" />',
                obj.image.url
            )
        return "No image"


@admin.register(ReturnRequest)
class ReturnRequestAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "order",
        "user",

        "product",

        "reason",

       

       "status",
        "refund_amount",
        "created_at",
    )
    list_filter = ("status", "reason", "created_at")
    search_fields = ("id", "order__public_id", "user__username", "user__email", "product__name")
    list_select_related = ("order", "user", "product")
    list_per_page = 50
    show_full_result_count = False
    readonly_fields = ("created_at", "updated_at", "id")
    inlines = [ReturnRequestImageInline]
    fieldsets = (
        ("Order Information", {"fields": ("id", "order", "user", "product")}),
        ("Return Details", {"fields": ("reason", "description", "photo", "refund_amount")}),
        ("Status & Notes", {"fields": ("status", "admin_notes")}),
        ("Timestamps", {"fields": ("created_at", "updated_at"), "classes": ("collapse",)}),
    )

    actions = [approve_return_request, reject_return_request, process_refund_request]



    def save_model(self, request, obj, form, change):

        previous_status = None

        if change and obj.pk:

            previous_status = ReturnRequest.objects.filter(pk=obj.pk).values_list("status", flat=True).first()



        super().save_model(request, obj, form, change)



        if obj.status == ReturnRequest.STATUS_REFUND_COMPLETED and previous_status != ReturnRequest.STATUS_REFUND_COMPLETED:

            _credit_return_to_wallet(obj)





@admin.register(Wallet)

class WalletAdmin(admin.ModelAdmin):

    list_display = ("user", "balance", "created_at", "updated_at")

    search_fields = ("user__username", "user__email")
    list_select_related = ("user",)
    list_per_page = 50
    show_full_result_count = False

    readonly_fields = ("created_at", "updated_at")

    fields = ("user", "balance", "created_at", "updated_at")





@admin.register(WalletTransaction)

class WalletTransactionAdmin(admin.ModelAdmin):

    list_display = ("id", "wallet", "transaction_type", "source", "amount", "balance_after", "order", "created_at")

    list_filter = ("transaction_type", "source", "created_at")

    search_fields = ("wallet__user__username", "order__id", "description")
    list_select_related = ("wallet__user", "order")
    list_per_page = 50
    show_full_result_count = False

    readonly_fields = ("created_at",)





class ReviewImageInline(admin.TabularInline):

    model = ReviewImage

    extra = 0

    readonly_fields = ("uploaded_at", "image_preview")

    fields = ("image", "image_preview", "uploaded_at")



    @admin.display(description="Preview")

    def image_preview(self, obj):

        if obj.image:

            return format_html(

                '<img src="{}" style="max-height: 100px; max-width: 100px; border-radius: 5px;" />',

                obj.image.url

            )

        return "No image"





class ReviewReportInline(admin.TabularInline):

    model = ReviewReport

    extra = 0

    readonly_fields = ("reported_by", "reason", "status", "created_at")

    fields = ("reported_by", "reason", "status", "created_at")

    can_delete = False





@admin.register(Review)

class ReviewAdmin(admin.ModelAdmin):

    list_display = (

        "id",

        "user",

        "product",

        "rating",

        "is_verified_purchase",

        "is_reported",

        "report_count",

        "is_flagged",

        "created_at",

    )

    list_filter = ("rating", "is_verified_purchase", "is_reported", "is_flagged", "created_at")

    search_fields = ("user__username", "product__name", "comment")
    list_select_related = ("user", "product")
    list_per_page = 50
    show_full_result_count = False

    readonly_fields = ("created_at", "updated_at")

    inlines = [ReviewImageInline, ReviewReportInline]

    fieldsets = (

        ("Review Details", {

            "fields": ("user", "product", "rating", "comment")

        }),

        ("Moderation", {

            "fields": ("is_verified_purchase", "is_reported", "report_count", "is_flagged")

        }),

        ("Metadata", {

            "fields": ("created_at", "updated_at"),

            "classes": ("collapse",)

        }),

    )





@admin.register(ReviewReport)

class ReviewReportAdmin(admin.ModelAdmin):

    list_display = ("id", "review", "reported_by", "status", "created_at")

    list_filter = ("status", "created_at")

    search_fields = ("review__product__name", "reported_by__username", "reason")
    list_select_related = ("review__product", "reported_by")
    list_per_page = 50
    show_full_result_count = False

    readonly_fields = ("created_at",)
