from decimal import Decimal, ROUND_HALF_UP

from django.db import models
from django.db.models import Sum
from django.urls import reverse
from django.conf import settings


class ProductQuerySet(models.QuerySet):
    def approved(self):
        return self.filter(status=Product.STATUS_APPROVED)

    def publicly_visible(self):
        return self.approved().filter(available=True)


class Category(models.Model):
    GST_RATE_CHOICES = (
        (Decimal("0.00"), "No GST / 0%"),
        (Decimal("5.00"), "5%"),
        (Decimal("12.00"), "12%"),
        (Decimal("18.00"), "18%"),
        (Decimal("28.00"), "28%"),
    )

    name = models.CharField(max_length=250)
    slug = models.SlugField(unique=True)
    gst_rate = models.DecimalField(
        max_digits=5,
        decimal_places=2,
        default=Decimal("18.00"),
        choices=GST_RATE_CHOICES,
        help_text="GST rate as percentage for this category."
    )
    hsn_code = models.CharField(max_length=20, blank=True)
    
    class Meta:
        verbose_name_plural = "categories"
    
    def __str__(self):
        return self.name
    

class Product(models.Model):
    STATUS_PENDING = "pending"
    STATUS_APPROVED = "approved"
    STATUS_REJECTED = "rejected"
    STATUS_CHOICES = (
        (STATUS_PENDING, "Pending"),
        (STATUS_APPROVED, "Approved"),
        (STATUS_REJECTED, "Rejected"),
    )

    category = models.ForeignKey(Category, related_name='products', on_delete=models.CASCADE)
    brand = models.CharField(max_length=120, blank=True)
    name = models.CharField(max_length=250)
    slug = models.SlugField(max_length=250)
    description = models.TextField(blank=True)
    price = models.DecimalField(max_digits=10, decimal_places=2)
    gst_rate = models.DecimalField(
        max_digits=5,
        decimal_places=2,
        choices=Category.GST_RATE_CHOICES,
        default=Decimal("18.00"),
    )
    hsn_code = models.CharField(max_length=20, blank=True)
    discount_percent = models.DecimalField(
        max_digits=5,
        decimal_places=2,
        default=Decimal("0.00"),
        blank=True,
    )
    discount_amount = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        default=Decimal("0.00"),
        blank=True,
    )
    stock = models.PositiveIntegerField(default=0)
    available = models.BooleanField(default=True)
    status = models.CharField(
        max_length=20,
        choices=STATUS_CHOICES,
        default=STATUS_PENDING,
    )
    rejection_reason = models.TextField(blank=True)
    created = models.DateTimeField(auto_now_add=True)
    updated = models.DateTimeField(auto_now=True)
    image = models.ImageField(upload_to='products', blank=True, null=True)

    objects = ProductQuerySet.as_manager()

    class Meta:
        indexes = [
            models.Index(fields=("status", "created")),
            models.Index(fields=("available", "created")),
            models.Index(fields=("category", "created")),
            models.Index(fields=("updated",)),
        ]
    
    def __str__(self) -> str:
        return self.name
    
    def get_absolute_url(self):
        return reverse('products:product_detail', kwargs={'id':self.id, 'slug':self.slug})

    @property
    def is_publicly_visible(self):
        return self.status == self.STATUS_APPROVED and self.available

    def submit_for_review(self, *, save=True):
        self.status = self.STATUS_PENDING
        self.rejection_reason = ""
        self.available = False
        if save:
            self.save(update_fields=["status", "rejection_reason", "available", "updated"])
        return self

    def approve(self, *, reason="", save=True):
        self.status = self.STATUS_APPROVED
        self.rejection_reason = reason or ""
        self.available = True
        if save:
            self.save(update_fields=["status", "rejection_reason", "available", "updated"])
        return self

    def reject(self, *, reason="", save=True):
        self.status = self.STATUS_REJECTED
        self.rejection_reason = reason or ""
        self.available = False
        if save:
            self.save(update_fields=["status", "rejection_reason", "available", "updated"])
        return self

    def _quantize_money(self, value):
        return value.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)

    @property
    def effective_gst_rate(self):
        category_rate = None
        if self.category_id and getattr(self.category, "gst_rate", None) is not None:
            category_rate = self._quantize_money(self.category.gst_rate)
        product_rate = self._quantize_money(self.gst_rate) if self.gst_rate is not None else None
        if (
            category_rate is not None
            and category_rate != Decimal("18.00")
            and product_rate == Decimal("18.00")
        ):
            return category_rate
        if product_rate is not None:
            return product_rate
        if category_rate is not None:
            return category_rate
        return Decimal("18.00")

    @property
    def effective_hsn_code(self):
        if self.hsn_code:
            return self.hsn_code
        if self.category_id:
            return getattr(self.category, "hsn_code", "") or ""
        return ""

    def gst_amount_for_price(self, price=None):
        inclusive_price = self._quantize_money(price if price is not None else self.discounted_price)
        gst_rate = self.effective_gst_rate
        if gst_rate <= Decimal("0.00"):
            return Decimal("0.00")
        return self._quantize_money(
            (inclusive_price * gst_rate) / (Decimal("100") + gst_rate)
        )

    @property
    def discounted_price_with_gst(self):
        return self.discounted_price

    @property
    def discount_percent_value(self):
        price = self.price or Decimal("0.00")
        percent = self.discount_percent or Decimal("0.00")
        amount = self.discount_amount or Decimal("0.00")
        if percent > 0:
            return percent
        if amount > 0 and price > 0:
            computed = (amount * Decimal("100")) / price
            return computed.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        return Decimal("0.00")

    @property
    def discounted_price(self):
        price = self.price or Decimal("0.00")
        percent = self.discount_percent or Decimal("0.00")
        amount = self.discount_amount or Decimal("0.00")
        if percent > 0:
            discount = (price * percent) / Decimal("100")
        elif amount > 0:
            discount = amount
        else:
            return price
        discounted = price - discount
        if discounted < 0:
            discounted = Decimal("0.00")
        return self._quantize_money(discounted)

    @property
    def has_discount(self):
        price = self.price or Decimal("0.00")
        return self.discounted_price < price

    @property
    def has_variants(self):
        return self.variants.filter(is_active=True).exists()

    @property
    def active_variants(self):
        return self.variants.filter(is_active=True)

    @property
    def available_variants(self):
        return self.active_variants.filter(stock_quantity__gt=0)

    @property
    def effective_stock(self):
        if self.has_variants:
            return self.available_variants.aggregate(total=Sum("stock_quantity"))["total"] or 0
        return self.stock

    @property
    def is_in_stock(self):
        return self.effective_stock > 0


class ProductVariant(models.Model):
    product = models.ForeignKey(
        Product,
        related_name="variants",
        on_delete=models.CASCADE,
    )
    size = models.CharField(max_length=120, blank=True, null=True)
    color = models.CharField(max_length=120, blank=True, null=True)
    stock_quantity = models.PositiveIntegerField(default=0)
    sku = models.CharField(max_length=255, unique=True)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["product", "size", "color"],
                name="unique_product_variant_combination",
            )
        ]
        indexes = [
            models.Index(fields=["product", "size", "color"]),
        ]

    def __str__(self):
        return f"{self.product.name} Variant ({self.variant_label})"

    @property
    def variant_label(self):
        label = []
        if self.size:
            label.append(self.size)
        if self.color:
            label.append(self.color)
        return ", ".join(label) or "default"


class ProductImage(models.Model):
    product = models.ForeignKey(
        Product,
        related_name='images',
        on_delete=models.CASCADE
    )
    image = models.ImageField(upload_to='products/multiple/')
    sort_order = models.PositiveSmallIntegerField(default=0)

    def __str__(self):
        return f"Image for {self.product.name}"
    

class StockAlertSubscription(models.Model):
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        related_name="stock_alert_subscriptions",
        on_delete=models.CASCADE,
    )
    product = models.ForeignKey(
        Product,
        related_name="stock_alert_subscriptions",
        on_delete=models.CASCADE,
    )
    is_notified = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)
    notified_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["user", "product"],
                name="unique_stock_alert_user_product",
            )
        ]

    def __str__(self):
        return f"{self.user} - {self.product.name}"
