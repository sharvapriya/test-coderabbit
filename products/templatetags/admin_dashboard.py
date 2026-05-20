from decimal import Decimal
from datetime import timedelta

from django import template
from django.core.cache import cache
from django.contrib.auth import get_user_model
from django.db.models import Count, DecimalField, ExpressionWrapper, F, Sum
from django.db.models.functions import Coalesce
from django.utils import timezone

from orders.models import Order, OrderItem
from products.models import Product

register = template.Library()
ADMIN_DASHBOARD_CACHE_TIMEOUT = 300


def _pct_change(current, previous):
    current = Decimal(current or 0)
    previous = Decimal(previous or 0)
    if previous == 0:
        return Decimal("100.0") if current > 0 else Decimal("0.0")
    return ((current - previous) / previous) * Decimal("100.0")


@register.simple_tag
def get_admin_dashboard_metrics():
    cache_key = "admin_dashboard_metrics_v1"
    cached_metrics = cache.get(cache_key)
    if cached_metrics is not None:
        return cached_metrics

    now = timezone.now()
    seven_days_ago = now - timedelta(days=7)
    fourteen_days_ago = now - timedelta(days=14)
    User = get_user_model()

    money_expr = ExpressionWrapper(F("price") * F("quantity"), output_field=DecimalField(max_digits=14, decimal_places=2))

    total_revenue = (
        OrderItem.objects.filter(order__paid=True)
        .aggregate(total=Coalesce(Sum(money_expr), Decimal("0.00")))
        .get("total", Decimal("0.00"))
    )
    revenue_last_7 = (
        OrderItem.objects.filter(order__paid=True, order__created_at__gte=seven_days_ago)
        .aggregate(total=Coalesce(Sum(money_expr), Decimal("0.00")))
        .get("total", Decimal("0.00"))
    )
    revenue_prev_7 = (
        OrderItem.objects.filter(
            order__paid=True,
            order__created_at__gte=fourteen_days_ago,
            order__created_at__lt=seven_days_ago,
        )
        .aggregate(total=Coalesce(Sum(money_expr), Decimal("0.00")))
        .get("total", Decimal("0.00"))
    )

    total_orders = Order.objects.count()
    orders_last_7 = Order.objects.filter(created_at__gte=seven_days_ago).count()
    orders_prev_7 = Order.objects.filter(created_at__gte=fourteen_days_ago, created_at__lt=seven_days_ago).count()

    active_users = User.objects.filter(last_login__isnull=False).count()
    active_last_7 = User.objects.filter(last_login__gte=seven_days_ago).count()
    active_prev_7 = User.objects.filter(last_login__gte=fourteen_days_ago, last_login__lt=seven_days_ago).count()

    signups_week = User.objects.filter(date_joined__gte=seven_days_ago).count()
    signups_prev_week = User.objects.filter(date_joined__gte=fourteen_days_ago, date_joined__lt=seven_days_ago).count()

    metrics = {
        "total_revenue": total_revenue,
        "total_orders": total_orders,
        "active_users": active_users,
        "new_signups_week": signups_week,
        "revenue_change": _pct_change(revenue_last_7, revenue_prev_7),
        "orders_change": _pct_change(orders_last_7, orders_prev_7),
        "active_users_change": _pct_change(active_last_7, active_prev_7),
        "signups_change": _pct_change(signups_week, signups_prev_week),
    }
    cache.set(cache_key, metrics, ADMIN_DASHBOARD_CACHE_TIMEOUT)
    return metrics


@register.simple_tag
def get_top_products_by_revenue(limit=8):
    cache_key = f"admin_dashboard_top_products_{int(limit)}"
    cached_products = cache.get(cache_key)
    if cached_products is not None:
        return cached_products

    money_expr = ExpressionWrapper(F("price") * F("quantity"), output_field=DecimalField(max_digits=14, decimal_places=2))
    products = list(
        OrderItem.objects.filter(order__paid=True)
        .values("product_id", "product__name")
        .annotate(
            orders=Count("order", distinct=True),
            revenue=Coalesce(Sum(money_expr), Decimal("0.00")),
        )
        .order_by("-revenue")[: int(limit)]
    )
    cache.set(cache_key, products, ADMIN_DASHBOARD_CACHE_TIMEOUT)
    return products


@register.simple_tag
def get_products_stock(limit=12):
    cache_key = f"admin_dashboard_products_stock_{int(limit)}"
    cached_stock = cache.get(cache_key)
    if cached_stock is not None:
        return cached_stock

    products = list(
        Product.objects.values("name", "stock", "available", "category__name")
        .order_by("stock", "name")[: int(limit)]
    )
    cache.set(cache_key, products, ADMIN_DASHBOARD_CACHE_TIMEOUT)
    return products
