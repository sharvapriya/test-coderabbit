import re



from django.db import IntegrityError, models, transaction

from django.conf import settings

from django.core.exceptions import ValidationError

from decimal import Decimal

from django.db.models import Q

from django.utils import timezone

from products.models import Product





class Coupon(models.Model):

    code = models.CharField(max_length=50, unique=True)

    discount_percent = models.PositiveSmallIntegerField()

    active = models.BooleanField(default=True)

    valid_from = models.DateTimeField(null=True, blank=True)

    valid_to = models.DateTimeField(null=True, blank=True)

    minimum_purchase_amount = models.DecimalField(max_digits=10, decimal_places=2, default=0)

    seller = models.ForeignKey(

        "sellers.SellerProfile",

        related_name="coupons",

        on_delete=models.SET_NULL,

        null=True,

        blank=True,

    )

    product = models.ForeignKey(

        Product,

        related_name="coupons",

        on_delete=models.SET_NULL,

        null=True,

        blank=True,

    )



    # def __str__(self):

    #     return self.display_order_id or f"Order {self.id}"

    def __str__(self):

        return self.code



    def is_valid_now(self):

        now = timezone.now()

        if not self.active:

            return False

        if self.valid_from and now < self.valid_from:

            return False

        if self.valid_to and now > self.valid_to:

            return False

        return True





class Order(models.Model):

    PUBLIC_ID_PREFIX = "MYKART"

    PUBLIC_ID_REGEX = re.compile(r"^MYKART/(?P<year>\d{4})/(?P<sequence>\d{3,})$")



    ORDER_STATUS_ACTIVE = "active"

    ORDER_STATUS_CANCELLED = "cancelled"

    ORDER_STATUS_RETURNED = "returned"

    ORDER_STATUS_CHOICES = (

        (ORDER_STATUS_ACTIVE, "Active"),

        (ORDER_STATUS_CANCELLED, "Cancelled"),

        (ORDER_STATUS_RETURNED, "Returned"),

    )



    DELIVERY_TYPE_PLATFORM = "platform"

    DELIVERY_TYPE_OWN = "own_delivery"

    DELIVERY_TYPE_CHOICES = (

        (DELIVERY_TYPE_PLATFORM, "Platform delivery"),

        (DELIVERY_TYPE_OWN, "Own delivery"),

    )



    STATUS_PLACED = "placed"

    STATUS_PAID = "paid"

    STATUS_CONFIRMED = "confirmed"

    STATUS_PACKED = "packed"

    STATUS_SHIPPED = "shipped"

    STATUS_OUT_FOR_DELIVERY = "out_for_delivery"

    STATUS_DELIVERED = "delivered"

    STATUS_RETURNED = "returned"

    STATUS_REFUNDED = "refunded"

    STATUS_CANCELLED = "cancelled"

    STATUS_PARTIALLY_CANCELLED = "partially_cancelled"

    STATUS_CHOICES = (

        (STATUS_PLACED, "Placed"),

        (STATUS_PAID, "Paid"),

        (STATUS_CONFIRMED, "Confirmed"),

        (STATUS_PACKED, "Packed"),

        (STATUS_SHIPPED, "Shipped"),

        (STATUS_OUT_FOR_DELIVERY, "Out for delivery"),

        (STATUS_DELIVERED, "Delivered"),

        (STATUS_RETURNED, "Returned"),

        (STATUS_REFUNDED, "Refunded"),

        (STATUS_PARTIALLY_CANCELLED, "Partially cancelled"),

        (STATUS_CANCELLED, "Cancelled"),

    )

    CANCELLABLE_STATUSES = {STATUS_PLACED, STATUS_CONFIRMED, STATUS_PACKED}



    PAYMENT_COD = "cod"

    PAYMENT_ONLINE = "online"

    PAYMENT_WALLET = "wallet"

    PAYMENT_METHOD_CHOICES = (

        (PAYMENT_COD, "Cash on delivery"),

        (PAYMENT_ONLINE, "Online payment"),

        (PAYMENT_WALLET, "Wallet"),

    )



    user = models.ForeignKey(

        settings.AUTH_USER_MODEL,

        related_name="orders",

        on_delete=models.SET_NULL,

        null=True,

        blank=True,

    )

    full_name = models.CharField(max_length=250)

    email = models.EmailField()

    phone_number = models.CharField(max_length=20)

    address = models.CharField(max_length=250)

    city = models.CharField(max_length=120, blank=True)

    state = models.CharField(max_length=120, blank=True)

    pincode = models.CharField(max_length=20, blank=True)

    country = models.CharField(max_length=120, blank=True)

    created_at = models.DateTimeField(auto_now_add=True)

    updated_at = models.DateTimeField(auto_now=True)

    paid = models.BooleanField(default=False)

    coupon_code = models.CharField(max_length=50, blank=True)

    discount_amount = models.DecimalField(max_digits=10, decimal_places=2, default=0)

    total_amount = models.DecimalField(max_digits=12, decimal_places=2, default=0)

    delivery_charge = models.DecimalField(max_digits=12, decimal_places=2, default=0)

    delivery_type = models.CharField(

        max_length=20,

        choices=DELIVERY_TYPE_CHOICES,

        default=DELIVERY_TYPE_PLATFORM,

    )

    order_status = models.CharField(

        max_length=20,

        choices=ORDER_STATUS_CHOICES,

        default=ORDER_STATUS_ACTIVE,

    )

    shipping_charge = models.DecimalField(max_digits=12, decimal_places=2, default=0)

    return_shipping_charge = models.DecimalField(max_digits=12, decimal_places=2, default=0)

    return_window_days = models.PositiveIntegerField(default=7)

    payment_method = models.CharField(

        max_length=20,

        choices=PAYMENT_METHOD_CHOICES,

        default=PAYMENT_COD,

    )

    wallet_amount_used = models.DecimalField(max_digits=12, decimal_places=2, default=0)

    gateway_amount_paid = models.DecimalField(max_digits=12, decimal_places=2, default=0)

    wallet_amount_refunded = models.DecimalField(max_digits=12, decimal_places=2, default=0)

    status = models.CharField(

        max_length=30,

        choices=STATUS_CHOICES,

        default=STATUS_PLACED,

    )

    is_cancelled = models.BooleanField(default=False)

    cancelled_at = models.DateTimeField(null=True, blank=True)

    cancelled_by = models.ForeignKey(

        settings.AUTH_USER_MODEL,

        related_name="cancelled_orders",

        on_delete=models.SET_NULL,

        null=True,

        blank=True,

    )

    cancellation_reason = models.CharField(max_length=255, blank=True, default="")

    public_id = models.CharField(max_length=32, unique=True, null=True, blank=True)

    public_id_year = models.PositiveIntegerField(null=True, blank=True)

    public_id_sequence = models.PositiveIntegerField(null=True, blank=True)



    class Meta:

        constraints = [

            models.UniqueConstraint(

                fields=("public_id_year", "public_id_sequence"),

                condition=Q(public_id_year__isnull=False, public_id_sequence__isnull=False),

                name="orders_order_public_id_year_sequence_uniq",

            )

        ]
        indexes = [
            models.Index(fields=("status", "created_at")),
            models.Index(fields=("order_status", "created_at")),
            models.Index(fields=("payment_method", "created_at")),
            models.Index(fields=("delivery_type", "created_at")),
            models.Index(fields=("paid", "created_at")),
            models.Index(fields=("user", "created_at")),
        ]



    @classmethod

    def order_year_for(cls, value=None):

        dt = timezone.localtime(value or timezone.now())

        return dt.year



    @classmethod

    def format_public_id(cls, year, sequence):

        return f"{cls.PUBLIC_ID_PREFIX}/{year}/{sequence:03d}"



    @classmethod

    def is_public_id(cls, reference):

        return bool(cls.PUBLIC_ID_REGEX.match((reference or "").strip().upper()))



    @classmethod

    def reference_queryset(cls, reference, queryset=None):

        cleaned_reference = str(reference or "").strip()

        base_queryset = queryset if queryset is not None else cls.objects.all()

        if not cleaned_reference:

            return base_queryset.none()

        if cleaned_reference.isdigit():

            return base_queryset.filter(Q(id=int(cleaned_reference)) | Q(public_id=cleaned_reference.upper()))

        return base_queryset.filter(public_id=cleaned_reference.upper())



    @classmethod

    def get_by_reference(cls, reference, queryset=None):

        return cls.reference_queryset(reference, queryset=queryset).first()



    @classmethod

    def next_public_id_components(cls, value=None):

        year = cls.order_year_for(value)



        with transaction.atomic():

            counter, _ = OrderIdentifierSequence.objects.select_for_update().get_or_create(

                year=year,

                defaults={"last_value": 0},

            )



            counter.last_value = models.F('last_value') + 1

            counter.save(update_fields=["last_value"])

            counter.refresh_from_db()



            return year, counter.last_value, cls.format_public_id(year, counter.last_value)



    def assign_public_id(self, value=None):

        if self.public_id:  # already assigned → STOP

            return self.public_id



        year, sequence, public_id = self.next_public_id_components(

            value=value or getattr(self, "created_at", None)

        )



        self.public_id_year = year

        self.public_id_sequence = sequence

        self.public_id = public_id



        return public_id



    @property

    def legacy_order_id(self):

        return self.pk



    @property

    def display_order_id(self):

        if self.public_id:

            return self.public_id

        return f"Order {self.id}"

    

    def __str__(self):

        return self.display_order_id 





    @property

    def order_reference(self):

        return self.public_id or str(self.pk)



   



    def save(self, *args, **kwargs):

        if self._state.adding:

            with transaction.atomic():

                self.assign_public_id()

        super().save(*args, **kwargs)



    def clean(self):

        super().clean()

        delivery_charge = self.delivery_charge or Decimal("0")

        if delivery_charge < 0:

            raise ValidationError({"delivery_charge": "Delivery charge cannot be negative."})

        subtotal = self.get_original_subtotal_cost() if self.pk else Decimal("0")

        if subtotal and delivery_charge > subtotal:

            raise ValidationError(

                {"delivery_charge": "Delivery charge cannot be greater than the order product total."}

            )



    def get_original_subtotal_cost(self):

        return sum(item.get_cost() for item in self.items.all())



    def get_subtotal_cost(self):

        return sum(item.get_cost() for item in self.items.exclude(status=OrderItem.STATUS_CANCELLED))



    def get_total_cost(self):

        subtotal = self.get_subtotal_cost()

        original_subtotal = self.get_original_subtotal_cost()

        discount_amount = self.discount_amount or Decimal("0")

        if original_subtotal > 0 and subtotal > 0 and discount_amount > 0:

            discount_amount = (

                (discount_amount * subtotal) / original_subtotal

            ).quantize(Decimal("0.01"))

        elif subtotal <= 0:

            discount_amount = Decimal("0")

        total = subtotal - discount_amount

        return total if total > 0 else Decimal("0")



    @property

    def active_items(self):

        return self.items.exclude(status=OrderItem.STATUS_CANCELLED)



    @property

    def can_cancel(self):

        active_items = self.items.exclude(status=OrderItem.STATUS_CANCELLED)

        return (

            self.status in self.CANCELLABLE_STATUSES or self.status == self.STATUS_PARTIALLY_CANCELLED

        ) and active_items.exists() and all(item.can_cancel for item in active_items)



    @classmethod

    def is_cancellable_status(cls, status):

        return status in cls.CANCELLABLE_STATUSES



    def refresh_status_from_items(self, save=True):

        total_items = self.items.count()

        cancelled_items = self.items.filter(status=OrderItem.STATUS_CANCELLED).count()

        if total_items and cancelled_items == total_items:

            self.status = self.STATUS_CANCELLED

            self.is_cancelled = True

            self.order_status = self.ORDER_STATUS_CANCELLED

        elif cancelled_items:

            self.status = self.STATUS_PARTIALLY_CANCELLED

            self.is_cancelled = False

        self.total_amount = self.get_total_cost()

        if save:

            update_fields = ["status", "is_cancelled", "order_status", "total_amount", "updated_at"]

            if self.status == self.STATUS_CANCELLED:

                update_fields.extend(["cancelled_at", "cancelled_by", "cancellation_reason"])

            self.save(update_fields=update_fields)

        return self.status



    def resolve_fulfillment_status(self):

        active_items = list(self.items.exclude(status=OrderItem.STATUS_CANCELLED))

        if not active_items:

            return self.STATUS_CANCELLED



        try:

            assignment = self.delivery_assignment

        except Exception:

            assignment = None



        payout_statuses = []

        for item in active_items:

            try:

                payout_statuses.append(item.seller_payout.delivery_status)

            except Exception:

                continue



        if assignment and assignment.status == DeliveryAssignment.STATUS_DELIVERED:

            return self.STATUS_DELIVERED

        if assignment and assignment.status == DeliveryAssignment.STATUS_OUT_FOR_DELIVERY:

            return self.STATUS_OUT_FOR_DELIVERY

        if assignment and assignment.status == DeliveryAssignment.STATUS_PICKED_UP:

            return self.STATUS_SHIPPED



        delivered_statuses = {"delivered"}

        out_for_delivery_statuses = {"out_for_delivery"}

        shipped_statuses = {"shipped", "handed_to_hub", "at_hub"}

        packed_statuses = {"packed"}



        if any(status in delivered_statuses for status in payout_statuses):

            return self.STATUS_DELIVERED

        if any(status in out_for_delivery_statuses for status in payout_statuses):

            return self.STATUS_OUT_FOR_DELIVERY

        if any(status in shipped_statuses for status in payout_statuses):

            return self.STATUS_SHIPPED

        if payout_statuses and all(status in packed_statuses for status in payout_statuses):

            return self.STATUS_PACKED

        if assignment:

            return self.STATUS_CONFIRMED

        return self.STATUS_PLACED



    @property

    def return_deadline(self):

        """Calculate return deadline (7 days from delivery_at)"""

        try:

            assignment = self.delivery_assignment

            # Check if status is DELIVERED and delivered_at is set

            if assignment and assignment.status == DeliveryAssignment.STATUS_DELIVERED and assignment.delivered_at:

                return assignment.delivered_at + timezone.timedelta(days=self.return_window_days)



            # Alternative: Check if any ordered item is delivered via SellerPayout

            from sellers.models import SellerPayout

            payout = self.items.values_list("seller_payout", flat=True).first()

            if payout:

                payout_obj = SellerPayout.objects.filter(id=payout).first()

                if payout_obj and payout_obj.delivery_status == SellerPayout.DELIVERY_DELIVERED and payout_obj.delivery_status_updated_at:

                    return payout_obj.delivery_status_updated_at + timezone.timedelta(days=self.return_window_days)

        except (DeliveryAssignment.DoesNotExist, Exception):

            pass

        return None



    @property

    def is_returnable(self):

        """Check if order is eligible for return (7 days from delivery)"""

        try:

            from sellers.models import SellerPayout



            # Check DeliveryAssignment (platform delivery)

            assignment = self.delivery_assignment

            if assignment and assignment.status == DeliveryAssignment.STATUS_DELIVERED and assignment.delivered_at:

                deadline = self.return_deadline

                if deadline and timezone.now() <= deadline:

                    return True



            # Check SellerPayout (seller delivery) - if any item is delivered

            for item in self.items.all():

                try:

                    payout = item.seller_payout

                    if payout and payout.delivery_status == SellerPayout.DELIVERY_DELIVERED and payout.delivery_status_updated_at:

                        deadline = payout.delivery_status_updated_at + timezone.timedelta(days=7)

                        if timezone.now() <= deadline:

                            return True

                except Exception:

                    continue



        except Exception:

            pass

        return False





class OrderItem(models.Model):

    STATUS_ACTIVE = "active"

    STATUS_CANCELLED = "cancelled"

    STATUS_CHOICES = (

        (STATUS_ACTIVE, "Active"),

        (STATUS_CANCELLED, "Cancelled"),

    )



    order = models.ForeignKey(Order, related_name="items", on_delete=models.CASCADE)

    product = models.ForeignKey(Product, related_name="order_items", on_delete=models.CASCADE)

    variant = models.ForeignKey(

        "products.ProductVariant",

        related_name="order_items",

        on_delete=models.SET_NULL,

        null=True,

        blank=True

    )

    price = models.DecimalField(max_digits=10, decimal_places=2)

    gst_rate = models.DecimalField(max_digits=5, decimal_places=2, default=0)

    gst_amount = models.DecimalField(max_digits=10, decimal_places=2, default=0)

    quantity = models.PositiveIntegerField(default=1)

    status = models.CharField(

        max_length=20,

        choices=STATUS_CHOICES,

        default=STATUS_ACTIVE,

    )

    is_cancelled = models.BooleanField(default=False)

    cancelled_at = models.DateTimeField(null=True, blank=True)

    cancelled_by = models.ForeignKey(

        settings.AUTH_USER_MODEL,

        related_name="cancelled_order_items",

        on_delete=models.SET_NULL,

        null=True,

        blank=True,

    )

    cancellation_reason = models.CharField(max_length=255, blank=True, default="")



    def get_cost(self):

        return self.price * self.quantity

    def __str__(self):

        return str(self.pk)



    @property

    def taxable_subtotal(self):

        return self.price * self.quantity



    @property

    def gst_subtotal(self):

        return (self.gst_amount or Decimal("0")) * self.quantity



    def get_discount_share(self):

        original_subtotal = self.order.get_original_subtotal_cost()

        if original_subtotal <= 0 or (self.order.discount_amount or Decimal("0")) <= 0:

            return Decimal("0")

        return (

            ((self.order.discount_amount or Decimal("0")) * self.get_cost()) / original_subtotal

        ).quantize(Decimal("0.01"))



    def get_net_cost(self):

        total = self.get_cost() - self.get_discount_share()

        return total if total > 0 else Decimal("0")



    @property

    def variant_summary(self):

        if not self.variant_id:

            return ""

        parts = []

        if self.variant.size:

            parts.append(f"Size: {self.variant.size}")

        if self.variant.color:

            parts.append(f"Color: {self.variant.color}")

        return " | ".join(parts)



    @property

    def can_cancel(self):

        if self.status == self.STATUS_CANCELLED:

            return False

        if self.order.status in {

            Order.STATUS_CANCELLED,

            Order.STATUS_SHIPPED,

            Order.STATUS_OUT_FOR_DELIVERY,

            Order.STATUS_DELIVERED,

        }:

            return False

        try:

            payout = self.seller_payout

        except Exception:

            payout = None

        if payout:

            return payout.delivery_status in {

                "pending",

                "packed",

            }

        try:

            assignment = self.order.delivery_assignment

        except Exception:

            assignment = None

        if assignment:

            return assignment.status == DeliveryAssignment.STATUS_ASSIGNED

        return True





class PaymentTransaction(models.Model):

    STATUS_INITIATED = "initiated"

    STATUS_SUCCESS = "success"

    STATUS_FAILED = "failed"

    STATUS_CHOICES = (

        (STATUS_INITIATED, "Initiated"),

        (STATUS_SUCCESS, "Success"),

        (STATUS_FAILED, "Failed"),

    )



    GATEWAY_COD = "cod"

    GATEWAY_RAZORPAY = "razorpay"

    GATEWAY_WALLET = "wallet"

    GATEWAY_CHOICES = (

        (GATEWAY_COD, "Cash on delivery"),

        (GATEWAY_RAZORPAY, "Razorpay"),

        (GATEWAY_WALLET, "Wallet"),

    )



    order = models.ForeignKey(

        Order,

        related_name="payment_transactions",

        on_delete=models.CASCADE,

        null=True,

        blank=True,

    )

    user = models.ForeignKey(

        settings.AUTH_USER_MODEL,

        related_name="payment_transactions",

        on_delete=models.SET_NULL,

        null=True,

        blank=True,

    )

    payment_method = models.CharField(max_length=20, choices=Order.PAYMENT_METHOD_CHOICES)

    gateway = models.CharField(max_length=20, choices=GATEWAY_CHOICES)

    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default=STATUS_INITIATED)

    amount = models.DecimalField(max_digits=12, decimal_places=2)

    currency = models.CharField(max_length=10, default="INR")

    gateway_order_id = models.CharField(max_length=120, blank=True)

    gateway_payment_id = models.CharField(max_length=120, blank=True)

    gateway_signature = models.CharField(max_length=255, blank=True)

    failure_reason = models.CharField(max_length=255, blank=True)

    raw_response = models.JSONField(default=dict, blank=True)

    created_at = models.DateTimeField(auto_now_add=True)

    updated_at = models.DateTimeField(auto_now=True)



    class Meta:

        ordering = ("-created_at",)
        indexes = [
            models.Index(fields=("status", "created_at")),
            models.Index(fields=("gateway", "created_at")),
            models.Index(fields=("payment_method", "created_at")),
            models.Index(fields=("user", "created_at")),
            models.Index(fields=("order", "created_at")),
        ]



    # def __str__(self):

    #     return f"Txn #{self.id} - {self.order.display_order_id} - {self.status}"



    def __str__(self):

        if self.order:

            return f"Txn #{self.id} - {self.order.display_order_id} - {self.status}"

        return f"Txn #{self.id} - No Order - {self.status}"

    

class DeliveryAssignment(models.Model):

    STATUS_ASSIGNED = "assigned"

    STATUS_PICKED_UP = "picked_up"

    STATUS_OUT_FOR_DELIVERY = "out_for_delivery"

    STATUS_DELIVERED = "delivered"

    STATUS_DELIVERY_FAILED = "delivery_failed"

    STATUS_RETURNED = "returned"

    STATUS_CHOICES = (

        (STATUS_ASSIGNED, "Assigned"),

        (STATUS_PICKED_UP, "Picked up"),

        (STATUS_OUT_FOR_DELIVERY, "Out for delivery"),

        (STATUS_DELIVERED, "Delivered"),

        (STATUS_DELIVERY_FAILED, "Delivery failed"),

        (STATUS_RETURNED, "Returned"),

    )



    COD_NOT_APPLICABLE = "not_applicable"

    COD_PENDING = "pending_collection"

    COD_COLLECTED = "collected"

    COD_COLLECTION_FAILED = "collection_failed"

    COD_STATUS_CHOICES = (

        (COD_NOT_APPLICABLE, "Not applicable"),

        (COD_PENDING, "Pending collection"),

        (COD_COLLECTED, "Collected"),

        (COD_COLLECTION_FAILED, "Collection failed"),

    )



    order = models.OneToOneField(

        Order,

        related_name="delivery_assignment",

        on_delete=models.CASCADE,

    )

    delivery_agent = models.ForeignKey(

        settings.AUTH_USER_MODEL,

        related_name="delivery_assignments",

        on_delete=models.SET_NULL,

        null=True,

        blank=True,

    )

    status = models.CharField(max_length=30, choices=STATUS_CHOICES, default=STATUS_ASSIGNED)

    cod_payment_status = models.CharField(

        max_length=30,

        choices=COD_STATUS_CHOICES,

        default=COD_NOT_APPLICABLE,

    )

    cod_collected_amount = models.DecimalField(max_digits=12, decimal_places=2, default=0)

    customer_note = models.CharField(max_length=255, blank=True)

    internal_note = models.CharField(max_length=255, blank=True)

    updated_by = models.ForeignKey(

        settings.AUTH_USER_MODEL,

        related_name="updated_delivery_assignments",

        on_delete=models.SET_NULL,

        null=True,

        blank=True,

    )

    delivered_at = models.DateTimeField(null=True, blank=True)

    cod_collected_at = models.DateTimeField(null=True, blank=True)

    created_at = models.DateTimeField(auto_now_add=True)

    updated_at = models.DateTimeField(auto_now=True)



    class Meta:

        ordering = ("-updated_at", "-created_at")



    def __str__(self):

        return f"Delivery #{self.id} - {self.order.display_order_id}" 





class Wallet(models.Model):

    """User wallet for storing refund balance"""

    user = models.OneToOneField(

        settings.AUTH_USER_MODEL,

        related_name="wallet",

        on_delete=models.CASCADE,

    )

    balance = models.DecimalField(max_digits=12, decimal_places=2, default=0)

    created_at = models.DateTimeField(auto_now_add=True)

    updated_at = models.DateTimeField(auto_now=True)



    def __str__(self):

        return f"Wallet - {self.user.username} (Balance: ${self.balance})"





class WalletTransaction(models.Model):

    TYPE_CREDIT = "credit"

    TYPE_DEBIT = "debit"

    TYPE_CHOICES = (

        (TYPE_CREDIT, "Credit"),

        (TYPE_DEBIT, "Debit"),

    )



    SOURCE_REFUND = "refund"

    SOURCE_ORDER_PAYMENT = "order_payment"

    SOURCE_ORDER_ADJUSTMENT = "order_adjustment"

    SOURCE_CHOICES = (

        (SOURCE_REFUND, "Refund"),

        (SOURCE_ORDER_PAYMENT, "Order payment"),

        (SOURCE_ORDER_ADJUSTMENT, "Order adjustment"),

    )



    wallet = models.ForeignKey(

        Wallet,

        related_name="transactions",

        on_delete=models.CASCADE,

    )

    order = models.ForeignKey(

        Order,

        related_name="wallet_transactions",

        on_delete=models.SET_NULL,

        null=True,

        blank=True,

    )

    return_request = models.ForeignKey(

        "ReturnRequest",

        related_name="wallet_transactions",

        on_delete=models.SET_NULL,

        null=True,

        blank=True,

    )

    transaction_type = models.CharField(max_length=20, choices=TYPE_CHOICES)

    source = models.CharField(max_length=30, choices=SOURCE_CHOICES)

    amount = models.DecimalField(max_digits=12, decimal_places=2)

    balance_after = models.DecimalField(max_digits=12, decimal_places=2)

    description = models.CharField(max_length=255, blank=True)

    metadata = models.JSONField(default=dict, blank=True)

    created_at = models.DateTimeField(auto_now_add=True)



    class Meta:

        ordering = ("-created_at", "-id")
        verbose_name = "Cancelled Order"
        verbose_name_plural = "Cancelled Orders"
        verbose_name = "Cancelled Order"
        verbose_name_plural = "Cancelled Orders"



    def __str__(self):

        return f"{self.get_transaction_type_display()} ₹{self.amount} - {self.order.display_order_id if self.order else ''}"





class OrderStatusHistory(models.Model):

    order = models.ForeignKey(

        Order,

        related_name="status_history",

        on_delete=models.CASCADE,

    )

    order_item = models.ForeignKey(

        OrderItem,

        related_name="status_history",

        on_delete=models.CASCADE,

        null=True,

        blank=True,

    )

    from_status = models.CharField(max_length=30, blank=True)

    to_status = models.CharField(max_length=30)

    reason = models.CharField(max_length=255, blank=True)

    changed_by = models.ForeignKey(

        settings.AUTH_USER_MODEL,

        related_name="order_status_updates",

        on_delete=models.SET_NULL,

        null=True,

        blank=True,

    )

    created_at = models.DateTimeField(auto_now_add=True)

    metadata = models.JSONField(default=dict, blank=True)



    class Meta:

        ordering = ("-created_at", "-id")



    def __str__(self):

        return f"{self.order.display_order_id}: {self.from_status or 'unknown'} → {self.to_status}"





class ReturnRequest(models.Model):

    REASON_DEFECTIVE = "defective"

    REASON_WRONG_ITEM = "wrong_item"

    REASON_NOT_AS_DESCRIBED = "not_as_described"

    REASON_CHANGED_MIND = "changed_mind"

    REASON_SIZE_FIT = "size_fit"

    REASON_DAMAGED = "damaged"

    REASON_MISSING_PARTS = "missing_parts"

    REASON_OTHER = "other"



    REASON_CHOICES = (

        (REASON_DEFECTIVE, "Defective/Broken"),

        (REASON_WRONG_ITEM, "Wrong item received"),

        (REASON_NOT_AS_DESCRIBED, "Not as described"),

        (REASON_CHANGED_MIND, "Changed my mind"),

        (REASON_SIZE_FIT, "Size/Fit issue"),

        (REASON_DAMAGED, "Damaged during delivery"),

        (REASON_MISSING_PARTS, "Missing parts"),

        (REASON_OTHER, "Other"),

    )



    STATUS_PENDING = "pending"

    STATUS_APPROVED = "approved"

    STATUS_WITHDRAWN = "withdrawn"   
    

    STATUS_PICKED_UP = "picked_up"

    STATUS_REFUNDED = "refunded"

    STATUS_REJECTED = "rejected"

    

    STATUS_SHIPPED_BY_BUYER = "shipped_by_buyer"

    STATUS_RECEIVED_BY_SELLER = "received_by_seller"

    STATUS_REFUND_COMPLETED = "refund_completed"



    STATUS_CHOICES = (

        (STATUS_PENDING, "Pending"),

        (STATUS_APPROVED, "Approved"),

        (STATUS_PICKED_UP, "Picked Up"),

        (STATUS_REFUNDED, "Refunded"),

        (STATUS_REJECTED, "Rejected"),

        (STATUS_WITHDRAWN, "Withdrawn"),

        (STATUS_SHIPPED_BY_BUYER, "Shipped by Buyer"),

        (STATUS_RECEIVED_BY_SELLER, "Received by Seller"),

        (STATUS_REFUND_COMPLETED, "Refund Completed"),

    )



    order = models.ForeignKey(

        Order,

        related_name="return_requests",

        on_delete=models.CASCADE,

    )

    user = models.ForeignKey(

        settings.AUTH_USER_MODEL,

        related_name="return_requests",

        on_delete=models.CASCADE,

    )

    product = models.ForeignKey(

        Product,

        related_name="return_requests",

        on_delete=models.CASCADE,

    )

    reason = models.CharField(max_length=20, choices=REASON_CHOICES)

    description = models.TextField(blank=True, help_text="Additional details about the return")

    photo = models.ImageField(

        upload_to="return_requests/%Y/%m/%d/",

        blank=True,

        null=True,

        help_text="Upload a photo of the item (optional)",

    )

    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default=STATUS_PENDING)

    admin_notes = models.TextField(blank=True)

    refund_amount = models.DecimalField(max_digits=12, decimal_places=2, default=0)

    shipped_at = models.DateTimeField(null=True, blank=True)

    created_at = models.DateTimeField(auto_now_add=True)

    updated_at = models.DateTimeField(auto_now=True)



    class Meta:

        ordering = ("-created_at",)

        unique_together = [("order", "product")]
        indexes = [
            models.Index(fields=("status", "created_at")),
            models.Index(fields=("reason", "created_at")),
            models.Index(fields=("user", "created_at")),
            models.Index(fields=("product", "created_at")),
            models.Index(fields=("order", "created_at")),
        ]



    def __str__(self):

        return f"Return Request #{self.id} - {self.order.display_order_id} - {self.get_status_display()}"



    @property

    def seller_return_address(self):
        """Get the seller's return address from SellerProduct."""
        try:
            seller_product = self.product.seller_product
            if seller_product.delivery_mode == "own_delivery":

                return seller_product.shipping_details

            else:  # hub_delivery

                return seller_product.hub_address

        except Exception:
            return None


class ReturnRequestImage(models.Model):
    return_request = models.ForeignKey(
        ReturnRequest,
        related_name="images",
        on_delete=models.CASCADE,
    )
    image = models.ImageField(upload_to="return_requests/%Y/%m/%d/")
    uploaded_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ("uploaded_at",)

    def __str__(self):
        return f"Image for return request #{self.return_request_id}"


class Review(models.Model):

    AUTO_FLAG_THRESHOLD = 3



    user = models.ForeignKey(

        settings.AUTH_USER_MODEL,

        on_delete=models.SET_NULL,

        null=True,

        related_name="reviews",

    )

    product = models.ForeignKey(

        Product,

        on_delete=models.CASCADE,

        related_name="reviews",

    )

    rating = models.IntegerField(

        choices=[(i, f"{i} Star{'s' if i != 1 else ''}") for i in range(1, 6)]

    )

    comment = models.TextField(max_length=1000, blank=True)

    created_at = models.DateTimeField(auto_now_add=True)

    updated_at = models.DateTimeField(auto_now=True)

    is_verified_purchase = models.BooleanField(default=False)

    is_reported = models.BooleanField(default=False)

    report_count = models.PositiveIntegerField(default=0)

    is_flagged = models.BooleanField(default=False)



    class Meta:

        ordering = ("-created_at",)
        indexes = [
            models.Index(fields=("rating", "created_at")),
            models.Index(fields=("is_verified_purchase", "created_at")),
            models.Index(fields=("is_reported", "created_at")),
            models.Index(fields=("is_flagged", "created_at")),
            models.Index(fields=("user", "created_at")),
            models.Index(fields=("product", "created_at")),
        ]



    def __str__(self):

        username = self.user.username if self.user else "Deleted user"

        return f"Review of {self.product.name} by {username}"



    def refresh_report_flags(self, save=True):

        self.is_reported = self.report_count > 0

        self.is_flagged = self.report_count > self.AUTO_FLAG_THRESHOLD

        if save:

            self.save(update_fields=["is_reported", "is_flagged", "updated_at"])

        return self.is_flagged





class ReviewReport(models.Model):

    STATUS_PENDING = "pending"

    STATUS_RESOLVED = "resolved"

    STATUS_REJECTED = "rejected"

    STATUS_CHOICES = (

        (STATUS_PENDING, "Pending"),

        (STATUS_RESOLVED, "Resolved"),

        (STATUS_REJECTED, "Rejected"),

    )



    review = models.ForeignKey(

        Review,

        on_delete=models.CASCADE,

        related_name="reports",

    )

    reported_by = models.ForeignKey(

        settings.AUTH_USER_MODEL,

        on_delete=models.CASCADE,

        related_name="review_reports",

    )

    reason = models.TextField(max_length=500)

    created_at = models.DateTimeField(auto_now_add=True)

    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default=STATUS_PENDING)



    class Meta:

        constraints = [

            models.UniqueConstraint(

                fields=("review", "reported_by"),

                name="unique_review_report_per_user",

            )

        ]

        ordering = ("-created_at",)
        indexes = [
            models.Index(fields=("status", "created_at")),
            models.Index(fields=("reported_by", "created_at")),
            models.Index(fields=("review", "created_at")),
        ]



    def __str__(self):

        return f"Report #{self.id} for review #{self.review_id}"





class ReviewImage(models.Model):

    review = models.ForeignKey(

        Review,

        on_delete=models.CASCADE,

        related_name="images",

    )

    image = models.ImageField(

        upload_to="reviews/%Y/%m/%d/",

        max_length=500,

    )

    uploaded_at = models.DateTimeField(auto_now_add=True)



    class Meta:

        ordering = ("uploaded_at",)



    def __str__(self):

        return f"Image for review #{self.review.id}"





class OrderIdentifierSequence(models.Model):

    year = models.PositiveIntegerField(unique=True)

    last_value = models.PositiveIntegerField(default=0)

    created_at = models.DateTimeField(auto_now_add=True)

    updated_at = models.DateTimeField(auto_now=True)



    class Meta:

        ordering = ("year",)



    def __str__(self):

        return f"{self.year}: {self.last_value}"




