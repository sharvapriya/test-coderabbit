from django.shortcuts import render, get_object_or_404, redirect

from django.urls import reverse

from products.models import Product, ProductVariant

from .models import Cart, CartItem

from django.views.decorators.http import require_POST

from django.http import JsonResponse

from cart.models import Cart, CartItem





def _get_or_create_session_cart(request):

    # For authenticated users, use user-based cart

    if request.user.is_authenticated:

        cart, created = Cart.objects.get_or_create(user=request.user)

        # Store cart_id in session for consistency

        request.session['cart_id'] = cart.id

        return cart

    

    # For anonymous users, use session-based cart

    cart_id = request.session.get('cart_id')



    if cart_id:

        try:

            cart = Cart.objects.get(id=cart_id, user__isnull=True)

        except Cart.DoesNotExist:

            cart = Cart.objects.create()

            request.session['cart_id'] = cart.id

    else:

        cart = Cart.objects.create()

        request.session['cart_id'] = cart.id



    return cart





def _reset_buy_now_checkout_cart(request):
    checkout_cart_id = request.session.get("checkout_cart_id")
    if checkout_cart_id:
        Cart.objects.filter(id=checkout_cart_id).delete()
        request.session.pop("checkout_cart_id", None)
    request.session.pop("checkout_mode", None)





def _get_requested_variant(request, product):

    if not product.has_variants:

        return None, None



    variant_id = request.POST.get("variant_id") or request.GET.get("variant_id")

    if not variant_id:

        return None, "Please select an available variant before continuing."



    variant = ProductVariant.objects.filter(

        id=variant_id,

        product=product,

        is_active=True,

    ).first()

    if not variant:

        return None, "The selected variant is no longer available."



    return variant, None





def _add_product_to_cart(cart, product, variant=None):

    cart_item, created = CartItem.objects.get_or_create(

        cart=cart,

        product=product,

        variant=variant,

    )

    available_stock = variant.stock_quantity if variant else product.stock



    if not created:

        if cart_item.quantity >= available_stock:

            return None, f"Only {available_stock} unit(s) available for {product.name}."

        cart_item.quantity += 1



    cart_item.save()

    return cart_item, None





def _get_cart_count(cart):

    return sum(item.quantity for item in cart.items.all())





@require_POST

def cart_add(request, product_id):

    cart = _get_or_create_session_cart(request)

    # product = get_object_or_404(Product, id=product_id, available=True)

    product = get_object_or_404(Product.objects.publicly_visible(), id=product_id)

    fallback_url = request.META.get('HTTP_REFERER') or reverse('products:product_detail', args=[product.id, product.slug])

    variant, variant_error = _get_requested_variant(request, product)



    if variant_error:

        if request.headers.get('x-requested-with') == 'XMLHttpRequest':

            return JsonResponse({

                "success": False,

                "message": variant_error,

            }, status=400)

        return redirect(fallback_url)



    available_stock = variant.stock_quantity if variant else product.stock



    if available_stock < 1:

        item_label = f"{product.name} ({variant.variant_label})" if variant else product.name

        if request.headers.get('x-requested-with') == 'XMLHttpRequest':

            return JsonResponse({

                "success": False,

                "message": f"{item_label} is out of stock.",

            }, status=400)

        return redirect(fallback_url)

        # return JsonResponse(

        #     {

        #         "success": False,

        #         "message": f"{product.name} is out of stock.",

        #     },

        #     status=400,

        # )

    

    cart_item, error_message = _add_product_to_cart(cart, product, variant=variant)

    if error_message:

        if request.headers.get('x-requested-with') == 'XMLHttpRequest':

            return JsonResponse({

                "success": False,

                "message": error_message,

            }, status=400)

        return redirect(fallback_url)

    

     # If request is AJAX → return JSON

    if request.headers.get('x-requested-with') == 'XMLHttpRequest':

    

        return JsonResponse({

            "success": True,

            "message": f"Added {product.name}{f' ({variant.variant_label})' if variant else ''} to cart",

            "cart_count": _get_cart_count(cart),

        })



    # Otherwise redirect back to the page

    return redirect(fallback_url)





def buy_now(request, product_id):
    if not request.user.is_authenticated:
        return redirect(f"{reverse('login')}?next={request.get_full_path()}")

    product = get_object_or_404(Product.objects.publicly_visible(), id=product_id)
    variant, variant_error = _get_requested_variant(request, product)
    if variant_error:
        return redirect(request.META.get('HTTP_REFERER', reverse('products:product_detail', args=[product.id, product.slug])))

    available_stock = variant.stock_quantity if variant else product.stock
    if available_stock < 1:
        return redirect(request.META.get('HTTP_REFERER', reverse('products:product_detail', args=[product.id, product.slug])))

    selection_mode = (request.GET.get("selection_mode") or "").strip()
    source = (request.GET.get("source") or "").strip()

    if selection_mode == "checkout":
        cart = _get_or_create_session_cart(request)
        request.session["checkout_mode"] = "cart"
        request.session.pop("checkout_cart_id", None)
    else:
        _reset_buy_now_checkout_cart(request)
        cart = Cart.objects.create()
        request.session["checkout_cart_id"] = cart.id
        request.session["checkout_mode"] = "buy_now"
    
    _, error_message = _add_product_to_cart(cart, product, variant=variant)
    if error_message:
        if selection_mode != "checkout":
            Cart.objects.filter(id=cart.id).delete()
            request.session.pop("checkout_cart_id", None)
        return redirect(request.META.get('HTTP_REFERER', reverse('products:product_detail', args=[product.id, product.slug])))

    if selection_mode == "checkout":
        redirect_url = reverse("orders:payment_step")
        if source:
            redirect_url = f"{redirect_url}?source={source}"
        return redirect(redirect_url)

    return redirect('orders:payment_step')

    # return redirect('payment_checkout')

    

    # response_data = {

    #     "success":True,

    #     "message": f'Added {product.name} to cart'

    # }

    

    # return JsonResponse(response_data)

    

    

def cart_detail(request):

    cart = None

    cart_items = []

    checkout_summary = {

        "subtotal": 0,

        "discount_amount": 0,

        "final_total": 0,

        "coupon_code": "",

    }

    

    # For authenticated users, get their user cart

    if request.user.is_authenticated:

        try:

            cart = Cart.objects.prefetch_related("items").get(user=request.user)

        except Cart.DoesNotExist:

            cart = None

    else:

        # For anonymous users, get session cart

        cart_id = request.session.get('cart_id')

        if cart_id:

            try:

                cart = Cart.objects.prefetch_related("items").get(id=cart_id, user__isnull=True)

            except Cart.DoesNotExist:

                cart = None

    

    if not cart or not cart.items.exists():

        cart = None

    else:

        cart_items = list(cart.items.select_related("product", "variant"))

        from orders.views import _build_checkout_context



        checkout_summary = _build_checkout_context(request, cart_items)

    

    return render(

        request,

        "cart/detail.html",

        {

            "cart": cart,

            "cart_items": cart_items,

            **checkout_summary,

        },

    )

    

@require_POST

def cart_remove(request, product_id):

    # For authenticated users, get their user cart

    if request.user.is_authenticated:

        cart = get_object_or_404(Cart, user=request.user)

    else:

        # For anonymous users, get session cart

        cart_id = request.session.get('cart_id')

        cart = get_object_or_404(Cart, id=cart_id, user__isnull=True)

    

    item = get_object_or_404(CartItem, id=product_id, cart=cart)

    item.delete()

    

    return redirect("cart:cart_detail")



@require_POST

def cart_update_quantity(request, item_id, action):

    # For authenticated users, get their user cart

    if request.user.is_authenticated:

        cart = get_object_or_404(Cart, user=request.user)

    else:

        # For anonymous users, get session cart

        cart_id = request.session.get('cart_id')

        cart = get_object_or_404(Cart, id=cart_id, user__isnull=True)

    

    item = get_object_or_404(CartItem, id=item_id, cart=cart)



    if action == "increase":

        if item.quantity < item.stock_available:

            item.quantity += 1

            item.save()

    elif action == "decrease" and item.quantity > 1:

        item.quantity -= 1

        item.save()



    return redirect("cart:cart_detail")



    

