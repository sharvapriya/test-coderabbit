

# Create your views here.
from django.shortcuts import get_object_or_404, redirect, render
from django.contrib.auth.decorators import login_required
from .models import Wishlist
from products.models import Product



@login_required
def add_to_wishlist(request, product_id):
    product = get_object_or_404(Product.objects.publicly_visible(), id=product_id)
    Wishlist.objects.get_or_create(user=request.user, product=product)
    return redirect(request.META.get('HTTP_REFERER', 'home'))


@login_required
def remove_from_wishlist(request, product_id):
    product = get_object_or_404(Product.objects.publicly_visible(), id=product_id)
    Wishlist.objects.filter(user=request.user, product=product).delete()
    return redirect(request.META.get('HTTP_REFERER', 'home'))


@login_required
def wishlist_view(request):
    wishlist_items = Wishlist.objects.filter(
        user=request.user,
        product__status=Product.STATUS_APPROVED,
        product__available=True,
    )
    return render(request, 'wishlist/wishlist.html', {'wishlist_items': wishlist_items})
