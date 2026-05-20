

# Create your models here.
from django.db import models
from django.contrib.auth.models import User
from products.models import Product   # adjust if your app name is different

class Wishlist(models.Model):
    user = models.ForeignKey(User, on_delete=models.CASCADE)
    product = models.ForeignKey(Product, on_delete=models.CASCADE)
    added_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ('user', 'product')  # prevent duplicate wishlist items

    def __str__(self):
        return f"{self.user.username} - {self.product.name}"