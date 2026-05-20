from django.contrib import admin
from django.contrib.admin.helpers import ACTION_CHECKBOX_NAME
from django.template.response import TemplateResponse
from django.utils.translation import gettext_lazy as _

from .models import Category, Product, StockAlertSubscription, ProductImage
from .admin_forms import ProductAdminForm, ProductRejectionForm


class ProductImageInline(admin.TabularInline):
    model = ProductImage
    extra = 6  # number of empty image fields shown

@admin.register(Category)
class CategoryAdmin(admin.ModelAdmin):
    list_display = ["name", "slug", "gst_rate", "hsn_code"]
    list_editable = ["gst_rate", "hsn_code"]
    prepopulated_fields = {'slug':('name',)}
    
    list_per_page = 50
    show_full_result_count = False
    
@admin.register(Product)
class ProductAdmin(admin.ModelAdmin):
    form = ProductAdminForm
    list_display = [
        "name",
        "brand",
        "seller_name",
        "status",
        "is_public",
        "base_price",
        "effective_price",
        "discount_status",
        "discount_percent",
        "discount_amount",
        "gst_rate",
        "hsn_code",
        "stock",
        "available",
        "created",
        "updated",
        "category",
    ]
    list_editable = ["gst_rate", "hsn_code", "available"]
    list_select_related = ["category", "seller_product__seller"]
    list_filter = ["status", "available", "category", "created", "updated"]
    search_fields = ["name", "slug", "brand", "seller_product__seller__business_name"]
    actions = ["approve_products", "reject_products"]
    readonly_fields = ["public_visibility"]
    list_per_page = 50
    show_full_result_count = False
    fields = [
        "category",
        "brand",
        "name",
        "slug",
        "description",
        "price",
        "discount_percent",
        "discount_amount",
        "gst_rate",
        "hsn_code",
        "stock",
        "available",
        "status",
        "rejection_reason",
        "public_visibility",
        "image",
    ]
    prepopulated_fields = {'slug':('name',)}
    
    # 🔥 THIS is what enables multiple images
    inlines = [ProductImageInline]

    @admin.display(description="Seller")
    def seller_name(self, obj):
        seller_product = getattr(obj, "seller_product", None)
        if not seller_product:
            return "-"
        return seller_product.seller.business_name

    @admin.display(boolean=True, description="Public")
    def is_public(self, obj):
        return obj.is_publicly_visible

    @admin.display(description="Public visibility")
    def public_visibility(self, obj):
        return "Visible to customers" if obj.is_publicly_visible else "Hidden from customers"

    @admin.display(description="Base Price", ordering="price")
    def base_price(self, obj):
        return obj.price

    @admin.display(description="Effective Price")
    def effective_price(self, obj):
        return obj.discounted_price

    @admin.display(description="Discount")
    def discount_status(self, obj):
        if not obj.has_discount:
            return "No"
        return f"{obj.discount_percent_value:g}% off"

    def save_model(self, request, obj, form, change):
        if obj.status == Product.STATUS_APPROVED:
            obj.available = True
            if not obj.rejection_reason:
                obj.rejection_reason = ""
        else:
            obj.available = False
        super().save_model(request, obj, form, change)

    @admin.action(description="Approve selected products")
    def approve_products(self, request, queryset):
        count = 0
        for product in queryset.exclude(status=Product.STATUS_APPROVED):
            product.approve(save=True)
            count += 1
        self.message_user(request, f"Approved {count} product(s).")

    @admin.action(description="Reject selected products")
    def reject_products(self, request, queryset):
        form = None
        if "apply" in request.POST:
            form = ProductRejectionForm(request.POST)
            if form.is_valid():
                reason = form.cleaned_data["rejection_reason"].strip()
                count = 0
                for product in queryset.exclude(status=Product.STATUS_REJECTED):
                    product.reject(reason=reason, save=True)
                    count += 1
                self.message_user(request, f"Rejected {count} product(s).")
                return None
        if form is None:
            form = ProductRejectionForm(
                initial={"_selected_action": request.POST.getlist(ACTION_CHECKBOX_NAME)}
            )

        context = {
            **self.admin_site.each_context(request),
            "opts": self.model._meta,
            "title": _("Reject selected products"),
            "products": queryset,
            "form": form,
            "action_checkbox_name": ACTION_CHECKBOX_NAME,
        }
        return TemplateResponse(request, "admin/products/reject_selected_products.html", context)
    

@admin.register(StockAlertSubscription)
class StockAlertSubscriptionAdmin(admin.ModelAdmin):
    list_display = ["user", "product", "is_notified", "created_at", "notified_at"]
    list_filter = ["is_notified", "created_at"]
    search_fields = ["user__username", "user__email", "product__name"]
    list_select_related = ("user", "product")
    list_per_page = 50
    show_full_result_count = False
