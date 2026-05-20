from django.conf import settings

import re

from pathlib import Path

from decimal import Decimal, ROUND_HALF_UP


from django.contrib import messages

from django.core.paginator import Paginator

from django.contrib.auth.decorators import login_required

from django.db import transaction

from django.db.models import Q

from django.shortcuts import get_object_or_404, redirect, render

from django.urls import reverse
from django.template.loader import render_to_string

from django.views.decorators.http import require_POST

from django.utils import timezone

from django.utils.crypto import get_random_string

from django.utils.html import strip_tags
from urllib.parse import urlencode


from django.http import JsonResponse
from django.http import HttpResponse

import json

from accounts.models import Address, Profile
from .models import Order

from cart.models import CartItem

from cart.models import Cart

from products.models import Product

from sellers.models import SellerPayout

from .models import ReturnRequest

from .forms import (

    DeliveryAssignmentUpdateForm,

    DiscountApplyForm,

    OrderCreateForm,

    ReturnRequestForm,

    ReviewForm,

    ReviewReportForm,

)

from .models import (

    Coupon,

    DeliveryAssignment,

    Order,

    OrderItem,

    PaymentTransaction,

    ReturnRequest,
    ReturnRequestImage,

    Review,

    ReviewImage,

    ReviewReport,

    Wallet,
    WalletTransaction,
    


)

# from .utils.wallet import get_wallet   

from .services import (

    OrderCancellationError,

    calculate_wallet_usage,

    cancel_order as cancel_order_service,

    cancel_order_item as cancel_order_item_service,

    debit_wallet,

    get_wallet,

)
from .utils.email import handle_order_status_change, order_placed_email, payment_confirmation_email
from django.views.decorators.csrf import csrf_exempt

INVOICE_CITY_ALIASES = [
    ("Ariyalur", ["ariyalur"]),
    ("Chengalpattu", ["chengalpattu"]),
    ("Chennai", ["chennai", "madras"]),
    ("Coimbatore", ["coimbatore", "kovai"]),
    ("Cuddalore", ["cuddalore"]),
    ("Dharmapuri", ["dharmapuri"]),
    ("Dindigul", ["dindigul"]),
    ("Erode", ["erode"]),
    ("Kallakurichi", ["kallakurichi"]),
    ("Kancheepuram", ["kancheepuram", "kanchipuram"]),
    ("Karur", ["karur"]),
    ("Krishnagiri", ["krishnagiri"]),
    ("Madurai", ["madurai"]),
    ("Mayiladuthurai", ["mayiladuthurai"]),
    ("Nagapattinam", ["nagapattinam"]),
    ("Namakkal", ["namakkal"]),
    ("Nilgiris", ["nilgiris", "the nilgiris", "ooty", "udhagamandalam"]),
    ("Perambalur", ["perambalur"]),
    ("Pudukkottai", ["pudukkottai", "pudukottai"]),
    ("Ramanathapuram", ["ramanathapuram"]),
    ("Ranipet", ["ranipet"]),
    ("Salem", ["salem"]),
    ("Sivaganga", ["sivaganga", "sivagangai"]),
    ("Tenkasi", ["tenkasi"]),
    ("Thanjavur", ["thanjavur", "tanjore"]),
    ("Theni", ["theni"]),
    ("Thoothukudi", ["thoothukudi", "tuticorin"]),
    ("Tiruchirappalli", ["tiruchirappalli", "tiruchy", "trichy"]),
    ("Tirunelveli", ["tirunelveli", "nellai"]),
    ("Tirupattur", ["tirupattur"]),
    ("Tiruppur", ["tiruppur", "tirupur"]),
    ("Tiruvallur", ["tiruvallur", "thiruvallur"]),
    ("Tiruvannamalai", ["tiruvannamalai", "thiruvannamalai"]),
    ("Tiruvarur", ["tiruvarur", "thiruvarur"]),
    ("Vellore", ["vellore"]),
    ("Viluppuram", ["viluppuram", "villupuram"]),
    ("Virudhunagar", ["virudhunagar"]),
    ("Kanniyakumari", ["kanniyakumari", "kanyakumari", "nagercoil"]),
]


def _extract_invoice_city(address):
    normalized_address = re.sub(r"[^a-z0-9\s]", " ", (address or "").lower())
    normalized_address = re.sub(r"\s+", " ", normalized_address).strip()
    if not normalized_address:
        return "-"

    for city_name, aliases in INVOICE_CITY_ALIASES:
        for alias in aliases:
            if re.search(rf"\b{re.escape(alias.lower())}\b", normalized_address):
                return city_name

    return "-"

from .services import (

    OrderCancellationError,

    cancel_order as cancel_order_service,

    cancel_order_item as cancel_order_item_service,

)





def _is_local_checkout_request(request):
    host = (request.get_host() or "").split(":", 1)[0].lower()
    return host in {"localhost", "127.0.0.1", "testserver"}




def _delivery_stage_level(status):

    stage_map = {

        SellerPayout.DELIVERY_PENDING: 1,

        SellerPayout.DELIVERY_PACKED: 2,

        SellerPayout.DELIVERY_SHIPPED: 3,

        SellerPayout.DELIVERY_HANDED_TO_HUB: 3,

        SellerPayout.DELIVERY_AT_HUB: 3,

        SellerPayout.DELIVERY_OUT_FOR_DELIVERY: 4,

        SellerPayout.DELIVERY_DELIVERED: 5,

    }

    return stage_map.get(status, 1)


def _normalize_tracking_status(payout=None, delivery_assignment=None, order=None):

    if payout:
        return payout.delivery_status, payout.get_delivery_status_display()

    if delivery_assignment and not payout:
        assignment_map = {
            DeliveryAssignment.STATUS_ASSIGNED: ("pending", "Awaiting Dispatch"),
            DeliveryAssignment.STATUS_PICKED_UP: ("shipped", "Picked up"),
            DeliveryAssignment.STATUS_OUT_FOR_DELIVERY: ("out_for_delivery", "Out for delivery"),
            DeliveryAssignment.STATUS_DELIVERED: ("delivered", "Delivered"),
        }
        if delivery_assignment.status in assignment_map:
            return assignment_map[delivery_assignment.status]

    if order:
        order_status_map = {
            Order.STATUS_PLACED: ("pending", "Order placed"),
            Order.STATUS_CONFIRMED: ("pending", "Awaiting Dispatch"),
            Order.STATUS_PACKED: ("packed", "Packed"),
            Order.STATUS_SHIPPED: ("shipped", "Shipped"),
            Order.STATUS_OUT_FOR_DELIVERY: ("out_for_delivery", "Out for delivery"),
            Order.STATUS_DELIVERED: ("delivered", "Delivered"),
        }
        resolved_status = order.resolve_fulfillment_status()
        if resolved_status in order_status_map:
            return order_status_map[resolved_status]

    return "pending", "Awaiting Dispatch"




def _calculate_discount_amount(subtotal, percent):

    raw_discount = (subtotal * Decimal(percent)) / Decimal("100")

    return raw_discount.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)




def _item_unit_price(item):

    return item.product.discounted_price_with_gst


def _item_taxable_unit_price(item):

    return item.product.discounted_price




def _coupon_applicable_subtotal(cart_items, subtotal, coupon):

    if coupon.product_id:

        applicable_total = sum(

            _item_unit_price(item) * item.quantity

            for item in cart_items

            if item.product_id == coupon.product_id

        )

    elif coupon.seller_id:

        applicable_total = sum(

            _item_unit_price(item) * item.quantity

            for item in cart_items

            if getattr(getattr(item.product, "seller_product", None), "seller_id", None) == coupon.seller_id

        )

    else:

        applicable_total = subtotal

    if (coupon.minimum_purchase_amount or Decimal("0")) > applicable_total:

        return Decimal("0")

    return applicable_total


def _has_user_used_coupon(user, coupon_code):
    if not getattr(user, "is_authenticated", False) or not coupon_code:
        return False
    return Order.objects.filter(user=user, coupon_code__iexact=coupon_code).exists()


def _get_checkout_offers(cart_items, subtotal, user=None):

    cart_product_ids = {item.product_id for item in cart_items}
    cart_seller_ids = {
        getattr(getattr(item.product, "seller_product", None), "seller_id", None)
        for item in cart_items
    }
    cart_seller_ids.discard(None)

    offers = []
    seen_coupon_ids = set()

    coupons = Coupon.objects.filter(active=True).select_related("seller", "product").order_by("-discount_percent", "code")

    for coupon in coupons:

        if coupon.id in seen_coupon_ids or not coupon.is_valid_now():

            continue

        applicable_subtotal = _coupon_applicable_subtotal(cart_items, subtotal, coupon)
        is_relevant = True
        matching_total = subtotal

        if coupon.product_id and coupon.product_id not in cart_product_ids:

            is_relevant = False
            applicable_subtotal = Decimal("0")

        if coupon.seller_id and coupon.seller_id not in cart_seller_ids:

            is_relevant = False
            applicable_subtotal = Decimal("0")

        minimum_purchase_amount = coupon.minimum_purchase_amount or Decimal("0")
        shortfall_amount = Decimal("0")
        already_used = _has_user_used_coupon(user, coupon.code)
        if coupon.product_id:
            matching_total = sum(
                _item_unit_price(item) * item.quantity
                for item in cart_items
                if item.product_id == coupon.product_id
            )
        elif coupon.seller_id:
            matching_total = sum(
                _item_unit_price(item) * item.quantity
                for item in cart_items
                if getattr(getattr(item.product, "seller_product", None), "seller_id", None) == coupon.seller_id
            )

        if applicable_subtotal <= 0:
            is_relevant = False
            if minimum_purchase_amount > 0:
                shortfall_amount = max(minimum_purchase_amount - matching_total, Decimal("0"))

        if already_used:
            is_relevant = False

        estimated_savings = _calculate_discount_amount(applicable_subtotal, coupon.discount_percent)

        if coupon.product_id and coupon.product:

            applies_to = coupon.product.name
            unlock_params = {
                "selection_mode": "checkout",
                "source": "cart",
                "category": coupon.product.category.slug if coupon.product.category_id else "",
                "q": coupon.product.name,
            }
            unlock_url = f"{reverse('products:product_list')}?{urlencode({k: v for k, v in unlock_params.items() if v})}"

        elif coupon.seller_id and coupon.seller:

            applies_to = f"{coupon.seller.business_name} products"
            unlock_url = f"{reverse('products:product_list')}?{urlencode({'selection_mode': 'checkout', 'source': 'cart'})}"

        else:

            applies_to = "your entire cart"
            unlock_url = f"{reverse('products:product_list')}?{urlencode({'selection_mode': 'checkout', 'source': 'cart'})}"

        offers.append(
            {
                "offer_type": "coupon",
                "code": coupon.code,
                "discount_percent": coupon.discount_percent,
                "estimated_savings": estimated_savings,
                "applies_to": applies_to,
                "source_label": "Seller Offer" if coupon.seller_id else "Admin Offer",
                "source_name": coupon.seller.business_name if coupon.seller_id and coupon.seller else "MyKart Store",
                "is_relevant": is_relevant,
                "already_used": already_used,
                "matching_total": matching_total,
                "minimum_purchase_amount": minimum_purchase_amount,
                "shortfall_amount": shortfall_amount,
                "unlock_url": unlock_url,
            }
        )

        seen_coupon_ids.add(coupon.id)

    offers.sort(key=lambda offer: (not offer["is_relevant"], -offer["discount_percent"], offer["code"]))

    return offers[:10]




def _resolve_session_discount(request, cart_items, subtotal):

    discount_data = request.session.get("checkout_discount")

    if not discount_data:

        return ("", Decimal("0"), Decimal("0"))


    code = (discount_data.get("code") or "").strip().upper()

    if not code:

        request.session.pop("checkout_discount", None)

        return ("", Decimal("0"), Decimal("0"))


    coupon = Coupon.objects.filter(code__iexact=code).first()

    if not coupon or not coupon.is_valid_now():

        request.session.pop("checkout_discount", None)

        return ("", Decimal("0"), Decimal("0"))

    if _has_user_used_coupon(request.user, coupon.code):

        request.session.pop("checkout_discount", None)

        return ("", Decimal("0"), Decimal("0"))


    applicable_subtotal = _coupon_applicable_subtotal(cart_items, subtotal, coupon)

    if applicable_subtotal <= 0:

        request.session.pop("checkout_discount", None)

        return ("", Decimal("0"), Decimal("0"))


    discount_amount = _calculate_discount_amount(

        applicable_subtotal,

        coupon.discount_percent,

    )

    request.session["checkout_discount"] = {

        "code": coupon.code,

        "percent": coupon.discount_percent,

        "amount": str(discount_amount),

    }

    return (coupon.code, Decimal(coupon.discount_percent), discount_amount)





def _get_checkout_use_wallet(request):

    stored = request.session.get("checkout_use_wallet")
    if stored is None:
        return False
    return bool(stored)


def _get_selected_payment_method(request):
    stored = (request.session.get("checkout_payment_method") or "").strip()
    if stored in {Order.PAYMENT_ONLINE, Order.PAYMENT_WALLET}:
        return stored
    return Order.PAYMENT_ONLINE



def _get_checkout_cart_or_redirect(request):
    source = (request.GET.get("source") or request.POST.get("source") or "").strip().lower()
    if source == "cart":
        request.session.pop("checkout_cart_id", None)
        request.session["checkout_mode"] = "cart"

    checkout_mode = request.session.get("checkout_mode")
    checkout_cart_id = request.session.get("checkout_cart_id")
    default_cart_id = request.session.get("cart_id")

    if checkout_mode == "buy_now" and checkout_cart_id:
        cart_id = checkout_cart_id
    else:
        cart_id = default_cart_id or checkout_cart_id

    if not cart_id:
        return None

    try:
        cart = Cart.objects.get(id=cart_id)
    except Cart.DoesNotExist:
        if cart_id == checkout_cart_id:
            request.session.pop("checkout_cart_id", None)
            request.session.pop("checkout_mode", None)
        else:
            request.session.pop("cart_id", None)
        return None

    if not cart.items.exists():
        if cart_id == checkout_cart_id:
            request.session.pop("checkout_cart_id", None)
            request.session.pop("checkout_mode", None)
        return None

    return cart

def _build_checkout_context(request, cart_items, payment_method=None):

    subtotal = sum(_item_unit_price(item) * item.quantity for item in cart_items)
    available_offers = _get_checkout_offers(cart_items, subtotal, getattr(request, "user", None))
    coupon_code, discount_percent, discount_amount = _resolve_session_discount(request, cart_items, subtotal)
    final_total = subtotal - discount_amount
    if final_total < 0:
        final_total = Decimal("0")

    # wallet = get_wallet(request.user) if request.user.is_authenticated else None
    # wallet_balance = wallet.balance if wallet else Decimal("0")
    # use_wallet = _get_checkout_use_wallet(request)
    # wallet_eligible = wallet_balance >= final_total and final_total > 0
    # if use_wallet and wallet_eligible:
    #     wallet_applied, remaining_payable = calculate_wallet_usage(
    #         total_amount=final_total,
    #         wallet_balance=wallet_balance,
    #         use_wallet=use_wallet,
    #     )
    # else:
    #     wallet_applied = Decimal("0")
    #     remaining_payable = final_total

    wallet = get_wallet(request.user) if request.user.is_authenticated else None
    wallet_balance = wallet.balance if wallet else Decimal("0")
    wallet_has_funds = wallet_balance > 0 and final_total > 0

    # use_wallet = _get_checkout_use_wallet(request)
    use_wallet = _get_checkout_use_wallet(request) and wallet_has_funds

    # wallet fully covers order
    wallet_eligible = wallet_balance >= final_total and final_total > 0

    # APPLY PARTIAL WALLET ALSO
    if use_wallet and wallet_balance > 0:
        wallet_applied = min(wallet_balance, final_total)
        remaining_payable = final_total - wallet_applied
    else:
        wallet_applied = Decimal("0")
        remaining_payable = final_total

    selected_payment_method = payment_method or _get_selected_payment_method(request)
    if wallet_applied > 0 and remaining_payable == 0:
        effective_payment_method = Order.PAYMENT_WALLET
    elif use_wallet and not wallet_eligible:
        effective_payment_method = Order.PAYMENT_ONLINE
    else:
        effective_payment_method = selected_payment_method

    return {
        "subtotal": subtotal,
        "available_offers": available_offers,
        "coupon_code": coupon_code,
        "discount_percent": discount_percent,
        "discount_amount": discount_amount,
        "final_total": final_total,
        "wallet": wallet,
        "wallet_balance": wallet_balance,
        "wallet_has_funds": wallet_has_funds,
        "wallet_eligible": wallet_eligible,
        "use_wallet": use_wallet,
        "wallet_applied": wallet_applied,
        "remaining_payable": remaining_payable,
        "selected_payment_method": selected_payment_method,
        "effective_payment_method": effective_payment_method,
        "wallet_only": wallet_applied > 0 and remaining_payable == 0,
        # "wallet_requires_online": use_wallet and not wallet_eligible and remaining_payable > 0,
        "wallet_requires_online": wallet_applied > 0 and remaining_payable > 0,
    }




def _get_saved_checkout_details(user):
    if not getattr(user, "is_authenticated", False):
        return {}

    default_address = (
        Address.objects.filter(user=user)
        .order_by("-is_default", "-created_at")
        .only("label", "address_line", "city", "state", "country", "pincode", "is_default")
        .first()
    )

    profile = Profile.objects.filter(user=user).first()
    if default_address:
        address_details = {
            "full_name": (
                (profile.full_name or "").strip()
                if profile
                else (getattr(user, "get_full_name", lambda: "")() or "").strip()
            )
            or (getattr(user, "get_full_name", lambda: "")() or "").strip()
            or getattr(user, "username", ""),
            "email": (getattr(user, "email", "") or "").strip(),
            "phone_number": ((profile.phone_number or "").strip() if profile else ""),
            "address": (default_address.address_line or "").strip(),
            "city": (default_address.city or "").strip(),
            "state": (default_address.state or "").strip(),
            "pincode": (default_address.pincode or "").strip(),
            "country": (default_address.country or "").strip(),
        }
        return {key: value for key, value in address_details.items() if value}

    if profile:
        profile_details = {}
        full_name = (profile.full_name or "").strip() or (getattr(user, "get_full_name", lambda: "")() or "").strip()
        email = (getattr(user, "email", "") or "").strip()
        phone_number = (profile.phone_number or "").strip()
        address = profile.address_line
        city = (profile.city or "").strip()
        state = (profile.state or "").strip()
        pincode = (profile.pincode or "").strip()
        country = (profile.country or "").strip()
        
        if full_name:
            profile_details["full_name"] = full_name
        if email:
            profile_details["email"] = email
        if phone_number:
            profile_details["phone_number"] = phone_number
        if address:
            profile_details["address"] = address
        if city:
            profile_details["city"] = city
        if state:
            profile_details["state"] = state
        if pincode:
            profile_details["pincode"] = pincode
        if country:
            profile_details["country"] = country
        if profile_details:
            return profile_details


    latest_order = (
        Order.objects.filter(user=user)
        .exclude(full_name="")
        .exclude(email="")
        .exclude(phone_number="")
        .exclude(address="")
        .order_by("-created_at")
        .only("full_name", "email", "phone_number", "address", "city", "state", "pincode", "country")
        .first()
    )

    full_name = ""
    if latest_order and (latest_order.full_name or "").strip():
        full_name = latest_order.full_name.strip()
    else:
        full_name = (getattr(user, "get_full_name", lambda: "")() or "").strip() or getattr(user, "username", "")

    email = ""
    if latest_order and (latest_order.email or "").strip():
        email = latest_order.email.strip()
    else:
        email = (getattr(user, "email", "") or "").strip()

    phone_number = ""
    if latest_order and (latest_order.phone_number or "").strip():
        phone_number = latest_order.phone_number.strip()

    address = ""
    if latest_order and (latest_order.address or "").strip():
        address = latest_order.address.strip()

    city = ""
    if latest_order and (latest_order.city or "").strip():
        city = latest_order.city.strip()

    state = ""
    if latest_order and (latest_order.state or "").strip():
        state = latest_order.state.strip()

    pincode = ""
    if latest_order and (latest_order.pincode or "").strip():
        pincode = latest_order.pincode.strip()

    country = ""
    if latest_order and (latest_order.country or "").strip():
        country = latest_order.country.strip()

    initial = {}
    if full_name:
        initial["full_name"] = full_name
    if email:
        initial["email"] = email
    if phone_number:
        initial["phone_number"] = phone_number
    if address:
        initial["address"] = address
    if city:
        initial["city"] = city
    if state:
        initial["state"] = state
    if pincode:
        initial["pincode"] = pincode
    if country:
        initial["country"] = country
    return initial
    
    

def _create_order_with_items(
    user,
    form,
    coupon_code,
    discount_amount,
    final_total,
    payment_method,
    cart_items,
    wallet_amount_used=0,
    gateway_amount_paid=0,
):
    
    order = form.save(commit=False)

    order.user = user

    order.coupon_code = coupon_code

    order.discount_amount = discount_amount

    order.total_amount = final_total

    order.payment_method = payment_method
    order.wallet_amount_used = wallet_amount_used
    order.gateway_amount_paid = gateway_amount_paid

    order.status = Order.STATUS_PLACED

    order.save()

    # Save address details to user's profile if new values are provided
    if user.is_authenticated:
        profile, created = Profile.objects.get_or_create(user=user)
        
        # Update profile with checkout details
        if form.cleaned_data.get('full_name'):
            profile.full_name = form.cleaned_data['full_name']
        if form.cleaned_data.get('phone_number'):
            profile.phone_number = form.cleaned_data['phone_number']
        if form.cleaned_data.get('address'):
            profile.address_line = form.cleaned_data['address']
        if form.cleaned_data.get('city'):
            profile.city = form.cleaned_data['city']
        if form.cleaned_data.get('state'):
            profile.state = form.cleaned_data['state']
        if form.cleaned_data.get('pincode'):
            profile.pincode = form.cleaned_data['pincode']
        if form.cleaned_data.get('country'):
            profile.country = form.cleaned_data['country']
        
        profile.save()

    for item in cart_items:

        OrderItem.objects.create(

            order=order,

            product=item.product,

            variant=item.variant,

            price=_item_taxable_unit_price(item),

            gst_rate=item.product.effective_gst_rate,

            gst_amount=item.product.gst_amount_for_price(_item_taxable_unit_price(item)),

            quantity=item.quantity,

        )

    return order



def _has_stock_issue(cart_items):

    return any(item.stock_available < item.quantity for item in cart_items)
    
def _deduct_stock(cart_items):

    for item in cart_items:
        if item.variant_id:
            item.variant.stock_quantity -= item.quantity
            item.variant.save(update_fields=["stock_quantity", "updated_at"])
            if item.product.effective_stock == 0:
                item.product.available = False
                item.product.save(update_fields=["available"])
            continue

        item.product.stock -= item.quantity
        if item.product.stock == 0:
            item.product.available = False
        item.product.save(update_fields=["stock", "available"])




def _is_delivery_agent(user):

    return user.is_authenticated and (

        user.is_staff or user.groups.filter(name__iexact="Delivery").exists()

    )




def _sync_cod_payment_state(order, assignment):

    if order.payment_method != Order.PAYMENT_COD:

        return


    txn, _ = PaymentTransaction.objects.get_or_create(

        order=order,

        payment_method=Order.PAYMENT_COD,

        gateway=PaymentTransaction.GATEWAY_COD,

        defaults={

            "user": order.user,

            "status": PaymentTransaction.STATUS_INITIATED,

            "amount": order.get_total_cost(),

            "raw_response": {"source": "delivery_module", "result": "pending_collection"},

        },

    )


    if assignment.cod_payment_status == DeliveryAssignment.COD_COLLECTED:

        if not order.paid:

            order.paid = True

            order.save(update_fields=["paid", "updated_at"])

        txn.status = PaymentTransaction.STATUS_SUCCESS

        txn.failure_reason = ""

        txn.gateway_payment_id = txn.gateway_payment_id or f"CODCOLLECT-{order.id}"

        txn.raw_response = {

            "source": "delivery_module",

            "result": "collected",

        }

        txn.save(

            update_fields=[

                "status",

                "failure_reason",

                "gateway_payment_id",

                "raw_response",

                "updated_at",

            ]

        )

        return


    if order.paid:

        order.paid = False

        order.save(update_fields=["paid", "updated_at"])


    if assignment.cod_payment_status == DeliveryAssignment.COD_COLLECTION_FAILED:

        txn.status = PaymentTransaction.STATUS_FAILED

        txn.failure_reason = "Delivery marked complete but COD collection failed."

        txn.raw_response = {

            "source": "delivery_module",

            "result": "collection_failed",

        }

    else:

        txn.status = PaymentTransaction.STATUS_INITIATED

        txn.failure_reason = ""

        txn.raw_response = {

            "source": "delivery_module",

            "result": "pending_collection",

        }

    txn.save(update_fields=["status", "failure_reason", "raw_response", "updated_at"])




def _request_expects_json(request):

    accepted = request.headers.get("Accept", "")

    requested_with = request.headers.get("X-Requested-With", "")

    return "application/json" in accepted or requested_with == "XMLHttpRequest"




def _extract_cancellation_reason(request):

    reason = (request.POST.get("reason") or "").strip()

    if reason:

        return reason

    if "application/json" in (request.headers.get("Content-Type", "") or ""):

        try:

            payload = json.loads(request.body or "{}")

        except json.JSONDecodeError:

            return ""

        return (payload.get("reason") or "").strip()

    return ""


def _extract_cancellation_quantity(request):
    raw_quantity = (request.POST.get("cancel_quantity") or "").strip()
    if not raw_quantity:
        return None
    try:
        quantity = int(raw_quantity)
    except (TypeError, ValueError):
        return None
    return quantity if quantity > 0 else None






def _sync_order_status_from_delivery(order, assignment=None, send_notification=False):

    if order.status in {Order.STATUS_CANCELLED, Order.STATUS_PARTIALLY_CANCELLED}:

        return

    assignment = assignment or DeliveryAssignment.objects.filter(order=order).first()

    if not assignment:

        return

    if assignment.status == DeliveryAssignment.STATUS_ASSIGNED:

        order.status = Order.STATUS_CONFIRMED

    elif assignment.status == DeliveryAssignment.STATUS_PICKED_UP:

        order.status = Order.STATUS_SHIPPED

    elif assignment.status == DeliveryAssignment.STATUS_OUT_FOR_DELIVERY:

        order.status = Order.STATUS_OUT_FOR_DELIVERY

    elif assignment.status == DeliveryAssignment.STATUS_DELIVERED:

        order.status = Order.STATUS_DELIVERED
    
    order._skip_status_email_signal = True
    order.save(update_fields=["status", "updated_at"])
    if send_notification:
        handle_order_status_change(order)





def _return_item_is_delivered(order, item):
    try:
        assignment = order.delivery_assignment
    except Exception:
        assignment = None

    if assignment and assignment.status == DeliveryAssignment.STATUS_DELIVERED:
        return True

    try:
        payout = item.seller_payout
        return payout and payout.delivery_status == SellerPayout.DELIVERY_DELIVERED
    except Exception:
        return False


def _validate_return_photos(photos):
    errors = []
    allowed_extensions = {".jpg", ".jpeg", ".png", ".gif", ".webp"}

    if len(photos) < 1:
        errors.append("Upload at least 1 screenshot or photo for each selected product.")
    if len(photos) > 5:
        errors.append("Upload a maximum of 5 screenshots or photos for each selected product.")

    for photo in photos:
        ext = Path(photo.name).suffix.lower()
        if ext not in allowed_extensions:
            errors.append("Only JPG, JPEG, PNG, GIF, or WEBP images are allowed.")
            break
        if photo.size > 5 * 1024 * 1024:
            errors.append(f"Image '{photo.name}' is too large. Maximum file size is 5MB.")

    return errors


def _build_return_items(order, selected_product_ids=None, posted_data=None):
    selected_product_ids = set(selected_product_ids or [])
    existing_product_ids = set(
        ReturnRequest.objects.filter(order=order)
        .exclude(status=ReturnRequest.STATUS_WITHDRAWN)
        .values_list("product_id", flat=True)
    )
    active_items = list(
        order.items.exclude(status=OrderItem.STATUS_CANCELLED)
        .select_related("product", "variant", "seller_payout")
        .order_by("id")
    )
    delivered_items = [
        item for item in active_items if _return_item_is_delivered(order, item)
    ]
    available_count = sum(
        1 for item in delivered_items if item.product_id not in existing_product_ids
    )
    eligible_items = []

    for item in delivered_items:
        product_id = item.product_id
        has_existing = product_id in existing_product_ids
        is_selected = product_id in selected_product_ids
        if posted_data is None and not has_existing:
            is_selected = available_count == 1

        item.has_existing_return_request = has_existing
        item.return_refund_amount = item.price * item.quantity
        item.is_selected_for_return = is_selected
        item.selected_return_reason = (
            posted_data.get(f"reason_{product_id}", "") if posted_data is not None else ""
        )
        item.selected_other_reason = (
            posted_data.get(f"other_reason_{product_id}", "") if posted_data is not None else ""
        )
        eligible_items.append(item)

    return eligible_items


@login_required

def discount_step(request):
    cart = _get_checkout_cart_or_redirect(request)

    if not cart:
        return redirect("cart:cart_detail")


    cart_items = list(cart.items.select_related("product", "variant"))

    subtotal = sum(_item_unit_price(item) * item.quantity for item in cart_items)
    available_offers = _get_checkout_offers(cart_items, subtotal, request.user)

    selected_code, selected_percent, selected_discount = _resolve_session_discount(

        request,

        cart_items,

        subtotal,

    )

    form = DiscountApplyForm(initial={"code": selected_code} if selected_code else None)

    requested_code = (request.GET.get("code") or "").strip().upper()

    if request.method == "GET" and requested_code:

        coupon = Coupon.objects.filter(code__iexact=requested_code).first()

        if not coupon or not coupon.is_valid_now():

            form = DiscountApplyForm({"code": requested_code})
            form.add_error("code", "Invalid or expired discount code.")
            request.session.pop("checkout_discount", None)
            selected_code = ""
            selected_percent = Decimal("0")
            selected_discount = Decimal("0")

        elif _has_user_used_coupon(request.user, coupon.code):

            form = DiscountApplyForm({"code": requested_code})
            form.add_error("code", "Already this coupon accessed.")
            request.session.pop("checkout_discount", None)
            selected_code = ""
            selected_percent = Decimal("0")
            selected_discount = Decimal("0")

        else:
            applicable_subtotal = _coupon_applicable_subtotal(cart_items, subtotal, coupon)

            if applicable_subtotal <= 0:

                form = DiscountApplyForm({"code": requested_code})
                form.add_error("code", "This coupon is not eligible for the current cart yet.")
                request.session.pop("checkout_discount", None)
                selected_code = ""
                selected_percent = Decimal("0")
                selected_discount = Decimal("0")

            else:

                selected_discount = _calculate_discount_amount(

                    applicable_subtotal,

                    coupon.discount_percent,

                )

                request.session["checkout_discount"] = {

                    "code": coupon.code,

                    "percent": coupon.discount_percent,

                    "amount": str(selected_discount),

                }

                messages.success(request, f"Coupon {coupon.code} applied successfully.")

                return redirect("orders:payment_step")


    if request.method == "POST":

        form = DiscountApplyForm(request.POST)

        if form.is_valid():

            code = form.cleaned_data["code"]

            coupon = Coupon.objects.filter(code__iexact=code).first()

            if not coupon or not coupon.is_valid_now():

                form.add_error("code", "Invalid or expired discount code.")

                request.session.pop("checkout_discount", None)

                selected_code = ""

                selected_percent = Decimal("0")

                selected_discount = Decimal("0")

            elif _has_user_used_coupon(request.user, coupon.code):

                form.add_error("code", "Already this coupon accessed.")

                request.session.pop("checkout_discount", None)

                selected_code = ""

                selected_percent = Decimal("0")

                selected_discount = Decimal("0")

            else:

                applicable_subtotal = _coupon_applicable_subtotal(cart_items, subtotal, coupon)

                if applicable_subtotal <= 0:

                    form.add_error("code", "This code does not apply to items in your cart.")

                    request.session.pop("checkout_discount", None)

                    selected_code = ""

                    selected_percent = Decimal("0")

                    selected_discount = Decimal("0")

                else:

                    selected_discount = _calculate_discount_amount(

                        applicable_subtotal,

                        coupon.discount_percent,

                    )

                    selected_percent = Decimal(coupon.discount_percent)

                    selected_code = coupon.code

                    request.session["checkout_discount"] = {

                        "code": coupon.code,

                        "percent": coupon.discount_percent,

                        "amount": str(selected_discount),

                    }

                    return redirect("orders:payment_step")

    final_total = subtotal - selected_discount

    if final_total < 0:

        final_total = Decimal("0")


    return render(

        request,

        "orders/discount_step.html",

        {

            "cart": cart,

            "form": form,

            "subtotal": subtotal,

            "selected_code": selected_code,

            "selected_percent": selected_percent,

            "discount_amount": selected_discount,

            "final_total": final_total,

            "available_offers": available_offers,

        },

    )




@login_required

def order_create(request):

    cart = _get_checkout_cart_or_redirect(request)

    if not cart:
        return redirect("cart:cart_detail")

    selected_payment_method = _get_selected_payment_method(request)
    cart_items = list(cart.items.select_related("product", "variant"))
    checkout = _build_checkout_context(request, cart_items, payment_method=selected_payment_method)

    if request.method == "POST":
        form = OrderCreateForm(request.POST)
        if form.is_valid():
            try:
                with transaction.atomic():
                    locked_cart_items = list(cart.items.select_related("product", "variant").select_for_update())
                    if _has_stock_issue(locked_cart_items):
                        messages.error(request, "One or more items are out of stock. Please review your cart.")
                        return redirect("cart:cart_detail")

                    checkout = _build_checkout_context(request, locked_cart_items, payment_method=selected_payment_method)
                    effective_payment_method = checkout["effective_payment_method"]
                    wallet_applied = checkout["wallet_applied"]
                    remaining_payable = checkout["remaining_payable"]

                    if effective_payment_method == Order.PAYMENT_ONLINE and remaining_payable > 0 and not request.session.get("online_payment_confirmed", False):
                        messages.error(request, "Please complete the online payment first.")
                        return redirect("orders:payment_online")

                    order = _create_order_with_items(
                        user=request.user,
                        form=form,
                        coupon_code=checkout["coupon_code"],
                        discount_amount=checkout["discount_amount"],
                        final_total=checkout["final_total"],
                        payment_method=effective_payment_method,
                        cart_items=locked_cart_items,
                        wallet_amount_used=wallet_applied,
                        gateway_amount_paid=remaining_payable,
                    )

                    if wallet_applied > 0:
                        debit_wallet(
                            user=request.user,
                            amount=wallet_applied,
                            source=WalletTransaction.SOURCE_ORDER_PAYMENT,
                            description=f"Used for Order #{order.id}",
                            order=order,
                            metadata={"order_id": order.id},
                        )
                        PaymentTransaction.objects.create(
                            order=order,
                            user=request.user,
                            payment_method=Order.PAYMENT_WALLET,
                            gateway=PaymentTransaction.GATEWAY_WALLET,
                            status=PaymentTransaction.STATUS_SUCCESS,
                            amount=wallet_applied,
                            gateway_payment_id=f"WALLET-{order.id}",
                            raw_response={"source": "wallet_checkout", "result": "success"},
                        )

                    _deduct_stock(locked_cart_items)

                    if effective_payment_method == Order.PAYMENT_COD:
                        PaymentTransaction.objects.create(
                            order=order,
                            user=request.user,
                            payment_method=Order.PAYMENT_COD,
                            gateway=PaymentTransaction.GATEWAY_COD,
                            status=PaymentTransaction.STATUS_INITIATED,
                            amount=order.get_total_cost(),
                            gateway_payment_id=f"COD-{order.id}",
                            raw_response={"source": "cod_checkout", "result": "pending_collection"},
                        )
                        assignment = DeliveryAssignment.objects.create(
                            order=order,
                            status=DeliveryAssignment.STATUS_ASSIGNED,
                            cod_payment_status=DeliveryAssignment.COD_PENDING,
                        )
                    elif effective_payment_method == Order.PAYMENT_WALLET:
                        order.paid = True
                        order.save(update_fields=["paid", "updated_at"])
                        assignment = DeliveryAssignment.objects.create(
                            order=order,
                            status=DeliveryAssignment.STATUS_ASSIGNED,
                            cod_payment_status=DeliveryAssignment.COD_NOT_APPLICABLE,
                        )
                        transaction.on_commit(lambda: payment_confirmation_email(request.user, order))
                    else:
                        payment_txn_id = request.session.get("razorpay_transaction_id")
                        if payment_txn_id:
                            PaymentTransaction.objects.filter(id=payment_txn_id).update(
                                order=order,
                                amount=remaining_payable,
                                raw_response={"source": "razorpay", "result": "success", "wallet_used": str(wallet_applied)},
                            )
                        else:
                            PaymentTransaction.objects.create(
                                order=order,
                                user=request.user,
                                payment_method=Order.PAYMENT_ONLINE,
                                gateway=PaymentTransaction.GATEWAY_RAZORPAY,
                                status=PaymentTransaction.STATUS_SUCCESS,
                                amount=remaining_payable,
                                gateway_order_id=request.session.get("razorpay_order_id", ""),
                                gateway_payment_id=request.session.get("razorpay_payment_id", ""),
                                gateway_signature=request.session.get("razorpay_signature", ""),
                                raw_response={"source": "razorpay", "result": "success", "wallet_used": str(wallet_applied)},
                            )
                        order.paid = True
                        order.save(update_fields=["paid", "updated_at"])
                        assignment = DeliveryAssignment.objects.create(
                            order=order,
                            status=DeliveryAssignment.STATUS_ASSIGNED,
                            cod_payment_status=DeliveryAssignment.COD_NOT_APPLICABLE,
                        )
                        transaction.on_commit(lambda: payment_confirmation_email(request.user, order))

                    _sync_order_status_from_delivery(order, assignment)
                    transaction.on_commit(lambda: order_placed_email(request.user, order))

                    cart.delete()
                    request.session.pop("cart_id", None)
                    request.session.pop("checkout_discount", None)
                    request.session.pop("checkout_payment_method", None)
                    request.session.pop("checkout_use_wallet", None)
                    request.session.pop("online_payment_confirmed", None)
                    request.session.pop("razorpay_order_id", None)
                    request.session.pop("razorpay_payment_id", None)
                    request.session.pop("razorpay_signature", None)
                    request.session.pop("razorpay_transaction_id", None)
                    request.session.pop("razorpay_amount", None)
                    request.session.pop("razorpay_amount_paise", None)

                    return redirect("orders:order_confirmation", order.id)
            except OrderCancellationError as exc:
                messages.error(request, exc.message)
                return redirect("orders:payment_step")
    else:
        saved_checkout_details = _get_saved_checkout_details(request.user)
        form = OrderCreateForm(initial=saved_checkout_details)
        # form = OrderCreateForm()

    return render(
        request,
        "orders/order_create.html",
        {
            "cart": cart,
            "form": form,
            "saved_checkout_details": saved_checkout_details if request.method != "POST" else {},
            "payment_method": checkout["effective_payment_method"],
            **checkout,
        },
    )




@login_required

def order_confirmation(request, order_id):

    order = get_object_or_404(Order.objects.prefetch_related("payment_transactions"), id=order_id, user=request.user)

    return render(request, "orders/order_confirmation.html", {"order": order})

def _format_invoice_number(order):
    issued_on = timezone.localtime(order.created_at) if order.created_at else timezone.localtime(timezone.now())
    date_block = issued_on.strftime("%Y%m%d")
    return f"TAX-INV-{date_block}-{order.id:06d}"


def _build_invoice_context(order, buyer_phone):
    order_items = list(order.items.all())
    invoice_line_items = []
    money_precision = Decimal("0.01")
    gst_rate_labels = []

    for item in order_items:
        line_total = item.get_cost().quantize(money_precision)
        gst_rate = (item.gst_rate or Decimal("0")).quantize(money_precision)
        if gst_rate > 0:
            line_gst = ((line_total * gst_rate) / Decimal("100")).quantize(money_precision)
        else:
            line_gst = Decimal("0.00")
        line_taxable = (line_total - line_gst).quantize(money_precision)
        if line_taxable < 0:
            line_taxable = Decimal("0.00")
        rate_label = f"{gst_rate.normalize()}%"
        if gst_rate > 0 and rate_label not in gst_rate_labels:
            gst_rate_labels.append(rate_label)
        invoice_line_items.append(
            {
                "item": item,
                "line_total": line_total,
                "line_gst": line_gst,
                "line_taxable": line_taxable,
            }
        )

    seller_profiles = []
    seen_seller_ids = set()
    for item in order_items:
        seller_product = getattr(item.product, "seller_product", None)
        seller = getattr(seller_product, "seller", None)
        if seller and seller.id not in seen_seller_ids:
            seller_profiles.append(seller)
            seen_seller_ids.add(seller.id)

    items_total = sum((line["line_total"] for line in invoice_line_items), Decimal("0")).quantize(Decimal("0.01"))
    gst_amount = sum((line["line_gst"] for line in invoice_line_items), Decimal("0")).quantize(Decimal("0.01"))
    taxable_subtotal = sum((line["line_taxable"] for line in invoice_line_items), Decimal("0")).quantize(Decimal("0.01"))

    discount_amount = (order.discount_amount or Decimal("0")).quantize(Decimal("0.01"))
    shipping_amount = (
        order.delivery_charge
        or order.shipping_charge
        or Decimal("0")
    ).quantize(Decimal("0.01"))
    computed_total = (items_total - discount_amount + shipping_amount).quantize(Decimal("0.01"))
    stored_total = (order.total_amount or Decimal("0")).quantize(Decimal("0.01"))
    grand_total = stored_total if stored_total > 0 else computed_total

    adjustment_amount = (grand_total - computed_total).quantize(Decimal("0.01"))
    if adjustment_amount == Decimal("0.00"):
        adjustment_amount = None

    successful_transactions = list(
        order.payment_transactions.filter(status=PaymentTransaction.STATUS_SUCCESS)
    )
    primary_transaction = next(
        (
            txn for txn in successful_transactions
            if txn.gateway_payment_id or txn.gateway_order_id
        ),
        successful_transactions[0] if successful_transactions else None,
    )

    wallet_paid = (order.wallet_amount_used or Decimal("0")).quantize(Decimal("0.01"))
    gateway_paid = (order.gateway_amount_paid or Decimal("0")).quantize(Decimal("0.01"))
    recorded_paid = (wallet_paid + gateway_paid).quantize(Decimal("0.01"))
    transaction_paid = sum((txn.amount for txn in successful_transactions), Decimal("0")).quantize(Decimal("0.01"))
    total_paid = recorded_paid if recorded_paid > 0 else transaction_paid
    if order.paid and total_paid <= 0:
        total_paid = grand_total
    balance_due = (grand_total - total_paid).quantize(Decimal("0.01"))
    if balance_due < 0:
        balance_due = Decimal("0.00")

    payment_transaction_id = "-"
    if primary_transaction:
        payment_transaction_id = (
            primary_transaction.gateway_payment_id
            or primary_transaction.gateway_order_id
            or f"TXN-{primary_transaction.id}"
        )

    return {
        "order": order,
        "order_items": order_items,
        "invoice_line_items": invoice_line_items,
        "buyer_phone": buyer_phone,
        "seller_profiles": seller_profiles,
        "invoice_number": _format_invoice_number(order),
        "subtotal": taxable_subtotal,
        "items_total": items_total,
        "gst_rate_labels": gst_rate_labels,
        "shipping_amount": shipping_amount,
        "discount_amount": discount_amount,
        "gst_amount": gst_amount,
        "grand_total": grand_total,
        "adjustment_amount": adjustment_amount,
        "wallet_paid": wallet_paid,
        "gateway_paid": gateway_paid,
        "total_paid": total_paid,
        "balance_due": balance_due,
        "primary_transaction": primary_transaction,
        "payment_transaction_id": payment_transaction_id,
        "support_email": "support@mykartstore.com",
        "support_phone": "+91 99654 08000",
        "support_company": "MyKartStore",
        "support_address_lines": [
            "Coimbatore, Tamil Nadu 641012",
            "India",
        ],
    }


def _render_invoice_pdf_response(request, context):
    try:
        from weasyprint import HTML
    except ModuleNotFoundError:
        fallback_context = {
            **context,
            "pdf_mode": True,
            "pdf_fallback_mode": True,
        }
        return render(request, "orders/invoice.html", fallback_context)

    html = render_to_string("orders/invoice.html", {**context, "pdf_mode": True}, request=request)
    pdf_bytes = HTML(
        string=html,
        base_url=request.build_absolute_uri("/"),
    ).write_pdf()

    response = HttpResponse(pdf_bytes, content_type="application/pdf")
    response["Content-Disposition"] = f'attachment; filename="{context["invoice_number"]} _ MyKartStore Buyer Invoice.pdf"'
    return response

@login_required
def order_invoice(request, order_id):
    order = get_object_or_404(
        Order.objects.prefetch_related(
            "items",
            "items__product",
            "items__variant",
            "items__product__seller_product__seller",
            "payment_transactions",
        ),
        id=order_id,
        user=request.user
    )

    buyer_phone = order.phone_number or getattr(getattr(request.user, "profile", None), "phone_number", "") or "-"

    return render(
        request,
        "orders/invoice.html",
        _build_invoice_context(order, buyer_phone),
    )


@login_required
def order_invoice_pdf(request, order_id):
    order = get_object_or_404(
        Order.objects.prefetch_related(
            "items",
            "items__product",
            "items__variant",
            "items__product__seller_product__seller",
            "payment_transactions",
        ),
        id=order_id,
        user=request.user,
    )

    buyer_phone = order.phone_number or getattr(getattr(request.user, "profile", None), "phone_number", "") or "-"
    context = _build_invoice_context(order, buyer_phone)
    return _render_invoice_pdf_response(request, context)

@login_required

def order_tracking_list(request):

    orders = (

        Order.objects.filter(user=request.user)

        .prefetch_related("items", "items__product", "items__seller_payout")

        .select_related("delivery_assignment")

        .order_by("-created_at")

    )

    active_tracking_orders = []

    delivered_tracking_orders = []

    cancelled_tracking_orders = []

    for order in orders:

        items = list(order.items.exclude(status=OrderItem.STATUS_CANCELLED))

        if not items:

            items = list(order.items.all())

        row = {

            "order": order,

            "items_count": len(items),

            "preview_items": items[:3],

            "extra_items_count": max(len(items) - 3, 0),

        }

        if order.status == Order.STATUS_CANCELLED:

            cancelled_tracking_orders.append(row)

            continue

        payout_statuses = []

        for item in items:

            try:

                payout_statuses.append(item.seller_payout.delivery_status)

            except SellerPayout.DoesNotExist:

                payout_statuses.append(None)


        all_items_delivered = bool(payout_statuses) and all(

            status == SellerPayout.DELIVERY_DELIVERED for status in payout_statuses

        )


        try:

            assignment = order.delivery_assignment

        except DeliveryAssignment.DoesNotExist:

            assignment = None

        assignment_delivered = (

            assignment and assignment.status == DeliveryAssignment.STATUS_DELIVERED

        )


        if all_items_delivered or assignment_delivered:

            delivered_tracking_orders.append(row)

        else:

            active_tracking_orders.append(row)

    # return_requests = (
    #     ReturnRequest.objects
    #     .filter(user=request.user)
    #     .select_related("order_item", "order_item__product", "order_item__order")
    #     .order_by("-created_at")
    # )

    return_requests = (
        ReturnRequest.objects
        .filter(user=request.user)
        .select_related("order", "product")
        .order_by("-created_at")
    )


    return render(

        request,

        "orders/order_tracking_list.html",

        {

            "orders": orders,

            "active_tracking_orders": active_tracking_orders,

            "delivered_tracking_orders": delivered_tracking_orders,

            "cancelled_tracking_orders": cancelled_tracking_orders,

            # "has_orders": bool(active_tracking_orders or delivered_tracking_orders or cancelled_tracking_orders),

            # ✅ ADD THIS
            "return_requests": return_requests,

            "has_orders": bool(
                active_tracking_orders
                or delivered_tracking_orders
                or cancelled_tracking_orders
            ),

        },

    )




@login_required

def order_tracking_detail(request, order_id):

    order = get_object_or_404(

        Order.objects.prefetch_related("items", "items__product", "payment_transactions"),

        id=order_id,

        user=request.user,

    )

    delivery_assignment = DeliveryAssignment.objects.filter(order=order).select_related("delivery_agent", "updated_by").first()


    payouts = {

        payout.order_item_id: payout

        for payout in SellerPayout.objects.filter(order_item__order=order).select_related(

            "delivery_status_updated_by"

        )

    }

    tracking_rows = []

    for item in order.items.all():

        payout = payouts.get(item.id)
        tracking_status, tracking_status_label = _normalize_tracking_status(
            payout=payout,
            delivery_assignment=delivery_assignment,
            order=order,
        )

        tracking_rows.append(

            {

                "item": item,

                "payout": payout,

                "stage_level": _delivery_stage_level(tracking_status),

                "status_label": tracking_status_label,

                "is_cancellable": item.can_cancel,

            }

        )


    # Get return requests if exists

    return_requests = ReturnRequest.objects.filter(order=order).order_by("-created_at")

    returnable_items = _build_return_items(order) if order.is_returnable else []

    can_initiate_return = any(

        not item.has_existing_return_request for item in returnable_items

    )

    show_return_refund_section = bool(return_requests) or order.status in {
        Order.STATUS_DELIVERED,
        Order.STATUS_RETURNED,
        Order.STATUS_REFUNDED,
    } or (
        delivery_assignment and delivery_assignment.status == DeliveryAssignment.STATUS_DELIVERED
    ) or any(row["stage_level"] >= 5 for row in tracking_rows)


    return render(

        request,

        "orders/order_tracking_detail.html",

        {

            "order": order,

            "tracking_rows": tracking_rows,

            "transactions": order.payment_transactions.all(),

            "delivery_assignment": delivery_assignment,

            "return_requests": return_requests,

            "can_initiate_return": can_initiate_return,

            "can_cancel_order": any(row["is_cancellable"] for row in tracking_rows),

            "show_return_refund_section": show_return_refund_section,

        },

    )




@login_required

@require_POST

def cancel_order(request, order_id):

    order = Order.objects.filter(id=order_id, user=request.user).first()

    if not order:

        if _request_expects_json(request):

            return JsonResponse({"error": "Order not found."}, status=404)

        messages.error(request, "Order not found.")

        return redirect("orders:order_tracking_list")


    reason = _extract_cancellation_reason(request)

    try:

        result = cancel_order_service(order_id=order.id, actor=request.user, reason=reason)

    except OrderCancellationError as exc:

        if _request_expects_json(request):

            return JsonResponse({"error": exc.message, "code": exc.code}, status=exc.status_code)

        messages.error(request, exc.message)

        return redirect("orders:order_tracking_detail", order_id=order.id)


    success_message = "The entire order was cancelled successfully."

    if result.refunded_amount > 0:

        success_message = f"{success_message} Refund of Rs.{result.refunded_amount} was added to wallet."


    if _request_expects_json(request):

        return JsonResponse(

            {

                "message": success_message,

                "order_id": result.order.id,

                "status": result.order.status,

                "cancelled_at": result.order.cancelled_at.isoformat() if result.order.cancelled_at else None,

                "refunded_amount": str(result.refunded_amount),

                "wallet_balance": str(result.wallet_balance),

            },

            status=200,

        )


    messages.success(request, success_message)

    return redirect("orders:order_tracking_detail", order_id=order.id)




@login_required

@require_POST

def cancel_order_item(request, order_item_id):

    order_item = OrderItem.objects.select_related("order", "product").filter(

        id=order_item_id,

        order__user=request.user,

    ).first()

    if not order_item:

        if _request_expects_json(request):

            return JsonResponse({"error": "Order item not found."}, status=404)

        messages.error(request, "Order item not found.")

        return redirect("orders:order_tracking_list")


    reason = _extract_cancellation_reason(request)
    cancel_quantity = _extract_cancellation_quantity(request)

    try:

        result = cancel_order_item_service(
            order_item_id=order_item.id,
            actor=request.user,
            reason=reason,
            quantity_to_cancel=cancel_quantity,
        )

    except OrderCancellationError as exc:

        if _request_expects_json(request):

            return JsonResponse({"error": exc.message, "code": exc.code}, status=exc.status_code)

        messages.error(request, exc.message)

        return redirect("orders:order_tracking_detail", order_id=order_item.order.id)


    success_message = f"'{order_item.product.name}' was cancelled successfully."

    if result.refunded_amount > 0:

        success_message = f"{success_message} Refund of Rs.{result.refunded_amount} was added to wallet."


    if _request_expects_json(request):

        return JsonResponse(

            {

                "message": success_message,

                "order_id": result.order.id,

                "status": result.order.status,

                "refunded_amount": str(result.refunded_amount),

                "wallet_balance": str(result.wallet_balance),

            },

            status=200,

        )


    messages.success(request, success_message)

    return redirect("orders:order_tracking_detail", order_id=order_item.order.id)




@login_required

def delivery_dashboard(request):

    # if not _is_delivery_agent(request.user):
    if not request.user.is_superuser:

        # messages.error(request, "Only delivery staff can access the delivery dashboard.")
        messages.error(request, "Only superusers can access the delivery dashboard.")


        return redirect("products:home")


    assignments = DeliveryAssignment.objects.select_related("order", "delivery_agent").order_by("-updated_at")

    if not request.user.is_staff:

        assignments = assignments.filter(Q(delivery_agent=request.user) | Q(delivery_agent__isnull=True))


    return render(

        request,

        "orders/delivery_dashboard.html",

        {"assignments": assignments},

    )




@login_required

def delivery_update(request, assignment_id):

    if not _is_delivery_agent(request.user):

        messages.error(request, "Only delivery staff can update delivery statuses.")

        return redirect("products:home")


    assignment = get_object_or_404(DeliveryAssignment.objects.select_related("order", "delivery_agent"), id=assignment_id)

    if assignment.delivery_agent and assignment.delivery_agent != request.user and not request.user.is_staff:

        messages.error(request, "You can update only your assigned deliveries.")

        return redirect("orders:delivery_dashboard")


    if request.method == "POST":

        form = DeliveryAssignmentUpdateForm(request.POST, instance=assignment, order=assignment.order)

        if form.is_valid():

            assignment = form.save(commit=False)

            assignment.updated_by = request.user

            assignment.delivery_agent = assignment.delivery_agent or request.user


            if assignment.status == DeliveryAssignment.STATUS_DELIVERED:

                assignment.delivered_at = assignment.delivered_at or timezone.now()

            else:

                assignment.delivered_at = None


            if assignment.order.payment_method == Order.PAYMENT_COD:

                if assignment.cod_payment_status == DeliveryAssignment.COD_COLLECTED:

                    assignment.cod_collected_at = assignment.cod_collected_at or timezone.now()

                else:

                    assignment.cod_collected_at = None

            else:

                assignment.cod_payment_status = DeliveryAssignment.COD_NOT_APPLICABLE

                assignment.cod_collected_amount = Decimal("0")

                assignment.cod_collected_at = None


            assignment.save()

            _sync_cod_payment_state(assignment.order, assignment)

            _sync_order_status_from_delivery(assignment.order, assignment)

            messages.success(request, "Delivery status and payment state updated.")

            return redirect("orders:delivery_dashboard")

    else:

        form = DeliveryAssignmentUpdateForm(instance=assignment, order=assignment.order)


    return render(

        request,

        "orders/delivery_update.html",

        {"assignment": assignment, "form": form},

    )




@login_required

def return_request_create(request, order_id):

    """Create a return request for a delivered order"""

    order = get_object_or_404(Order.objects.select_related("delivery_assignment"), id=order_id, user=request.user)


    # Check if order is eligible for return

    if not order.is_returnable:

        # Provide detailed error message

        try:

            from sellers.models import SellerPayout


            # Check DeliveryAssignment status

            assignment = order.delivery_assignment

            any_delivered = False


            # Check SellerPayout status

            for item in order.items.all():

                try:

                    payout = item.seller_payout

                    if payout and payout.delivery_status == SellerPayout.DELIVERY_DELIVERED:

                        any_delivered = True

                        break

                except SellerPayout.DoesNotExist:

                    continue


            if not assignment:

                messages.error(request, "Delivery information for this order is not available yet.")

            elif assignment.status != DeliveryAssignment.STATUS_DELIVERED and not any_delivered:

                current_status = assignment.get_status_display() if assignment else "Unknown"

                messages.error(

                    request,

                    f"Your order has not been delivered yet. Current status: {current_status}. "

                    "Returns are only allowed for delivered orders."

                )

            elif not assignment.delivered_at and not any_delivered:

                messages.error(request, "Delivery date was not recorded. Please contact support.")

            else:

                deadline = order.return_deadline

                if deadline:

                    messages.error(

                        request,

                        f"Return window has expired. The return window "

                        f"closed on {deadline.strftime('%B %d, %Y')}. "

                        f"Returns are accepted within 7 days of delivery."

                    )

                else:

                    messages.error(request, "Unable to determine return eligibility. Please contact support.")

        except Exception as e:

            messages.error(request, "Unable to determine return eligibility. Please contact support.")

        return redirect("orders:order_tracking_detail", order_id)


    if request.method == "POST":
        selected_product_ids = []
        form_errors = []

        seen_selected_product_ids = set()
        for product_id in request.POST.getlist("selected_products"):
            try:
                product_id = int(product_id)
            except (TypeError, ValueError):
                form_errors.append("One selected product is invalid.")
                continue
            if product_id not in seen_selected_product_ids:
                selected_product_ids.append(product_id)
                seen_selected_product_ids.add(product_id)

        eligible_items = _build_return_items(
            order,
            selected_product_ids=selected_product_ids,
            posted_data=request.POST,
        )
        eligible_by_product_id = {
            item.product_id: item for item in eligible_items if not item.has_existing_return_request
        }

        if not selected_product_ids:
            form_errors.append("Select at least one product to return.")

        return_requests_to_create = []
        reason_choices = dict(ReturnRequest.REASON_CHOICES)

        for product_id in selected_product_ids:
            item = eligible_by_product_id.get(product_id)
            if not item:
                form_errors.append("One selected product is not available for return.")
                continue

            reason = request.POST.get(f"reason_{product_id}", "").strip()
            other_reason = strip_tags(request.POST.get(f"other_reason_{product_id}", "")).strip()
            uploaded_photos = request.FILES.getlist(f"photos_{product_id}")

            if reason not in reason_choices:
                form_errors.append(f"Choose a return reason for {item.product.name}.")
            elif reason == ReturnRequest.REASON_OTHER and not other_reason:
                form_errors.append(f"Enter the other reason for {item.product.name}.")

            photo_errors = _validate_return_photos(uploaded_photos)
            form_errors.extend(f"{item.product.name}: {error}" for error in photo_errors)

            return_requests_to_create.append(
                {
                    "item": item,
                    "reason": reason,
                    "description": other_reason if reason == ReturnRequest.REASON_OTHER else "",
                    "photos": uploaded_photos,
                }
            )

        if not form_errors:
            created_count = 0
            total_refund = Decimal("0")
            with transaction.atomic():
                for entry in return_requests_to_create:
                    item = entry["item"]
                    uploaded_photos = entry["photos"]
                    refund_amount = item.price * item.quantity
                    return_request = ReturnRequest.objects.create(
                        order=order,
                        user=request.user,
                        product=item.product,
                        reason=entry["reason"],
                        description=entry["description"],
                        refund_amount=refund_amount,
                        photo=uploaded_photos[0] if uploaded_photos else None,
                    )
                    for photo in uploaded_photos:
                        ReturnRequestImage.objects.create(return_request=return_request, image=photo)
                    created_count += 1
                    total_refund += refund_amount

            messages.success(
                request,
                f"{created_count} return request(s) submitted successfully. Estimated refund: Rs.{total_refund}.",
            )
            return redirect("orders:order_tracking_detail", order_id)

    else:
        form_errors = []
        eligible_items = _build_return_items(order)


    return render(

        request,

        "orders/return_request_form.html",

        {
            "order": order,
            "eligible_items": eligible_items,
            "return_reason_choices": ReturnRequest.REASON_CHOICES,
            "form_errors": form_errors,
        },

    )




@login_required

def return_request_list(request):

    """List all return requests for the logged-in user"""

    return_requests = ReturnRequest.objects.filter(user=request.user).select_related(

        "order", "product"

    ).order_by("-created_at")


    pending_returns = return_requests.filter(status=ReturnRequest.STATUS_PENDING)

    approved_returns = return_requests.filter(status=ReturnRequest.STATUS_APPROVED)

    withdrawn_returns = return_requests.filter(status=ReturnRequest.STATUS_WITHDRAWN)

    shipped_returns = return_requests.filter(status__in=[ReturnRequest.STATUS_SHIPPED_BY_BUYER, ReturnRequest.STATUS_PICKED_UP])

    received_returns = return_requests.filter(status=ReturnRequest.STATUS_RECEIVED_BY_SELLER)

    refunded_returns = return_requests.filter(status__in=[ReturnRequest.STATUS_REFUNDED, ReturnRequest.STATUS_REFUND_COMPLETED])

    rejected_returns = return_requests.filter(status=ReturnRequest.STATUS_REJECTED)


    return render(

        request,

        "orders/return_request_list.html",

        {

            "return_requests": return_requests,

            "pending_returns": pending_returns,

            "approved_returns": approved_returns,

            "withdrawn_returns": withdrawn_returns,

            "shipped_returns": shipped_returns,

            "received_returns": received_returns,

            "refunded_returns": refunded_returns,

            "rejected_returns": rejected_returns,

        },

    )

@login_required
@require_POST
def confirm_return_shipment(request, return_id):
    return_request = get_object_or_404(ReturnRequest, id=return_id, user=request.user)
    if return_request.status == ReturnRequest.STATUS_APPROVED:
        return_request.status = ReturnRequest.STATUS_SHIPPED_BY_BUYER
        return_request.shipped_at = timezone.now()
        return_request.save(update_fields=["status", "shipped_at", "updated_at"])
        messages.success(request, "Return shipment confirmed successfully.")
    else:
        messages.error(request, "This return request cannot be marked as shipped.")
    return redirect("orders:return_request_list")


@login_required
@require_POST
def withdraw_return_request(request, return_id=None, request_id=None):
    target_return_id = return_id if return_id is not None else request_id
    return_request = get_object_or_404(ReturnRequest, id=target_return_id, user=request.user)
    if return_request.status not in {
        ReturnRequest.STATUS_PENDING,
        ReturnRequest.STATUS_APPROVED,
    }:
        messages.error(request, "This return request can no longer be withdrawn.")
        return redirect("orders:order_tracking_detail", return_request.order_id)

    order_id = return_request.order_id
    return_request.status = ReturnRequest.STATUS_WITHDRAWN
    return_request.save(update_fields=["status", "updated_at"])
    messages.success(request, "Return request withdrawn successfully.")
    return redirect("orders:order_tracking_detail", order_id)



@login_required

def wallet_detail(request):

    from .models import Wallet

    wallet, _ = Wallet.objects.get_or_create(user=request.user)
    wallet_transactions = wallet.transactions.select_related("order", "return_request").all() if wallet else []
    total_refunded = sum(
        (txn.amount for txn in wallet_transactions if txn.transaction_type == WalletTransaction.TYPE_CREDIT),
        Decimal("0"),
    )
    total_spent = sum(
        (txn.amount for txn in wallet_transactions if txn.transaction_type == WalletTransaction.TYPE_DEBIT),
        Decimal("0"),
    )

    return render(
        request,
        "orders/wallet_detail.html",
        {
            "wallet": wallet,
            "wallet_transactions": wallet_transactions,
            "total_refunded": total_refunded,
            "total_spent": total_spent,
        },
    )











# ============================================================================

# REVIEW SYSTEM VIEWS

# ============================================================================


def _wants_json_response(request):

    return request.headers.get("x-requested-with") == "XMLHttpRequest" or "application/json" in request.headers.get("Accept", "")




def _user_has_verified_purchase(user, product):

    delivered_qs = OrderItem.objects.filter(

        order__user=user,

        product=product,

    ).filter(

        Q(order__status=Order.STATUS_DELIVERED)

        | Q(seller_payout__delivery_status=SellerPayout.DELIVERY_DELIVERED)

        | Q(order__delivery_assignment__status=DeliveryAssignment.STATUS_DELIVERED)

    )

    return delivered_qs.exists()




def _serialize_review(review):

    return {

        "id": review.id,

        "user": review.user.username if review.user else "Deleted user",

        "product_id": review.product_id,

        "product": review.product.name,

        "rating": review.rating,

        "comment": review.comment,

        "created_at": review.created_at.isoformat(),

        "updated_at": review.updated_at.isoformat(),

        "is_verified_purchase": review.is_verified_purchase,

        "is_reported": review.is_reported,

        "report_count": review.report_count,

        "is_flagged": review.is_flagged,

        "images": [image.image.url for image in review.images.all() if image.image],

    }




def _review_list_redirect_url(request, product):

    next_url = request.POST.get("next") or request.GET.get("next")

    return next_url or reverse("products:product_detail", args=[product.id, product.slug])




@login_required

def review_add(request):

    product_id = request.POST.get("product_id") or request.GET.get("product_id")

    product = get_object_or_404(Product, id=product_id)


    if request.method == "POST":

        form = ReviewForm(request.POST, request.FILES, user=request.user, product=product)

        if form.is_valid():

            review = form.save(commit=False)

            review.user = request.user

            review.product = product

            review.is_verified_purchase = _user_has_verified_purchase(request.user, product)

            review.comment = strip_tags(review.comment or "")

            review.save()


            for image in request.FILES.getlist("images"):

                ReviewImage.objects.create(review=review, image=image)


            message = "Review posted successfully."

            if _wants_json_response(request):

                review = Review.objects.select_related("user", "product").prefetch_related("images").get(id=review.id)

                return JsonResponse({"success": True, "message": message, "review": _serialize_review(review)}, status=201)

            messages.success(request, message)

            return redirect(_review_list_redirect_url(request, product))


        if _wants_json_response(request):

            return JsonResponse({"success": False, "errors": form.errors}, status=400)

    else:

        form = ReviewForm(user=request.user, product=product)


    return render(

        request,

        "orders/review_form.html",

        {

            "form": form,

            "product": product,

            "next_url": _review_list_redirect_url(request, product),

            "is_verified_purchase": _user_has_verified_purchase(request.user, product),

        },

    )




@login_required

def review_create(request, order_item_id):

    order_item = get_object_or_404(

        OrderItem.objects.select_related("order", "product"),

        id=order_item_id,

        order__user=request.user,

    )

    url = f"{reverse('reviews:add')}?product_id={order_item.product_id}&next={reverse('orders:order_tracking_detail', args=[order_item.order_id])}"

    return redirect(url)




def product_reviews(request, product_id):

    product = get_object_or_404(Product, id=product_id)

    sort = (request.GET.get("sort") or "latest").strip()

    verified_only = request.GET.get("verified_only") == "1"

    page_number = request.GET.get("page") or 1


    reviews = Review.objects.filter(product=product, is_flagged=False).select_related("user").prefetch_related("images")

    if verified_only:

        reviews = reviews.filter(is_verified_purchase=True)


    sort_map = {

        "latest": "-created_at",

        "highest": "-rating",

        "lowest": "rating",

    }

    reviews = reviews.order_by(sort_map.get(sort, "-created_at"), "-created_at")


    paginator = Paginator(reviews, 10)

    page_obj = paginator.get_page(page_number)


    return JsonResponse(

        {

            "product": {"id": product.id, "name": product.name},

            "sort": sort if sort in sort_map else "latest",

            "verified_only": verified_only,

            "pagination": {

                "page": page_obj.number,

                "pages": paginator.num_pages,

                "has_next": page_obj.has_next(),

                "has_previous": page_obj.has_previous(),

                "total": paginator.count,

            },

            "reviews": [_serialize_review(review) for review in page_obj.object_list],

        }

    )




@login_required

@require_POST

def report_review(request, review_id):

    review = get_object_or_404(Review.objects.select_related("product"), id=review_id)

    seller_profile = getattr(request.user, "seller_profile", None)

    if not seller_profile or not seller_profile.is_approved:

        return JsonResponse({"success": False, "message": "Only approved sellers can report reviews."}, status=403)


    owns_product = getattr(review.product, "seller_product", None)

    if not owns_product or owns_product.seller_id != seller_profile.id:

        return JsonResponse({"success": False, "message": "You can only report reviews for your own products."}, status=403)


    form = ReviewReportForm(request.POST)

    if not form.is_valid():

        first_error = next(iter(form.errors.values()))[0] if form.errors else "Unable to submit report."

        return JsonResponse({"success": False, "message": first_error, "errors": form.errors}, status=400)


    report, created = ReviewReport.objects.get_or_create(

        review=review,

        reported_by=request.user,

        defaults={

            "reason": form.cleaned_data["reason"],

            "status": ReviewReport.STATUS_PENDING,

        },

    )

    if not created:

        return JsonResponse({"success": False, "message": "You have already reported this review."}, status=400)


    review.report_count = review.reports.count()

    review.refresh_report_flags(save=False)

    review.save(update_fields=["report_count", "is_reported", "is_flagged", "updated_at"])


    return JsonResponse(

        {

            "success": True,

            "message": "Review reported successfully.",

            "review_id": review.id,

            "report_count": review.report_count,

            "is_flagged": review.is_flagged,

        }

    )




@login_required

def admin_review_list(request):

    if not request.user.is_staff:

        messages.error(request, "You do not have permission to access this page.")

        return redirect("products:home")


    reports = ReviewReport.objects.select_related("review", "review__user", "review__product", "reported_by").order_by("-created_at")

    status_filter = (request.GET.get("status") or "").strip()

    if status_filter in dict(ReviewReport.STATUS_CHOICES):

        reports = reports.filter(status=status_filter)


    if request.method == "POST":

        action = request.POST.get("action")

        report = get_object_or_404(ReviewReport, id=request.POST.get("report_id"))

        review = report.review


        if action == "resolve":

            report.status = ReviewReport.STATUS_RESOLVED

            report.save(update_fields=["status"])

            messages.success(request, "Report marked as resolved.")

        elif action == "reject":

            report.status = ReviewReport.STATUS_REJECTED

            report.save(update_fields=["status"])

            review.report_count = review.reports.filter(status=ReviewReport.STATUS_PENDING).count()

            review.refresh_report_flags(save=False)

            review.save(update_fields=["report_count", "is_reported", "is_flagged", "updated_at"])

            messages.success(request, "Report marked as rejected.")

        elif action == "delete_review":

            product_name = review.product.name

            review.delete()

            messages.success(request, f"Review for '{product_name}' deleted.")

        elif action == "suspend_user":

            if review.user:

                review.user.is_active = False

                review.user.save(update_fields=["is_active"])

                messages.success(request, f"User '{review.user.username}' suspended and report resolved.")

            else:

                messages.info(request, "Review user no longer exists. Report marked as resolved.")

            report.status = ReviewReport.STATUS_RESOLVED

            report.save(update_fields=["status"])

        return redirect("orders:admin_review_list")


    return render(

        request,

        "orders/admin_review_list.html",

        {

            "reports": reports,

            "status_filter": status_filter,

            "status_choices": ReviewReport.STATUS_CHOICES,

        },

    )
