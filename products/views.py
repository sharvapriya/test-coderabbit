from datetime import timedelta

from decimal import Decimal, InvalidOperation



from django.contrib.auth.decorators import login_required
from django.db.models import Q, Avg, Count
from django.contrib import messages
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_POST
from django.urls import reverse

from wishlist.models import Wishlist
from orders.forms import ReviewReportForm
from cart.views import _get_or_create_session_cart, _add_product_to_cart

from .models import Category, Product, StockAlertSubscription









def _consume_restock_notifications(request):

    if not request.user.is_authenticated:

        return []



    subscriptions = list(

        StockAlertSubscription.objects.filter(

            user=request.user,

            is_notified=False,

            product__stock__gt=0,

            product__available=True,

            product__status=Product.STATUS_APPROVED,

        ).select_related("product")

    )



    if not subscriptions:

        return []



    now = timezone.now()

    subscription_ids = [subscription.id for subscription in subscriptions]



    StockAlertSubscription.objects.filter(id__in=subscription_ids).update(

        is_notified=True,

        notified_at=now,

    )



    return [subscription.product for subscription in subscriptions]





def home(request):

    categories = Category.objects.all()

    public_products = Product.objects.publicly_visible()



    # Top 4 categories by product count

    top_categories = (

        Category.objects.annotate(

            product_count=Count(

                "products",

                filter=Q(

                    products__status=Product.STATUS_APPROVED,

                    products__available=True,

                ),

            )

        )

        .filter(product_count__gt=0)

        .order_by("-product_count", "name")[:4]

    )



    # Add preview image from latest available product in each category

    for category in top_categories:

        preview_product = (

            category.products.publicly_visible().filter(image__isnull=False)

            .exclude(image="")

            .order_by("-created")

            .first()

        )

        category.preview_image = preview_product.image if preview_product else None



    # Latest 4 discounted products

    recent_products = public_products.order_by("-created")

    discount_products = [product for product in recent_products if product.has_discount][:4]



    # Trending/latest products

    products = public_products.order_by("-created")[:8]



    wishlist_products = []

    if request.user.is_authenticated:

        wishlist_products = Wishlist.objects.filter(user=request.user).values_list(

            "product_id", flat=True

        )



    return render(

        request,

        "products/product/home.html",

        {

            "products": products,

            "categories": categories,

            "top_categories": top_categories,

            "discount_products": discount_products,

            "wishlist_products": wishlist_products,

        },

    )


def category_directory(request):

    return render(request, "products/product/categories.html")


def product_list(request, category_slug=None):

    category = None

    products = Product.objects.publicly_visible()

    categories = Category.objects.all()

    selected_category_slug = request.GET.get("category", "").strip()



    query = request.GET.get("q", "").strip()

    min_price = request.GET.get("min_price", "").strip()

    max_price = request.GET.get("max_price", "").strip()

    added_within = request.GET.get("added_within", "").strip()

    sort = request.GET.get("sort", "newest").strip()

    stock_status = request.GET.get("stock_status", "").strip()

    discount_only = request.GET.get("discount_only", "").strip()
    selection_mode = request.GET.get("selection_mode", "").strip()
    checkout_source = request.GET.get("source", "").strip()



    if category_slug:

        category = get_object_or_404(Category, slug=category_slug)

        products = products.filter(category=category)

        selected_category_slug = category.slug

    elif selected_category_slug:

        category = get_object_or_404(Category, slug=selected_category_slug)

        products = products.filter(category=category)



    if query:

        products = products.filter(

            Q(name__icontains=query)

            | Q(description__icontains=query)

            | Q(category__name__icontains=query)

        ).distinct()



    if min_price:

        try:

            products = products.filter(price__gte=Decimal(min_price))

        except InvalidOperation:

            min_price = ""



    if max_price:

        try:

            products = products.filter(price__lte=Decimal(max_price))

        except InvalidOperation:

            max_price = ""



    if stock_status == "in_stock":

        products = products.filter(stock__gt=0)

    elif stock_status == "low_stock":

        products = products.filter(stock__gt=0, stock__lte=10)

    else:

        stock_status = ""



    if discount_only == "1":

        products = products.filter(

            Q(discount_percent__gt=0) | Q(discount_amount__gt=0)

        )

    else:

        discount_only = ""



    if added_within in {"7", "30", "90"}:

        cutoff = timezone.now() - timedelta(days=int(added_within))

        products = products.filter(created__gte=cutoff)

    else:

        added_within = ""



    sort_map = {

        "newest": "-created",

        "price_low_high": "price",

        "price_high_low": "-price",

        "name_a_z": "name",

        "name_z_a": "-name",

    }



    if sort not in sort_map:

        sort = "newest"



    products = products.order_by(sort_map[sort])



    wishlist_products = []

    if request.user.is_authenticated:

        wishlist_products = Wishlist.objects.filter(user=request.user).values_list(

            "product_id", flat=True

        )

        stock_alert_products = StockAlertSubscription.objects.filter(

            user=request.user

        ).values_list("product_id", flat=True)

    else:

        stock_alert_products = []



    restocked_products = _consume_restock_notifications(request)



    return render(
        request,
        "products/product/list.html",
        

        {

            "category": category,

            "selected_category_slug": selected_category_slug,

            "products": products,

            "categories": categories,

            "query": query,

            "min_price": min_price,

            "max_price": max_price,

            "added_within": added_within,

            "sort": sort,

            "stock_status": stock_status,

            "discount_only": discount_only,

            "wishlist_products": wishlist_products,

            "stock_alert_products": stock_alert_products,
            "restocked_products": restocked_products,
            "selection_mode": selection_mode,
            "checkout_source": checkout_source,
        },
    )


@require_POST
def checkout_add_selected_products(request):
    selected_ids = request.POST.getlist("selected_products")
    selection_mode = (request.POST.get("selection_mode") or "").strip()
    source = (request.POST.get("source") or "").strip()

    if selection_mode != "checkout":
        return redirect("products:product_list")

    cart = _get_or_create_session_cart(request)
    request.session["checkout_mode"] = "cart"
    request.session.pop("checkout_cart_id", None)

    added_count = 0
    skipped_variant_count = 0

    for raw_product_id in selected_ids:
        try:
            product_id = int(raw_product_id)
        except (TypeError, ValueError):
            continue

        product = Product.objects.publicly_visible().filter(id=product_id).first()
        if not product:
            continue

        if product.has_variants:
            skipped_variant_count += 1
            continue

        _, error_message = _add_product_to_cart(cart, product)
        if not error_message:
            added_count += 1

    if added_count > 0:
        messages.success(request, f"{added_count} product(s) added to checkout.")
    if skipped_variant_count > 0:
        messages.info(request, f"{skipped_variant_count} product(s) need variant selection from the product detail page.")
    if added_count == 0 and skipped_variant_count == 0:
        messages.info(request, "No extra products were selected.")

    redirect_url = reverse("orders:payment_step")
    if source:
        redirect_url = f"{redirect_url}?source={source}"
    return redirect(redirect_url)



def product_detail(request, id, slug):

    product = get_object_or_404(Product.objects.publicly_visible(), id=id, slug=slug)

    seller_product = getattr(product, "seller_product", None)

    active_variants = list(product.active_variants.order_by("size", "color", "id"))

    available_variants = [variant for variant in active_variants if variant.stock_quantity > 0]

    default_variant = available_variants[0] if available_variants else (active_variants[0] if active_variants else None)

    variant_sizes = sorted({variant.size for variant in active_variants if variant.size})

    variant_colors = sorted({variant.color for variant in active_variants if variant.color})

    variant_data = [

        {

            "id": variant.id,

            "size": variant.size or "",

            "color": variant.color or "",

            "stock_quantity": variant.stock_quantity,

            "in_stock": variant.stock_quantity > 0,

            "label": variant.variant_label,

        }

        for variant in active_variants

    ]



    is_in_wishlist = False

    if request.user.is_authenticated:

        is_in_wishlist = Wishlist.objects.filter(

            user=request.user,

            product=product,

        ).exists()



        has_stock_alert = StockAlertSubscription.objects.filter(

            user=request.user,

            product=product

        ).exists()

    else:

        has_stock_alert = False



    restocked_products = _consume_restock_notifications(request)



    # Similar products: first same category, then latest products fallback

    similar_products = Product.objects.filter(

        category=product.category,

        status=Product.STATUS_APPROVED,

        available=True,

    ).exclude(id=product.id).order_by("-created")[:8]



    if not similar_products.exists():

        similar_products = Product.objects.publicly_visible().exclude(id=product.id).order_by("-created")[:8]



    # Reviews

    from orders.models import Review, ReviewReport



    reviews = Review.objects.filter(product=product, is_flagged=False)

    avg_rating = reviews.aggregate(Avg("rating"))["rating__avg"]

    total_reviews = reviews.count()



    rating_distribution = []

    for star in range(5, 0, -1):

        count = reviews.filter(rating=star).count()

        percentage = int((count / total_reviews * 100) if total_reviews > 0 else 0)

        rating_distribution.append({

            "star": star,

            "count": count,

            "percentage": percentage,

        })



    review_sort = (request.GET.get("review_sort") or "latest").strip()

    verified_only = request.GET.get("verified_only") == "1"



    review_order_map = {

        "latest": "-created_at",

        "highest": "-rating",

    }



    if verified_only:

        reviews = reviews.filter(is_verified_purchase=True)



    visible_reviews = reviews.select_related("user").prefetch_related("images").order_by(

        review_order_map.get(review_sort, "-created_at"),

        "-created_at",

    )[:10]



    user_review_count = 0

    seller_can_report = False

    seller_reported_review_ids = []



    if request.user.is_authenticated:

        user_review_count = Review.objects.filter(

            user=request.user,

            product=product

        ).count()



        seller_profile = getattr(request.user, "seller_profile", None)

        seller_product_rel = getattr(product, "seller_product", None)



        seller_can_report = bool(

            seller_profile

            and seller_profile.is_approved

            and seller_product_rel

            and seller_product_rel.seller_id == seller_profile.id

        )



        if seller_can_report:

            seller_reported_review_ids = list(

                ReviewReport.objects.filter(

                    review__product=product,

                    reported_by=request.user,

                ).values_list("review_id", flat=True)

            )



    return render(

        request,

        "products/product/detail.html",

        {

            "product": product,

            "seller_product": seller_product,

            "is_in_wishlist": is_in_wishlist,

            "has_stock_alert": has_stock_alert,

            "restocked_products": restocked_products,

            "similar_products": similar_products,

            "avg_rating": avg_rating,

            "total_reviews": total_reviews,

            "rating_distribution": rating_distribution,

            "approved_reviews": visible_reviews,

            "user_review_count": user_review_count,

            "review_sort": review_sort if review_sort in review_order_map else "latest",

            "verified_only": verified_only,

            "seller_can_report": seller_can_report,

            "seller_reported_review_ids": seller_reported_review_ids,

            "review_report_reason_choices": ReviewReportForm.REASON_CHOICES,

            "active_variants": active_variants,

            "variant_sizes": variant_sizes,

            "variant_colors": variant_colors,

            "default_variant": default_variant,

            "variant_data": variant_data,

        },

    )





@login_required

@require_POST

def subscribe_stock_alert(request, product_id):

    product = get_object_or_404(Product.objects.publicly_visible(), id=product_id)



    if product.stock < 1 or not product.available:

        subscription, created = StockAlertSubscription.objects.get_or_create(

            user=request.user,

            product=product,

            defaults={"is_notified": False},

        )



        if not created and subscription.is_notified:

            subscription.is_notified = False

            subscription.notified_at = None

            subscription.save(update_fields=["is_notified", "notified_at"])



    return redirect(request.META.get("HTTP_REFERER", "products:product_list"))

