from django.db import models
from django.conf import settings
from products.models import Product, ProductVariant


class Cart(models.Model):
    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="cart",
        null=True,
        blank=True,
    )
    created_at = models.DateTimeField(auto_now_add=True)

    def get_total_price(self):
        return sum(item.get_total_price() for item in self.items.all())


class CartItem(models.Model):
    cart = models.ForeignKey(Cart, related_name="items", on_delete=models.CASCADE)
    product = models.ForeignKey(Product, related_name="cart_items", on_delete=models.CASCADE)
    variant = models.ForeignKey(
        ProductVariant,
        related_name="cart_items",
        on_delete=models.CASCADE,
        null=True,
        blank=True,
    )
    quantity = models.PositiveIntegerField(default=1)

    @property
    def unit_price(self):
        return self.product.discounted_price

    @property
    def taxable_unit_price(self):
        #return self.product.discounted_price
        return self.unit_price

    @property
    def gst_rate(self):
        return self.product.effective_gst_rate

    @property
    def gst_amount(self):
        return self.product.gst_amount_for_price(self.taxable_unit_price)

    @property
    def stock_available(self):
        if self.variant_id:
            return self.variant.stock_quantity
        return self.product.stock

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

    def get_total_price(self):
        return self.unit_price * self.quantity
