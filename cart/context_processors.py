from .models import Cart


def cart_count(request):
    count = 0
    
    # For authenticated users, get their user cart
    if request.user.is_authenticated:
        try:
            cart = Cart.objects.prefetch_related("items").get(user=request.user)
            count = sum(item.quantity for item in cart.items.all())
        except Cart.DoesNotExist:
            count = 0
    else:
        # For anonymous users, get session cart
        cart_id = request.session.get("cart_id")
        if cart_id:
            try:
                cart = Cart.objects.prefetch_related("items").get(id=cart_id, user__isnull=True)
                count = sum(item.quantity for item in cart.items.all())
            except Cart.DoesNotExist:
                count = 0

    return {"cart_count": count}
