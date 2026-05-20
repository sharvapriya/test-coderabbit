from decimal import Decimal
import random
from django.conf import settings
from django.contrib.auth.models import Group
from django.core.exceptions import ValidationError
from django.db import models
from django.utils import timezone
from orders.models import OrderItem
from products.models import Category, Product
from django.contrib.auth import get_user_model
from django.core.exceptions import ObjectDoesNotExist


class SellerProfile(models.Model):
    REGISTRATION_ID_PREFIX = "MYKART"
    STATUS_PENDING = "pending"
    STATUS_APPROVED = "approved"
    STATUS_REJECTED = "rejected"
    STATUS_CHOICES = (
        (STATUS_PENDING, "Pending approval"),
        (STATUS_APPROVED, "Approved"),
        (STATUS_REJECTED, "Rejected"),
    )

    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="seller_profile",
    )
    registration_id = models.CharField(max_length=18, unique=True, null=True, blank=True)
    # seller_id = models.CharField(max_length=6, unique=True, null=True, blank=True)
    seller_id = models.CharField(max_length=30, unique=True, null=True, blank=True)
    approval_status = models.CharField(
        max_length=20,
        choices=STATUS_CHOICES,
        default=STATUS_PENDING,
    )
    approved_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="approved_seller_profiles",
    )
    approved_at = models.DateTimeField(null=True, blank=True)
    business_name = models.CharField(max_length=250)
    brand_name = models.CharField(max_length=120, blank=True)
    phone = models.CharField(max_length=30, blank=True)
    website = models.URLField(blank=True, null=True)
    pan_card_number = models.CharField(max_length=10)
    pan_card_photo = models.ImageField(upload_to="seller_documents/pan_cards/")
    business_pan_card_number = models.CharField(max_length=10, blank=True)
    business_pan_card_photo = models.ImageField(upload_to="seller_documents/business_pan_cards/", blank=True, null=True)
    seller_signature = models.ImageField(
        upload_to="seller_documents/signatures/",
        blank=True,
        null=True,
    )

    # aadhar_number = models.CharField(max_length=12, blank=True)
    aadhar_number = models.CharField(max_length=20, null=True, blank=True)
    gst_number = models.CharField(max_length=15, blank=True)
    payout_upi_id = models.CharField(max_length=50, blank=True)
    payout_phonepay_gpay_number = models.CharField(max_length=15, blank=True)
    supplier_details = models.TextField()
    msme_details = models.TextField(blank=True)
    registered_office_address = models.TextField()
    contact_person_name = models.CharField(max_length=150)
    contact_email = models.EmailField()
    alternate_phone = models.CharField(max_length=30, blank=True)
    product_categories = models.ManyToManyField(Category, related_name="seller_profiles", blank=True)
    terms_accepted = models.BooleanField(default=False)
    terms_accepted_at = models.DateTimeField(null=True, blank=True)
    payout_account_name = models.CharField(max_length=150)
    payout_account_number = models.CharField(max_length=50)
    payout_ifsc = models.CharField(max_length=20)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        indexes = [
            models.Index(fields=("approval_status", "approved_at")),
            models.Index(fields=("user", "approval_status")),
            models.Index(fields=("business_name",)),
            models.Index(fields=("contact_email",)),
        ]

    def __str__(self):
        return self.business_name

    @property
    def is_approved(self):
        return self.approval_status == self.STATUS_APPROVED

    @property
    def invoice_signature_url(self):
        signature = getattr(self, "seller_signature", None)
        if signature:
            return signature.url
        return ""

    @classmethod
    # def _generate_unique_6_digit_code(cls, field_name):
    def _generate_seller_id(cls):
        year = timezone.now().year
        for _ in range(100):
            code = f"{random.randint(0, 999999):06d}"
            #     if not cls.objects.filter(**{field_name: code}).exists():
            #         return code
            # raise ValidationError("Unable to generate a unique 6-digit ID. Try again.")
            seller_id = f"{cls.REGISTRATION_ID_PREFIX}/{year}/{code}"
            if not cls.objects.filter(seller_id=seller_id).exists():
                return seller_id
        raise ValidationError("Unable to generate a unique seller ID. Try again.")

    @classmethod
    def _registration_sequence_exists(cls, code):
        return cls.objects.filter(
            models.Q(registration_id=code)
            | models.Q(registration_id__endswith=f"/{code}")
        ).exists()

    @classmethod
    def _generate_registration_id(cls):
        year = timezone.now().year
        for _ in range(100):
            code = f"{random.randint(0, 999999):06d}"
            if not cls._registration_sequence_exists(code):
                return f"{cls.REGISTRATION_ID_PREFIX}/{year}/{code}"
        raise ValidationError("Unable to generate a unique registration ID. Try again.")

    def save(self, *args, **kwargs):
        if not self.registration_id:
            self.registration_id = self._generate_registration_id()
        if self.terms_accepted and self.terms_accepted_at is None:
            self.terms_accepted_at = timezone.now()

        if self.approval_status == self.STATUS_APPROVED:
            if not self.seller_id:
                # self.seller_id = self._generate_unique_6_digit_code("seller_id")
                self.seller_id = self._generate_seller_id()
            if self.approved_at is None:
                self.approved_at = timezone.now()

        super().save(*args, **kwargs)
        self.sync_user_role_groups()

    def sync_user_role_groups(self):
        if not self.user_id:
            return

        seller_group, _ = Group.objects.get_or_create(name="Seller")
        buyer_group, _ = Group.objects.get_or_create(name="Buyer")
        self.user.groups.remove(seller_group, buyer_group)
        if self.is_approved:
            self.user.groups.add(seller_group)
        else:
            self.user.groups.add(buyer_group)


# Computed property to show the current effective user role based on seller approval
User = get_user_model()

def _computed_user_profile(self):
    try:
        profile = self.seller_profile
    except ObjectDoesNotExist:
        return "Buyer"

    return "Seller" if profile.approval_status == SellerProfile.STATUS_APPROVED else "Buyer"

User.add_to_class("user_profile", property(_computed_user_profile))


class SellerProduct(models.Model):
    DELIVERY_TYPE_PLATFORM = "platform"
    DELIVERY_TYPE_OWN = "own_delivery"
    DELIVERY_TYPE_CHOICES = (
        (DELIVERY_TYPE_PLATFORM, "Platform delivery"),
        (DELIVERY_TYPE_OWN, "Own delivery"),
    )

    OWN_DELIVERY = "own_delivery"
    HUB_DELIVERY = "hub_delivery"
    DELIVERY_MODE_CHOICES = (
        (OWN_DELIVERY, "Own delivery"),
        (HUB_DELIVERY, "Hub handover"),
    )

    seller = models.ForeignKey(
        SellerProfile,
        related_name="seller_products",
        on_delete=models.CASCADE,
    )
    product = models.OneToOneField(
        Product,
        related_name="seller_product",
        on_delete=models.CASCADE,
    )

    
    delivery_mode = models.CharField(
        max_length=20,
        choices=DELIVERY_MODE_CHOICES,
        default=OWN_DELIVERY,
    )
    delivery_type = models.CharField(
        max_length=20,
        choices=DELIVERY_TYPE_CHOICES,
        default=DELIVERY_TYPE_OWN,
    )
    estimated_delivery_charge = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    shipping_details = models.TextField(
        blank=True,
        help_text="Required when delivery mode is own delivery.",
    )
    hub_name = models.CharField(max_length=120, blank=True)
    hub_address = models.TextField(blank=True)
    handover_instructions = models.TextField(blank=True)
    payout_rate_own_delivery = models.DecimalField(
        max_digits=5,
        decimal_places=2,
        default=Decimal("90.00"),
        help_text="Percentage paid to seller for own delivery.",
    )
    payout_rate_hub_delivery = models.DecimalField(
        max_digits=5,
        decimal_places=2,
        default=Decimal("82.00"),
        help_text="Percentage paid to seller for hub handover.",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ("-created_at",)
        indexes = [
            models.Index(fields=("seller", "delivery_mode")),
            models.Index(fields=("seller", "delivery_type")),
            models.Index(fields=("updated_at",)),
        ]

    def __str__(self):
        return f"{self.seller.business_name} - {self.product.name}"

    def clean(self):
        if (self.estimated_delivery_charge or Decimal("0")) < 0:
            raise ValidationError({"estimated_delivery_charge": "Estimated delivery charge cannot be negative."})
        if self.delivery_mode == self.OWN_DELIVERY and not self.shipping_details:
            raise ValidationError(
                {"shipping_details": "Shipping details are required for own delivery."}
            )
        if self.delivery_mode == self.HUB_DELIVERY:
            if not self.hub_name:
                raise ValidationError({"hub_name": "Hub name is required for hub delivery."})
            if not self.hub_address:
                raise ValidationError(
                    {"hub_address": "Hub address is required for hub delivery."}
                )
        if self.delivery_type == self.DELIVERY_TYPE_OWN and (self.estimated_delivery_charge or Decimal("0")) > 0:
            raise ValidationError(
                {"estimated_delivery_charge": "Own delivery products should not carry a platform delivery charge."}
            )

    def get_payout_rate(self):
        if self.delivery_mode == self.OWN_DELIVERY:
            return self.payout_rate_own_delivery
        return self.payout_rate_hub_delivery

    def calculate_payout_amount(self, gross_amount):
        gross_amount = gross_amount or Decimal("0")
        if self.delivery_type == self.DELIVERY_TYPE_OWN:
            return gross_amount
        payout_amount = gross_amount - (self.estimated_delivery_charge or Decimal("0"))
        return payout_amount if payout_amount > Decimal("0") else Decimal("0")

    def save(self, *args, **kwargs):
        if self.delivery_mode == self.OWN_DELIVERY:
            self.delivery_type = self.DELIVERY_TYPE_OWN
            self.estimated_delivery_charge = Decimal("0")
        elif not self.delivery_type:
            self.delivery_type = self.DELIVERY_TYPE_PLATFORM
        super().save(*args, **kwargs)


class SellerPayout(models.Model):
    PAYOUT_STATUS_PENDING = "pending"
    PAYOUT_STATUS_PAID = "paid"
    PAYOUT_STATUS_CHOICES = (
        (PAYOUT_STATUS_PENDING, "Pending"),
        (PAYOUT_STATUS_PAID, "Paid"),
    )

    STATUS_PENDING = "pending"
    STATUS_PROCESSING = "processing"
    STATUS_PAID = "paid"
    STATUS_FAILED = "failed"
    STATUS_CHOICES = (
        (STATUS_PENDING, "Pending"),
        (STATUS_PROCESSING, "Processing"),
        (STATUS_PAID, "Paid"),
        (STATUS_FAILED, "Failed"),
    )
    DELIVERY_PENDING = "pending"
    DELIVERY_PACKED = "packed"
    DELIVERY_SHIPPED = "shipped"
    DELIVERY_OUT_FOR_DELIVERY = "out_for_delivery"
    DELIVERY_DELIVERED = "delivered"
    DELIVERY_HANDED_TO_HUB = "handed_to_hub"
    DELIVERY_AT_HUB = "at_hub"
    DELIVERY_STATUS_CHOICES = (
        (DELIVERY_PENDING, "Pending"),
        (DELIVERY_PACKED, "Packed"),
        (DELIVERY_SHIPPED, "Shipped"),
        (DELIVERY_OUT_FOR_DELIVERY, "Out for delivery"),
        (DELIVERY_DELIVERED, "Delivered"),
        (DELIVERY_HANDED_TO_HUB, "Handed over to hub"),
        (DELIVERY_AT_HUB, "Received at hub"),
    )

    seller = models.ForeignKey(
        SellerProfile,
        related_name="payouts",
        on_delete=models.CASCADE,
    )
    order_item = models.OneToOneField(
        OrderItem,
        related_name="seller_payout",
        on_delete=models.CASCADE,
    )
    delivery_mode = models.CharField(max_length=20, choices=SellerProduct.DELIVERY_MODE_CHOICES)
    delivery_type = models.CharField(
        max_length=20,
        choices=SellerProduct.DELIVERY_TYPE_CHOICES,
        default=SellerProduct.DELIVERY_TYPE_PLATFORM,
    )
    delivery_charge = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    gross_amount = models.DecimalField(max_digits=12, decimal_places=2)
    payout_percentage = models.DecimalField(max_digits=5, decimal_places=2)
    payout_amount = models.DecimalField(max_digits=12, decimal_places=2)
    status = models.CharField(
        max_length=15,
        choices=STATUS_CHOICES,
        default=STATUS_PENDING,
    )
    delivery_status = models.CharField(
        max_length=30,
        choices=DELIVERY_STATUS_CHOICES,
        default=DELIVERY_PENDING,
    )
    delivery_status_note = models.CharField(max_length=255, blank=True)
    courier_number = models.CharField(max_length=120, blank=True)
    courier_slip = models.ImageField(
        upload_to="courier_slips/",
        blank=True,
        null=True,
    )
    delivery_status_updated_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="updated_seller_delivery_status",
    )
    delivery_status_updated_at = models.DateTimeField(null=True, blank=True)
    payout_status = models.CharField(
        max_length=20,
        choices=PAYOUT_STATUS_CHOICES,
        default=PAYOUT_STATUS_PENDING,
    )
    razorpay_payout_id = models.CharField(max_length=120, blank=True)
    paid_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ("-created_at",)

    def __str__(self):
        return f"Payout #{self.pk} - {self.seller.business_name}"

    def mark_paid(self, razorpay_payout_id=""):
        self.status = self.STATUS_PAID
        self.payout_status = self.PAYOUT_STATUS_PAID
        if razorpay_payout_id:
            self.razorpay_payout_id = razorpay_payout_id
        self.paid_at = timezone.now()
        self.save(update_fields=["status", "payout_status", "razorpay_payout_id", "paid_at"])

    @classmethod
    def own_delivery_status_choices(cls):
        return (
            (cls.DELIVERY_PENDING, "Pending"),
            (cls.DELIVERY_PACKED, "Packed"),
            (cls.DELIVERY_SHIPPED, "Shipped"),
            (cls.DELIVERY_OUT_FOR_DELIVERY, "Out for delivery"),
            (cls.DELIVERY_DELIVERED, "Delivered"),
        )


class ProductImage(models.Model):
    product = models.ForeignKey(
        Product,
        related_name="seller_images",
        on_delete=models.CASCADE
    )
    image = models.ImageField(upload_to='product_images/')
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.product.name} image"  



class CompletedSellerPayout(SellerPayout):
    class Meta:
        proxy = True
        verbose_name = "Completed order"
        verbose_name_plural = "Completed orders"


class HubProductDelivery(models.Model):
    STATUS_PENDING = SellerPayout.DELIVERY_PENDING
    STATUS_HANDED_TO_HUB = SellerPayout.DELIVERY_HANDED_TO_HUB
    STATUS_AT_HUB = SellerPayout.DELIVERY_AT_HUB
    STATUS_OUT_FOR_DELIVERY = SellerPayout.DELIVERY_OUT_FOR_DELIVERY
    STATUS_DELIVERED = SellerPayout.DELIVERY_DELIVERED
    STATUS_CHOICES = (
        (STATUS_PENDING, "Pending"),
        (STATUS_HANDED_TO_HUB, "Handed over to hub"),
        (STATUS_AT_HUB, "Received at hub"),
        (STATUS_OUT_FOR_DELIVERY, "Out for delivery"),
        (STATUS_DELIVERED, "Delivered"),
    )

    seller = models.ForeignKey(
        SellerProfile,
        related_name="hub_deliveries",
        on_delete=models.CASCADE,
    )
    order_item = models.OneToOneField(
        OrderItem,
        related_name="hub_delivery",
        on_delete=models.CASCADE,
    )
    seller_payout = models.OneToOneField(
        SellerPayout,
        related_name="hub_delivery_record",
        on_delete=models.CASCADE,
    )
    hub_name = models.CharField(max_length=120, blank=True)
    hub_address = models.TextField(blank=True)
    status = models.CharField(
        max_length=30,
        choices=STATUS_CHOICES,
        default=STATUS_PENDING,
    )
    status_note = models.CharField(max_length=255, blank=True)
    updated_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="updated_hub_delivery_status",
    )
    updated_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ("-created_at",)
        verbose_name = "Hub product delivery"
        verbose_name_plural = "Hub product deliveries"

    def __str__(self):
        return f"Hub delivery #{self.pk} - Order #{self.order_item.order.display_order_id}"

    def clean(self):
        if self.seller_payout.delivery_mode != SellerProduct.HUB_DELIVERY:
            raise ValidationError("Hub delivery records are only for hub delivery payouts.")
            
   

class SellerNotification(models.Model):
    TYPE_SELLER_ORDER = "seller_order"
    TYPE_ADMIN_ORDER = "admin_order"
    TYPE_DELIVERY_UPDATE = "delivery_update"
    TYPE_BALANCE_AVAILABLE = "balance_available"
    TYPE_PAYOUT_COMPLETED = "payout_completed"
    TYPE_DEDUCTION_APPLIED = "deduction_applied"
    TYPE_CHOICES = (
        (TYPE_SELLER_ORDER, "Seller order alert"),
        (TYPE_ADMIN_ORDER, "Admin order alert"),
        (TYPE_DELIVERY_UPDATE, "Delivery status update"),
        (TYPE_BALANCE_AVAILABLE, "Balance available"),
        (TYPE_PAYOUT_COMPLETED, "Payout completed"),
        (TYPE_DEDUCTION_APPLIED, "Deduction applied"),
    )

    recipient = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        related_name="seller_notifications",
        on_delete=models.CASCADE,
    )
    order_item = models.ForeignKey(
        OrderItem,
        related_name="seller_notifications",
        on_delete=models.CASCADE,
    )
    notification_type = models.CharField(max_length=30, choices=TYPE_CHOICES)
    message = models.CharField(max_length=255)
    is_read = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ("-created_at",)
        constraints = [
            models.UniqueConstraint(
                fields=["recipient", "order_item", "notification_type"],
                name="uniq_seller_notification_per_recipient_order_item_type",
            )
        ]

    def __str__(self):
        return f"{self.recipient} - {self.notification_type}"


class PayoutConfiguration(models.Model):
    name = models.CharField(max_length=100, default="Default payout config")
    is_active = models.BooleanField(default=True)
    platform_commission_rate = models.DecimalField(max_digits=5, decimal_places=2, default=Decimal("10.00"))
    payment_gateway_fee_rate = models.DecimalField(max_digits=5, decimal_places=2, default=Decimal("2.00"))
    gst_rate = models.DecimalField(max_digits=5, decimal_places=2, default=Decimal("18.00"))
    tds_rate = models.DecimalField(max_digits=5, decimal_places=2, default=Decimal("1.00"))
    additional_hold_days = models.PositiveIntegerField(default=7)
    default_return_window_days = models.PositiveIntegerField(default=7)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Payout configuration"
        verbose_name_plural = "Payout configurations"

    def __str__(self):
        return self.name

    @classmethod
    def get_solo(cls):
        config = cls.objects.filter(is_active=True).order_by("-updated_at", "-id").first()
        if config:
            return config
        return cls.objects.create()


class SellerOrderPayout(models.Model):
    STATUS_PENDING = "pending"
    STATUS_HOLD = "hold"
    STATUS_AVAILABLE = "available"
    STATUS_PAID = "paid"
    STATUS_REVERSED = "reversed"
    STATUS_CANCELLED = "cancelled"
    STATUS_CHOICES = (
        (STATUS_PENDING, "Pending"),
        (STATUS_HOLD, "Hold"),
        (STATUS_AVAILABLE, "Available"),
        (STATUS_PAID, "Paid"),
        (STATUS_REVERSED, "Reversed"),
        (STATUS_CANCELLED, "Cancelled"),
    )

    seller = models.ForeignKey(
        SellerProfile,
        related_name="order_payouts",
        on_delete=models.CASCADE,
    )
    order = models.ForeignKey(
        "orders.Order",
        related_name="seller_order_payouts",
        on_delete=models.CASCADE,
    )
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default=STATUS_PENDING)
    gross_amount = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    net_amount = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    breakdown = models.JSONField(default=dict, blank=True)
    currency = models.CharField(max_length=10, default="INR")
    delivered_at = models.DateTimeField(null=True, blank=True)
    return_window_days = models.PositiveIntegerField(default=7)
    hold_days = models.PositiveIntegerField(default=7)
    return_window_closed_at = models.DateTimeField(null=True, blank=True)
    available_on = models.DateTimeField(null=True, blank=True)
    paid_at = models.DateTimeField(null=True, blank=True)
    last_reference_id = models.CharField(max_length=100, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ("-updated_at", "-id")
        constraints = [
            models.UniqueConstraint(
                fields=("seller", "order"),
                name="uniq_seller_order_payout",
            )
        ]
        indexes = [
            models.Index(fields=("seller", "status")),
            models.Index(fields=("seller", "updated_at")),
            models.Index(fields=("status", "available_on")),
            models.Index(fields=("seller", "status", "created_at")),
        ]

    def __str__(self):
        return f"Payout state #{self.id} seller={self.seller_id} order={self.order.display_order_id}"


class Payout(models.Model):
    STATUS_INITIATED = "initiated"
    STATUS_PROCESSING = "processing"
    STATUS_COMPLETED = "completed"
    STATUS_FAILED = "failed"
    STATUS_CHOICES = (
        (STATUS_INITIATED, "Initiated"),
        (STATUS_PROCESSING, "Processing"),
        (STATUS_COMPLETED, "Completed"),
        (STATUS_FAILED, "Failed"),
    )

    seller = models.ForeignKey(
        SellerProfile,
        related_name="seller_wallet_payouts",
        on_delete=models.CASCADE,
    )
    amount = models.DecimalField(max_digits=12, decimal_places=2)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default=STATUS_INITIATED)
    reference = models.CharField(max_length=120, blank=True)
    idempotency_key = models.CharField(max_length=120, unique=True)
    breakdown = models.JSONField(default=dict, blank=True)
    failure_reason = models.CharField(max_length=255, blank=True)
    processed_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ("-created_at", "-id")
        indexes = [
            models.Index(fields=("seller", "status")),
            models.Index(fields=("seller", "created_at")),
            models.Index(fields=("status", "created_at")),
            models.Index(fields=("idempotency_key",)),
        ]

    def __str__(self):
        return f"Payout #{self.id} - seller={self.seller_id} - {self.amount}"


class SellerLedger(models.Model):
    TYPE_CREDIT = "credit"
    TYPE_DEBIT = "debit"
    TYPE_CHOICES = (
        (TYPE_CREDIT, "Credit"),
        (TYPE_DEBIT, "Debit"),
    )

    COMPONENT_PRODUCT_PRICE = "product_price"
    COMPONENT_COMMISSION = "commission"
    COMPONENT_GATEWAY_FEE = "gateway_fee"
    COMPONENT_SHIPPING = "shipping"
    COMPONENT_RETURN_SHIPPING = "return_shipping"
    COMPONENT_DISCOUNT = "seller_discount"
    COMPONENT_GST = "gst"
    COMPONENT_TDS = "tds"
    COMPONENT_PAYOUT = "payout"
    COMPONENT_RETURN = "return"
    COMPONENT_ADJUSTMENT = "adjustment"
    COMPONENT_CHOICES = (
        (COMPONENT_PRODUCT_PRICE, "Product price"),
        (COMPONENT_COMMISSION, "Commission"),
        (COMPONENT_GATEWAY_FEE, "Gateway fee"),
        (COMPONENT_SHIPPING, "Shipping"),
        (COMPONENT_RETURN_SHIPPING, "Return shipping"),
        (COMPONENT_DISCOUNT, "Seller discount"),
        (COMPONENT_GST, "GST"),
        (COMPONENT_TDS, "TDS"),
        (COMPONENT_PAYOUT, "Payout"),
        (COMPONENT_RETURN, "Return"),
        (COMPONENT_ADJUSTMENT, "Adjustment"),
    )

    STATUS_PENDING = "pending"
    STATUS_HOLD = "hold"
    STATUS_AVAILABLE = "available"
    STATUS_PAID = "paid"
    STATUS_CHOICES = (
        (STATUS_PENDING, "Pending"),
        (STATUS_HOLD, "Hold"),
        (STATUS_AVAILABLE, "Available"),
        (STATUS_PAID, "Paid"),
    )

    seller = models.ForeignKey(
        SellerProfile,
        related_name="ledger_entries",
        on_delete=models.CASCADE,
    )
    order = models.ForeignKey(
        "orders.Order",
        related_name="seller_ledger_entries",
        on_delete=models.CASCADE,
        null=True,
        blank=True,
    )
    payout = models.ForeignKey(
        Payout,
        related_name="ledger_entries",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
    )
    transaction_type = models.CharField(max_length=10, choices=TYPE_CHOICES)
    amount = models.DecimalField(max_digits=12, decimal_places=2)
    component = models.CharField(max_length=30, choices=COMPONENT_CHOICES)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default=STATUS_PENDING)
    reference_id = models.CharField(max_length=120)
    idempotency_key = models.CharField(max_length=150, unique=True)
    notes = models.CharField(max_length=255, blank=True)
    metadata = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ("-created_at", "-id")
        indexes = [
            models.Index(fields=("seller", "status", "created_at")),
            models.Index(fields=("order", "status")),
            models.Index(fields=("reference_id",)),
        ]

    def __str__(self):
        return f"Ledger #{self.id} {self.transaction_type} {self.amount} {self.component}"

    @property
    def signed_amount(self):
        if self.transaction_type == self.TYPE_CREDIT:
            return self.amount
        return -self.amount


class SellerWallet(models.Model):
    seller = models.OneToOneField(
        SellerProfile,
        related_name="wallet",
        on_delete=models.CASCADE,
    )
    pending_balance = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    hold_balance = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    available_balance = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    paid_balance = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Seller wallet"
        verbose_name_plural = "Seller wallets"

    def __str__(self):
        return f"Wallet seller={self.seller_id}"


class TransactionLog(models.Model):
    ACTION_LEDGER_CREATED = "ledger_created"
    ACTION_LEDGER_STATUS_UPDATED = "ledger_status_updated"
    ACTION_RETURN_PROCESSED = "return_processed"
    ACTION_PAYOUT_INITIATED = "payout_initiated"
    ACTION_PAYOUT_COMPLETED = "payout_completed"
    ACTION_PAYOUT_FAILED = "payout_failed"
    ACTION_WALLET_RECALCULATED = "wallet_recalculated"
    ACTION_MANUAL_ADJUSTMENT = "manual_adjustment"
    ACTION_CHOICES = (
        (ACTION_LEDGER_CREATED, "Ledger created"),
        (ACTION_LEDGER_STATUS_UPDATED, "Ledger status updated"),
        (ACTION_RETURN_PROCESSED, "Return processed"),
        (ACTION_PAYOUT_INITIATED, "Payout initiated"),
        (ACTION_PAYOUT_COMPLETED, "Payout completed"),
        (ACTION_PAYOUT_FAILED, "Payout failed"),
        (ACTION_WALLET_RECALCULATED, "Wallet recalculated"),
        (ACTION_MANUAL_ADJUSTMENT, "Manual adjustment"),
    )

    seller = models.ForeignKey(
        SellerProfile,
        related_name="transaction_logs",
        on_delete=models.CASCADE,
        null=True,
        blank=True,
    )
    order = models.ForeignKey(
        "orders.Order",
        related_name="seller_transaction_logs",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
    )
    payout = models.ForeignKey(
        Payout,
        related_name="transaction_logs",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
    )
    ledger_entry = models.ForeignKey(
        SellerLedger,
        related_name="transaction_logs",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
    )
    action = models.CharField(max_length=40, choices=ACTION_CHOICES)
    reference_id = models.CharField(max_length=120, blank=True)
    idempotency_key = models.CharField(max_length=150, blank=True, db_index=True)
    reason = models.CharField(max_length=255, blank=True)
    metadata = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ("-created_at", "-id")
        indexes = [
            models.Index(fields=("seller", "action", "created_at")),
            models.Index(fields=("idempotency_key",)),
        ]

    def __str__(self):
        return f"Audit #{self.id} {self.action}"




