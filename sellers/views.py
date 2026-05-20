from decimal import Decimal
import logging
import os
import secrets
import re

from django.contrib.admin.views.decorators import staff_member_required
from django.contrib.auth import get_user_model
from django.contrib.auth.decorators import login_required
from django.core.files import File
from django.core.paginator import Paginator
from django.core.files.storage import default_storage
from django.db import transaction
from django.db.models import Avg
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.cache import never_cache
from django.contrib import messages
from accounts.models import Address, Profile
from orders.models import Order, Review
from orders.forms import ReviewReportForm
from orders.utils.email import handle_order_status_change
from django.views.decorators.http import require_POST
from products.models import Category

from .forms import (
    SellerCouponForm,
    SellerProductEntryFormSet,
    SellerProductPublishForm,
    SellerProductSharedSettingsForm,
    SellerProfileRegistrationForm,
)
from .models import Payout, SellerLedger, SellerNotification, SellerOrderPayout, SellerPayout, SellerProfile, SellerProduct, SellerWallet
from .services import PayoutCalculator, PayoutService, WalletService


logger = logging.getLogger(__name__)


PUBLISH_SUBMISSION_SESSION_KEY = "seller_publish_submission_key"
PUBLISH_LAST_PROCESSED_SESSION_KEY = "seller_publish_last_processed_key"
SELLER_REGISTRATION_DRAFT_SESSION_KEY = "seller_registration_draft"


ORDER_NOTIFICATION_PREFIXES = (
    "New own-delivery order for ",
    "New order received for ",
)


def _format_notification_message(notification):
    message = (notification.message or "").strip()
    order_item = getattr(notification, "order_item", None)
    order = getattr(order_item, "order", None)
    product = getattr(order_item, "product", None)
    display_order_id = getattr(order, "display_order_id", "")

    for prefix in ORDER_NOTIFICATION_PREFIXES:
        if message.startswith(prefix):
            message = message[len(prefix):]
            break

    if display_order_id:
        message = re.sub(r"Order\s*#\d+", f"Order {display_order_id}", message)
        message = re.sub(r"order\s*#\d+", f"order {display_order_id}", message)

    if (
        notification.notification_type == SellerNotification.TYPE_SELLER_ORDER
        and product is not None
        and message.startswith(f"{product.name}.")
    ):
        message = f"{product.name} {message[len(product.name) + 1:].lstrip()}"

    return message


def _format_invoice_address(address_line="", city="", state="", pincode="", country=""):
    parts = [
        (address_line or "").strip(),
        (city or "").strip(),
        (state or "").strip(),
        (pincode or "").strip(),
        (country or "").strip(),
    ]
    return ", ".join(part for part in parts if part)


INVOICE_STATE_CODE_MAP = {
    "andaman and nicobar islands": "35",
    "andhra pradesh": "37",
    "arunachal pradesh": "12",
    "assam": "18",
    "bihar": "10",
    "chandigarh": "04",
    "chhattisgarh": "22",
    "dadra and nagar haveli and daman and diu": "26",
    "delhi": "07",
    "goa": "30",
    "gujarat": "24",
    "haryana": "06",
    "himachal pradesh": "02",
    "jammu and kashmir": "01",
    "jharkhand": "20",
    "karnataka": "29",
    "kerala": "32",
    "ladakh": "38",
    "lakshadweep": "31",
    "madhya pradesh": "23",
    "maharashtra": "27",
    "manipur": "14",
    "meghalaya": "17",
    "mizoram": "15",
    "nagaland": "13",
    "odisha": "21",
    "puducherry": "34",
    "punjab": "03",
    "rajasthan": "08",
    "sikkim": "11",
    "tamil nadu": "33",
    "telangana": "36",
    "tripura": "16",
    "uttar pradesh": "09",
    "uttarakhand": "05",
    "west bengal": "19",
}


def _normalize_invoice_state(value=""):
    normalized = re.sub(r"[^a-z\s]", " ", (value or "").strip().lower())
    return " ".join(normalized.split())


def _extract_invoice_state(value=""):
    normalized = _normalize_invoice_state(value)
    if not normalized:
        return ""

    for state_name in INVOICE_STATE_CODE_MAP:
        if state_name in normalized:
            return state_name.title()

    return ""


def _get_invoice_state_code(state_name=""):
    return INVOICE_STATE_CODE_MAP.get(_normalize_invoice_state(state_name), "-")


def _get_invoice_tax_type(seller_state="", buyer_state=""):
    normalized_seller_state = _normalize_invoice_state(seller_state)
    normalized_buyer_state = _normalize_invoice_state(buyer_state)
    if normalized_seller_state and normalized_buyer_state and normalized_seller_state == normalized_buyer_state:
        return "CGST + SGST"
    return "IGST"


def _amount_to_words(number):
    number = Decimal(str(number or 0)).quantize(Decimal("0.01"))
    integer_part = int(number)
    paise = int(((number - Decimal(integer_part)) * 100).quantize(Decimal("1")))

    ones = [
        "Zero", "One", "Two", "Three", "Four", "Five", "Six", "Seven", "Eight", "Nine",
        "Ten", "Eleven", "Twelve", "Thirteen", "Fourteen", "Fifteen", "Sixteen",
        "Seventeen", "Eighteen", "Nineteen",
    ]
    tens = ["", "", "Twenty", "Thirty", "Forty", "Fifty", "Sixty", "Seventy", "Eighty", "Ninety"]

    def _two_digits(value):
        if value < 20:
            return ones[value]
        tens_word = tens[value // 10]
        ones_word = "" if value % 10 == 0 else f" {ones[value % 10]}"
        return f"{tens_word}{ones_word}"

    def _three_digits(value):
        if value < 100:
            return _two_digits(value)
        remainder = value % 100
        remainder_text = "" if remainder == 0 else f" {_two_digits(remainder)}"
        return f"{ones[value // 100]} Hundred{remainder_text}"

    def _integer_to_words(value):
        if value == 0:
            return ones[0]

        parts = []
        crore = value // 10000000
        value %= 10000000
        lakh = value // 100000
        value %= 100000
        thousand = value // 1000
        value %= 1000
        hundred = value

        if crore:
            parts.append(f"{_two_digits(crore)} Crore")
        if lakh:
            parts.append(f"{_two_digits(lakh)} Lakh")
        if thousand:
            parts.append(f"{_two_digits(thousand)} Thousand")
        if hundred:
            parts.append(_three_digits(hundred))

        return " ".join(parts)

    words = f"{_integer_to_words(integer_part)}"
    if paise:
        words = f"{words} and {_integer_to_words(paise)} Paise"
    return f"{words} only"


def _build_invoice_party_details(name="", email="", phone="", address_line="", city="", state="", pincode="", country=""):
    resolved_state = (state or "").strip() or _extract_invoice_state(address_line)
    return {
        "name": (name or "").strip() or "-",
        "email": (email or "").strip() or "-",
        "phone": (phone or "").strip() or "-",
        "address": _format_invoice_address(address_line, city, state, pincode, country) or "-",
        "state": resolved_state or "-",
        "state_code": _get_invoice_state_code(resolved_state),
    }


def _issue_publish_submission_key(request, *, refresh=False):
    key = None if refresh else request.session.get(PUBLISH_SUBMISSION_SESSION_KEY)
    if not key:
        key = secrets.token_urlsafe(24)
        request.session[PUBLISH_SUBMISSION_SESSION_KEY] = key
    return key


def _get_registration_draft(request):
    draft = request.session.get(SELLER_REGISTRATION_DRAFT_SESSION_KEY)
    if not draft or draft.get("user_id") != request.user.id:
        return None
    return draft


def _delete_stored_file(path):
    if path and default_storage.exists(path):
        default_storage.delete(path)


def _clear_registration_draft(request):
    draft = _get_registration_draft(request)
    if draft:
        _delete_stored_file(draft.get("seller_signature_temp_path"))
    request.session.pop(SELLER_REGISTRATION_DRAFT_SESSION_KEY, None)
    request.session.modified = True


def _store_registration_signature(uploaded_file, *, previous_path=""):
    if previous_path:
        _delete_stored_file(previous_path)
    extension = os.path.splitext(uploaded_file.name or "")[1] or ".bin"
    temp_path = default_storage.save(
        f"seller_registration_drafts/{secrets.token_hex(12)}{extension}",
        uploaded_file,
    )
    return temp_path


def _build_registration_draft(form, request):
    previous_draft = _get_registration_draft(request) or {}
    temp_path = previous_draft.get("seller_signature_temp_path", "")
    signature_name = previous_draft.get("seller_signature_name", "")
    uploaded_signature = form.cleaned_data.get("seller_signature")
    if uploaded_signature:
        temp_path = _store_registration_signature(
            uploaded_signature,
            previous_path=temp_path,
        )
        signature_name = uploaded_signature.name

    fields = [
        "business_name",
        "brand_name",
        "phone",
        "website",
        "pan_card_number",
        "business_pan_card_number",
        "aadhar_number",
        "gst_number",
        "payout_upi_id",
        "payout_phonepay_gpay_number",
        "supplier_details",
        "registered_office_address",
        "contact_person_name",
        "contact_email",
        "alternate_phone",
        "payout_account_name",
        "payout_account_number",
        "payout_ifsc",
        "terms_accepted",
    ]
    form_data = {field: form.cleaned_data.get(field) for field in fields}
    form_data["product_categories"] = list(
        form.cleaned_data.get("product_categories", []).values_list("id", flat=True)
    )
    return {
        "user_id": request.user.id,
        "form_data": form_data,
        "seller_signature_temp_path": temp_path,
        "seller_signature_name": signature_name,
    }


def _build_registration_form_initial(draft):
    form_data = (draft or {}).get("form_data", {})
    initial = form_data.copy()
    initial["product_categories"] = form_data.get("product_categories", [])
    return initial


def _build_registration_review_sections(draft):
    form_data = draft["form_data"]
    category_model = SellerProfile._meta.get_field("product_categories").remote_field.model
    categories = list(
        category_model.objects.filter(
            id__in=form_data.get("product_categories", [])
        ).order_by("name")
    )
    return [
        {
            "title": "Supplier Details",
            "rows": [
                ("Business Name", form_data.get("business_name") or "-"),
                ("Brand Name", form_data.get("brand_name") or "Not provided"),
                ("Business Description", form_data.get("supplier_details") or "-"),
            ],
        },
        {
            "title": "Contact Information",
            "rows": [
                ("Contact Person Name", form_data.get("contact_person_name") or "-"),
                ("Contact Email", form_data.get("contact_email") or "-"),
                ("Primary Phone", form_data.get("phone") or "-"),
                ("Alternate Phone", form_data.get("alternate_phone") or "Not provided"),
                ("Website", form_data.get("website") or "Not provided"),
            ],
        },
        {
            "title": "Documents and Tax Details",
            "rows": [
                ("Signature", draft.get("seller_signature_name") or "Uploaded"),
                ("PAN Card Number", form_data.get("pan_card_number") or "-"),
                ("Business PAN Card Number", form_data.get("business_pan_card_number") or "Not provided"),
                ("Aadhaar Number", form_data.get("aadhar_number") or "Not provided"),
                ("GST Number", form_data.get("gst_number") or "Not provided"),
            ],
        },
        {
            "title": "Business and Category Details",
            "rows": [
                ("Registered Office Address", form_data.get("registered_office_address") or "-"),
                (
                    "Product Categories",
                    ", ".join(category.name for category in categories) or "-",
                ),
            ],
        },
        {
            "title": "Payout Details",
            "rows": [
                ("Payout Account Name", form_data.get("payout_account_name") or "-"),
                ("Payout Account Number", form_data.get("payout_account_number") or "-"),
                ("IFSC", form_data.get("payout_ifsc") or "-"),
                ("UPI ID", form_data.get("payout_upi_id") or "Not provided"),
                (
                    "PhonePe / GPay Number",
                    form_data.get("payout_phonepay_gpay_number") or "Not provided",
                ),
            ],
        },
        {
            "title": "Confirmation",
            "rows": [
                (
                    "Terms Accepted",
                    "Yes" if form_data.get("terms_accepted") else "No",
                ),
            ],
        },
    ]


def _create_seller_profile_from_draft(request, draft):
    form_data = draft["form_data"]
    profile = SellerProfile(
        user=request.user,
        approval_status=SellerProfile.STATUS_PENDING,
        business_name=form_data.get("business_name") or "",
        brand_name=form_data.get("brand_name") or "",
        phone=form_data.get("phone") or "",
        website=form_data.get("website") or "",
        pan_card_number=form_data.get("pan_card_number") or "",
        business_pan_card_number=form_data.get("business_pan_card_number") or "",
        aadhar_number=form_data.get("aadhar_number") or "",
        gst_number=form_data.get("gst_number") or "",
        payout_upi_id=form_data.get("payout_upi_id") or "",
        payout_phonepay_gpay_number=form_data.get("payout_phonepay_gpay_number") or "",
        supplier_details=form_data.get("supplier_details") or "",
        registered_office_address=form_data.get("registered_office_address") or "",
        contact_person_name=form_data.get("contact_person_name") or "",
        contact_email=form_data.get("contact_email") or "",
        alternate_phone=form_data.get("alternate_phone") or "",
        payout_account_name=form_data.get("payout_account_name") or "",
        payout_account_number=form_data.get("payout_account_number") or "",
        payout_ifsc=form_data.get("payout_ifsc") or "",
        terms_accepted=bool(form_data.get("terms_accepted")),
    )
    signature_temp_path = draft.get("seller_signature_temp_path")
    if signature_temp_path:
        with default_storage.open(signature_temp_path, "rb") as signature_file:
            profile.seller_signature.save(
                os.path.basename(signature_temp_path),
                File(signature_file),
                save=False,
            )
    profile.save()
    profile.product_categories.set(form_data.get("product_categories", []))
    return profile


def _money(value):
    return Decimal(str(value or "0")).quantize(Decimal("0.01"))


def _build_recent_payout_runs(seller, *, limit=None):
    payout_runs = [
        {
            "kind": "payout_run",
            "created_at": payout.created_at,
            "amount": _money(payout.amount),
            "status": payout.status,
            "status_display": payout.get_status_display(),
            "reference": payout.reference or "Pending reference",
            "processed_at": payout.processed_at,
            "title": "Wallet payout",
            "subtitle": "Released from available balance",
        }
        for payout in Payout.objects.filter(seller=seller).order_by("-created_at", "-id")
    ]

    paid_order_runs = [
        {
            "kind": "order_payout",
            "created_at": payout.paid_at or payout.updated_at or payout.created_at,
            "amount": _money(payout.net_amount),
            "status": payout.status,
            "status_display": payout.get_status_display(),
            "reference": payout.order.display_order_id,
            "processed_at": payout.paid_at,
            "title": "Order payout settled",
            "subtitle": payout.order.display_order_id,
        }
        for payout in SellerOrderPayout.objects.filter(seller=seller, status=SellerOrderPayout.STATUS_PAID)
        .select_related("order")
        .order_by("-paid_at", "-updated_at", "-id")
    ]

    combined_runs = sorted(
        payout_runs + paid_order_runs,
        key=lambda run: run["created_at"] or timezone.datetime.min.replace(tzinfo=timezone.get_current_timezone()),
        reverse=True,
    )
    if limit is not None:
        return combined_runs[:limit]
    return combined_runs


def _build_product_sales_snapshot(payouts, seller_products):
    sales_map = {
        seller_product.product_id: {
            "name": seller_product.product.name,
            "sales_amount": Decimal("0.00"),
            "quantity": 0,
        }
        for seller_product in seller_products
    }
    total_sales = Decimal("0.00")

    for payout in payouts:
        order_item = payout.order_item
        product = order_item.product
        sale_amount = _money(order_item.get_net_cost())
        total_sales += sale_amount
        entry = sales_map.setdefault(
            product.id,
            {
                "name": product.name,
                "sales_amount": Decimal("0.00"),
                "quantity": 0,
            },
        )
        entry["sales_amount"] += sale_amount
        entry["quantity"] += order_item.quantity

    top_products = sorted(
        sales_map.values(),
        key=lambda item: (item["sales_amount"], item["quantity"], item["name"].lower()),
        reverse=True,
    )

    palette = [
        "#38bdf8",
        "#818cf8",
        "#34d399",
        "#f59e0b",
        "#fb7185",
        "#c084fc",
    ]

    chart_segments = []
    current_angle = Decimal("0")
    for index, item in enumerate(top_products):
        percentage = Decimal("0.00")
        if total_sales > 0:
            percentage = ((item["sales_amount"] / total_sales) * Decimal("100")).quantize(Decimal("0.01"))
        item["sales_amount"] = _money(item["sales_amount"])
        item["share_percentage"] = percentage
        item["color"] = palette[index % len(palette)]
        if percentage > 0:
            start_angle = current_angle
            current_angle += (percentage / Decimal("100")) * Decimal("360")
            end_angle = current_angle
            chart_segments.append(f"{item['color']} {start_angle:.2f}deg {end_angle:.2f}deg")

    return {
        "total_sales_amount": _money(total_sales),
        "top_products": top_products,
        "product_count": len(top_products),
        "chart_background": f"conic-gradient({', '.join(chart_segments)})" if chart_segments else "",
    }


def _category_tax_data():
    return [
        {
            "id": category.id,
            "gst_rate": str(category.gst_rate or Decimal("18.00")),
            "hsn_code": category.hsn_code or "",
        }
        for category in Category.objects.order_by("name")
    ]


def _is_zeroed_order(order):
    return order.order_status in {Order.ORDER_STATUS_CANCELLED, Order.ORDER_STATUS_RETURNED} or order.status == Order.STATUS_CANCELLED


def _display_order_status(payout_summary):
    if payout_summary.order.order_status == Order.ORDER_STATUS_RETURNED:
        return "Returned"
    if payout_summary.order.order_status == Order.ORDER_STATUS_CANCELLED or payout_summary.order.status == Order.STATUS_CANCELLED:
        return "Cancelled"
    return payout_summary.get_status_display()


def _decorate_payout_summary(payout_summary):
    payout_summary.display_status = _display_order_status(payout_summary)
    if _is_zeroed_order(payout_summary.order):
        payout_summary.display_gross_amount = Decimal("0.00")
        payout_summary.display_net_amount = Decimal("0.00")
    else:
        payout_summary.display_gross_amount = payout_summary.gross_amount
        payout_summary.display_net_amount = payout_summary.net_amount
    return payout_summary


def _build_display_financial_snapshot(seller):
    summaries = [
        _decorate_payout_summary(summary)
        for summary in SellerOrderPayout.objects.filter(seller=seller).select_related("order").order_by("-updated_at", "-id")
    ]
    status_totals = {
        SellerOrderPayout.STATUS_PENDING: Decimal("0.00"),
        SellerOrderPayout.STATUS_HOLD: Decimal("0.00"),
        SellerOrderPayout.STATUS_AVAILABLE: Decimal("0.00"),
        SellerOrderPayout.STATUS_PAID: Decimal("0.00"),
    }
    for summary in summaries:
        if summary.display_net_amount <= 0:
            continue
        if summary.status in status_totals:
            status_totals[summary.status] += summary.display_net_amount
    pending_payout = _money(
        status_totals[SellerOrderPayout.STATUS_PENDING]
        + status_totals[SellerOrderPayout.STATUS_HOLD]
        + status_totals[SellerOrderPayout.STATUS_AVAILABLE]
    )
    paid_payout = _money(status_totals[SellerOrderPayout.STATUS_PAID])
    return {
        "earnings": summaries,
        "wallet": {
            "pending_balance": _money(status_totals[SellerOrderPayout.STATUS_PENDING]),
            "hold_balance": _money(status_totals[SellerOrderPayout.STATUS_HOLD]),
            "available_balance": _money(status_totals[SellerOrderPayout.STATUS_AVAILABLE]),
            "paid_balance": paid_payout,
        },
        "pending_payout": pending_payout,
        "paid_payout": paid_payout,
        "wallet_balance": _money(pending_payout + paid_payout),
    }


def _build_order_item_breakdown_rows(*, seller, order):
    ledger_entries = list(
        SellerLedger.objects.filter(seller=seller, order=order)
        .select_related("order")
        .order_by("created_at", "id")
    )
    rows = {}
    item_ids = set()
    for entry in ledger_entries:
        order_item_id = entry.metadata.get("order_item_id")
        if not order_item_id:
            continue
        item_ids.add(order_item_id)
        row = rows.setdefault(
            order_item_id,
            {
                "order_id": order.id,
                "order_number": f"#{order.id}",
                "order_status": order.get_order_status_display(),
                "item_id": order_item_id,
                "reference_id": entry.reference_id,
                "created_at": entry.created_at,
                "status": entry.get_status_display(),
                "product_name": "",
                "quantity": 0,
                "gross_amount": Decimal("0.00"),
                "discounted_amount": Decimal("0.00"),
                "seller_discount": Decimal("0.00"),
                "product_discount": Decimal("0.00"),
                "coupon_discount": Decimal("0.00"),
                "commission": Decimal("0.00"),
                "gateway_fee": Decimal("0.00"),
                "shipping": Decimal("0.00"),
                "return_shipping": Decimal("0.00"),
                "gst": Decimal("0.00"),
                "tds": Decimal("0.00"),
                "net_amount": Decimal("0.00"),
                "delivery_type": "",
            },
        )
        row["net_amount"] = _money(row["net_amount"] + entry.signed_amount)
        if entry.created_at >= row["created_at"]:
            row["status"] = entry.get_status_display()

        breakdown = entry.metadata.get("breakdown") or {}
        if breakdown:
            row["gross_amount"] = _money(breakdown.get("product_price"))
            row["discounted_amount"] = _money(
                breakdown.get(
                    "taxable_product_price",
                    _money(breakdown.get("product_price", "0")) - _money(breakdown.get("seller_discount", "0")),
                )
            )
            row["seller_discount"] = _money(breakdown.get("seller_discount"))
            row["product_discount"] = _money(breakdown.get("product_discount"))
            row["coupon_discount"] = _money(breakdown.get("coupon_discount"))
            row["commission"] = _money(breakdown.get("platform_commission"))
            row["gateway_fee"] = _money(breakdown.get("payment_gateway_fee"))
            row["shipping"] = _money(breakdown.get("shipping_charges"))
            row["gst"] = _money(breakdown.get("gst"))
            row["tds"] = _money(breakdown.get("tds"))
            row["delivery_type"] = breakdown.get("delivery_type") or row["delivery_type"]

        if entry.component == SellerLedger.COMPONENT_RETURN_SHIPPING:
            row["return_shipping"] = _money(row["return_shipping"] + entry.amount)

    order_items = {
        item.id: item
        for item in order.items.filter(id__in=item_ids).select_related("product")
    }
    for item_id, row in rows.items():
        item = order_items.get(item_id)
        if item:
            row["product_name"] = item.product.name
            row["quantity"] = item.quantity
        row["total_deductions"] = _money(
            row["seller_discount"]
            + row["commission"]
            + row["gateway_fee"]
            + row["shipping"]
            + row["return_shipping"]
            + row["gst"]
            + row["tds"]
        )
        if _is_zeroed_order(order):
            row["gross_amount"] = Decimal("0.00")
            row["discounted_amount"] = Decimal("0.00")
            row["seller_discount"] = Decimal("0.00")
            row["product_discount"] = Decimal("0.00")
            row["coupon_discount"] = Decimal("0.00")
            row["commission"] = Decimal("0.00")
            row["gateway_fee"] = Decimal("0.00")
            row["shipping"] = Decimal("0.00")
            row["return_shipping"] = Decimal("0.00")
            row["gst"] = Decimal("0.00")
            row["tds"] = Decimal("0.00")
            row["total_deductions"] = Decimal("0.00")
            row["net_amount"] = Decimal("0.00")
            row["status"] = order.get_order_status_display()
    return sorted(rows.values(), key=lambda row: (row["order_id"], row["item_id"]))


def _attach_order_breakdown_rows(page_obj, seller):
    for payout_summary in page_obj.object_list:
        _decorate_payout_summary(payout_summary)
        payout_summary.item_rows = _build_order_item_breakdown_rows(seller=seller, order=payout_summary.order)
    return page_obj


def _registration_status_redirect(profile):
    status_url = reverse("sellers:registration_status")
    if profile and profile.registration_id:
        return redirect(f"{status_url}?registration_id={profile.registration_id}")
    return redirect(status_url)


def _get_approved_seller_or_redirect(request):
    seller = SellerProfile.objects.filter(user=request.user).first()
    if not seller:
        return None, redirect("sellers:create_profile")
    if not seller.is_approved:
        messages.info(
            request,
            "Your seller profile is pending admin approval. Track status using your registration ID.",
        )
        return None, _registration_status_redirect(seller)
    return seller, None


@login_required
@never_cache
def seller_dashboard(request):
    seller = SellerProfile.objects.filter(user=request.user).first()
    if not seller:
        return redirect("sellers:create_profile")
    if not seller.is_approved:
        return _registration_status_redirect(seller)

    seller_products = SellerProduct.objects.filter(seller=seller).select_related("product")
    total_reviews_count = Review.objects.filter(product__seller_product__seller=seller).count()
    payouts = list(
        SellerPayout.objects.filter(seller=seller).exclude(
            order_item__order__status=Order.STATUS_CANCELLED,
        ).exclude(
            order_item__order__order_status=Order.ORDER_STATUS_CANCELLED,
        ).select_related(
            "order_item", "order_item__order", "order_item__product"
        )
    )
    notifications_qs = SellerNotification.objects.filter(
        recipient=request.user,
        notification_type__in=[
            SellerNotification.TYPE_SELLER_ORDER,
            SellerNotification.TYPE_DELIVERY_UPDATE,
        ],
    ).select_related(
        "order_item",
        "order_item__product",
        "order_item__order",
    ).order_by("-created_at", "-id")
    unread_notification_count = notifications_qs.filter(is_read=False).count()
    # notifications = notifications_qs[:10]
    notifications = list(notifications_qs)
    for notification in notifications:
        notification.display_message = _format_notification_message(notification)
    financial_snapshot = WalletService.get_financial_snapshot(seller)
    wallet = financial_snapshot["wallet"]
    sales_snapshot = _build_product_sales_snapshot(payouts, seller_products)
    order_earnings = SellerOrderPayout.objects.filter(seller=seller).exclude(
        order__status=Order.STATUS_CANCELLED,
    ).select_related("order")[:10]
    recent_ledger_entries = SellerLedger.objects.filter(seller=seller).select_related("order")[:10]
    payout_history = _build_recent_payout_runs(seller, limit=8)

    active_payouts = []
    completed_payouts = []
    for payout in payouts:
        is_completed = payout.delivery_status == SellerPayout.DELIVERY_DELIVERED
        if is_completed:
            completed_payouts.append(payout)
        else:
            active_payouts.append(payout)

    from orders.models import ReturnRequest
    # Returns that need attention from the seller (shipped by buyer or already received)
    seller_returns = ReturnRequest.objects.filter(
        product__seller_product__seller=seller,
        status__in=[
            ReturnRequest.STATUS_SHIPPED_BY_BUYER,
            ReturnRequest.STATUS_RECEIVED_BY_SELLER,
        ]
    ).select_related('order', 'product', 'user').order_by('-updated_at')
    pending_seller_returns_count = seller_returns.filter(
        status=ReturnRequest.STATUS_SHIPPED_BY_BUYER
    ).count()
    total_orders_count = len(active_payouts)

    return render(
        request,
        "sellers/dashboard.html",
        {
            "seller": seller,
            "seller_products": seller_products,
            "payouts": payouts,
            "active_payouts": active_payouts,
            "completed_payouts": completed_payouts,
            "notifications": notifications,
            "unread_notification_count": unread_notification_count,
            "own_delivery_status_choices": SellerPayout.own_delivery_status_choices(),
            "hub_delivery_status_choices": SellerPayout.DELIVERY_STATUS_CHOICES,
            "total_reviews_count": total_reviews_count,
            "total_orders_count": total_orders_count,
            "total_returns_count": seller_returns.count(),
            "seller_wallet": wallet,
            "wallet_balance": financial_snapshot["wallet_balance"],
            "total_sales_amount": sales_snapshot["total_sales_amount"],
            "product_sales_chart": sales_snapshot["top_products"],
            "product_sales_count": sales_snapshot["product_count"],
            "sales_chart_background": sales_snapshot["chart_background"],
            "order_earnings": order_earnings,
            "recent_ledger_entries": recent_ledger_entries,
            "payout_history": payout_history,
            "seller_returns": seller_returns,
            "pending_seller_returns_count": pending_seller_returns_count,
        },
    )


@login_required
@require_POST
def mark_notification_as_read(request, notification_id):
    seller, redirect_response = _get_approved_seller_or_redirect(request)
    if redirect_response:
        return redirect_response

    notification = get_object_or_404(
        SellerNotification,
        id=notification_id,
        recipient=request.user,
        notification_type__in=[
            SellerNotification.TYPE_SELLER_ORDER,
            SellerNotification.TYPE_DELIVERY_UPDATE,
        ],
    )

    if not notification.is_read:
        notification.is_read = True
        notification.save(update_fields=["is_read"])

    return redirect(f"{reverse('sellers:dashboard')}?panel=notifications")


@login_required
def create_seller_profile(request):
    existing_profile = SellerProfile.objects.filter(user=request.user).first()
    if existing_profile:
        if existing_profile.is_approved:
            return redirect("sellers:dashboard")
        return _registration_status_redirect(existing_profile)

    draft = _get_registration_draft(request)
    has_saved_signature = bool((draft or {}).get("seller_signature_temp_path"))

    if request.method == "POST":
        form = SellerProfileRegistrationForm(
            request.POST,
            request.FILES,
            has_saved_signature=has_saved_signature,
        )
        if form.is_valid():
            request.session[SELLER_REGISTRATION_DRAFT_SESSION_KEY] = _build_registration_draft(form, request)
            request.session.modified = True
            return redirect("sellers:review_profile")
        messages.error(request, "Please fix the highlighted form errors and continue again.")
    else:
        form = SellerProfileRegistrationForm(
            initial=_build_registration_form_initial(draft),
            has_saved_signature=has_saved_signature,
        )

    return render(
        request,
        "sellers/profile_form.html",
        {
            "form": form,
            "saved_signature_name": (draft or {}).get("seller_signature_name", ""),
        },
    )


@login_required
@never_cache
def review_seller_profile(request):
    existing_profile = SellerProfile.objects.filter(user=request.user).first()
    if existing_profile:
        if existing_profile.is_approved:
            return redirect("sellers:dashboard")
        return _registration_status_redirect(existing_profile)

    draft = _get_registration_draft(request)
    if not draft:
        messages.info(request, "Complete the seller registration form before reviewing it.")
        return redirect("sellers:create_profile")

    if request.method == "POST":
        action = (request.POST.get("action") or "").strip()
        if action == "edit":
            return redirect("sellers:create_profile")
        if action == "confirm":
            try:
                profile = _create_seller_profile_from_draft(request, draft)
            except FileNotFoundError:
                messages.error(request, "Your saved signature could not be found. Please upload it again.")
                _clear_registration_draft(request)
                return redirect("sellers:create_profile")
            _clear_registration_draft(request)
            messages.success(
                request,
                f"Registration submitted to admin. Your registration ID is {profile.registration_id}.",
            )
            return _registration_status_redirect(profile)

    return render(
        request,
        "sellers/profile_review.html",
        {
            "review_sections": _build_registration_review_sections(draft),
        },
    )



@login_required
def withdraw_registration(request):
    if request.method != "POST":
        return redirect("sellers:registration_status")

    registration_id = (request.POST.get("registration_id") or "").strip()
    profile = SellerProfile.objects.filter(
        registration_id=registration_id,
        user=request.user,
    ).first()

    if profile is None:
        messages.error(request, "Pending seller registration not found.")
        return redirect("sellers:registration_status")

    if profile.approval_status != SellerProfile.STATUS_PENDING:
        messages.error(request, "Only pending seller registrations can be withdrawn.")
        return redirect(f"{reverse('sellers:registration_status')}?registration_id={profile.registration_id}")

    profile.delete()
    _clear_registration_draft(request)
    messages.success(request, "Seller registration withdrawn successfully.")
    return redirect("sellers:create_profile")
def registration_status(request):
    registration_id = ""
    tracked_profile = None
    has_searched = False
    lookup_error = ""

    if request.method == "POST":
        registration_id = (request.POST.get("registration_id") or "").strip()
    else:
        registration_id = (request.GET.get("registration_id") or "").strip()

    if registration_id:
        has_searched = True
        tracked_profile = (
            SellerProfile.objects.filter(registration_id=registration_id)
            .select_related("user")
            .first()
        )
        if tracked_profile is None:
            lookup_error = "No registration found for that ID."
    elif request.method == "POST":
        has_searched = True
        lookup_error = "Enter a registration ID to track your application."

    return render(
        request,
        "sellers/registration_status.html",
        {
            "registration_id": registration_id,
            "tracked_profile": tracked_profile,
            "has_searched": has_searched,
            "lookup_error": lookup_error,
        },
    )



@login_required
def publish_product(request):
    seller, redirect_response = _get_approved_seller_or_redirect(request)
    if redirect_response:
        return redirect_response

    submission_key = _issue_publish_submission_key(request)

    if request.method == "POST":
        posted_submission_key = (request.POST.get("submission_key") or "").strip()
        last_processed_key = request.session.get(PUBLISH_LAST_PROCESSED_SESSION_KEY)
        if posted_submission_key != submission_key:
            if posted_submission_key and posted_submission_key == last_processed_key:
                logger.info(
                    "Ignored duplicate seller publish submission",
                    extra={"seller_id": seller.id, "submission_key": posted_submission_key},
                )
                messages.info(request, "This publish request was already processed.")
                return redirect("sellers:dashboard")
            logger.warning(
                "Rejected seller publish submission with invalid key",
                extra={
                    "seller_id": seller.id,
                    "expected_submission_key": submission_key,
                    "posted_submission_key": posted_submission_key,
                },
            )
            messages.error(request, "Your publish session expired. Please review the form and submit again.")
            product_formset = SellerProductEntryFormSet(
                request.POST,
                request.FILES,
                prefix="products",
            )
            settings_form = SellerProductSharedSettingsForm(request.POST, prefix="settings")
            coupon_form = SellerCouponForm(request.POST, prefix="coupon", seller=seller)
            submission_key = _issue_publish_submission_key(request, refresh=True)
            return render(
                request,
                "sellers/publish_product.html",
                {
                    "product_formset": product_formset,
                    "settings_form": settings_form,
                    "coupon_form": coupon_form,
                    "seller": seller,
                    "payout_preview_config": PayoutCalculator().config,
                    "submission_key": submission_key,
                },
            )
        product_formset = SellerProductEntryFormSet(
            request.POST,
            request.FILES,
            prefix="products",
        )
        settings_form = SellerProductSharedSettingsForm(request.POST, prefix="settings")
        coupon_form = SellerCouponForm(request.POST, prefix="coupon", seller=seller)
        if product_formset.is_valid() and settings_form.is_valid() and coupon_form.is_valid():
            created_count = 0
            try:
                with transaction.atomic():
                    shared_settings = settings_form.cleaned_data.copy()
                    created_products = []
                    for form in product_formset:
                        if not form.has_meaningful_input():
                            continue
                        seller_product = form.save(seller=seller, shared_settings=shared_settings)
                        created_products.append(seller_product.product)
                        created_count += 1
                    coupon_form.save(seller=seller, products=created_products)
            except Exception:
                logger.exception(
                    "Seller product publish failed",
                    extra={"seller_id": seller.id, "product_count": created_count},
                )
                messages.error(request, "We could not publish your products right now. Please try again.")
            else:
                request.session[PUBLISH_LAST_PROCESSED_SESSION_KEY] = posted_submission_key
                submission_key = _issue_publish_submission_key(request, refresh=True)
                logger.info(
                    "Seller products published successfully",
                    extra={"seller_id": seller.id, "created_count": created_count},
                )
                messages.success(
                    request,
                    f"{created_count} product{'s' if created_count != 1 else ''} submitted for admin review.",
                )
                return redirect("sellers:dashboard")
        else:
            logger.warning(
                "Seller publish validation failed",
                extra={
                    "seller_id": seller.id,
                    "product_formset_errors": product_formset.errors,
                    "product_formset_non_form_errors": product_formset.non_form_errors(),
                    "settings_form_errors": settings_form.errors,
                    "coupon_form_errors": coupon_form.errors,
                },
            )
            messages.error(request, "Please fix the highlighted form errors and submit again.")
    else:
        product_formset = SellerProductEntryFormSet(prefix="products")
        settings_form = SellerProductSharedSettingsForm(prefix="settings")
        coupon_form = SellerCouponForm(prefix="coupon", seller=seller)

    return render(
        request,
        "sellers/publish_product.html",
        {
            "product_formset": product_formset,
            "settings_form": settings_form,
            "coupon_form": coupon_form,
            "seller": seller,
            "category_tax_data": _category_tax_data(),
            "payout_preview_config": PayoutCalculator().config,
            "submission_key": submission_key,
        },
    )


@login_required
def edit_product(request, seller_product_id):
    seller, redirect_response = _get_approved_seller_or_redirect(request)
    if redirect_response:
        return redirect_response

    seller_product = get_object_or_404(
        SellerProduct.objects.select_related("product").prefetch_related("product__images"),
        id=seller_product_id,
        seller=seller,
    )

    if request.method == "POST":
        form = SellerProductPublishForm(request.POST, request.FILES, instance=seller_product)
        if form.is_valid():
            form.save(seller=seller)
            messages.success(request, "Product updated and sent for admin review.")
            return redirect("sellers:dashboard")
        messages.error(request, "Please fix the highlighted form errors and submit again.")
    else:
        form = SellerProductPublishForm(instance=seller_product)

    return render(
        request,
        "sellers/edit_product.html",
        {
            "form": form,
            "seller": seller,
            "seller_product": seller_product,
            "category_tax_data": _category_tax_data(),
            "payout_preview_config": PayoutCalculator().config,
        },
    )


@login_required
def delete_product(request, seller_product_id):
    seller, redirect_response = _get_approved_seller_or_redirect(request)
    if redirect_response:
        return redirect_response

    seller_product = get_object_or_404(
        SellerProduct.objects.select_related("product"),
        id=seller_product_id,
        seller=seller,
    )

    if request.method == "POST":
        seller_product.product.delete()
        messages.success(request, "Product deleted successfully.")

    return redirect("sellers:dashboard")


@login_required
def update_own_delivery_status(request, payout_id):
    seller, redirect_response = _get_approved_seller_or_redirect(request)
    if redirect_response:
        return redirect_response

    payout = get_object_or_404(
        SellerPayout.objects.select_related("order_item", "order_item__product"),
        id=payout_id,
        seller=seller,
    )
    requested_panel = (request.POST.get("panel_context") or request.GET.get("panel") or "").strip()
    if requested_panel not in {"active-payouts", "completed-orders"}:
        requested_panel = "active-payouts"
    dashboard_redirect = f"{reverse('sellers:dashboard')}?panel={requested_panel}"
    wants_json = request.headers.get("x-requested-with") == "XMLHttpRequest"

    def _json_error(message, *, status=400):
        return JsonResponse({"ok": False, "message": message}, status=status)

    def _redirect_or_json_error(message, *, status=400):
        if wants_json:
            return _json_error(message, status=status)
        messages.error(request, message)
        return redirect(dashboard_redirect)

    if request.method != "POST":
        if wants_json:
            return _json_error("Invalid request method.", status=405)
        return redirect(dashboard_redirect)

    if payout.delivery_mode == SellerProduct.OWN_DELIVERY:
        allowed_statuses = {value for value, _ in SellerPayout.own_delivery_status_choices()}
    else:
        allowed_statuses = {value for value, _ in SellerPayout.DELIVERY_STATUS_CHOICES}
    new_status = request.POST.get("delivery_status", "").strip()
    note = request.POST.get("delivery_status_note", "").strip()
    courier_number = request.POST.get("courier_number", "").strip()
    courier_slip = request.FILES.get("courier_slip")

    if new_status not in allowed_statuses:
        return _redirect_or_json_error("Invalid delivery status selected.")
    
    if new_status == SellerPayout.DELIVERY_DELIVERED and payout.delivery_mode == SellerProduct.OWN_DELIVERY:
        if not courier_number and not payout.courier_number:
            return _redirect_or_json_error("Courier number is required before marking this order as delivered.") 
        if not courier_slip and not payout.courier_slip:
            return _redirect_or_json_error("Courier slip image is required before marking this order as delivered.")
           
        if payout.status != SellerPayout.STATUS_PAID:
            payout.status = SellerPayout.STATUS_PROCESSING
    elif payout.status != SellerPayout.STATUS_PAID:
        payout.status = SellerPayout.STATUS_PENDING

    payout.delivery_status = new_status
    payout.delivery_status_note = note
    if courier_number:
        payout.courier_number = courier_number
    if courier_slip:
        payout.courier_slip = courier_slip
    payout.delivery_status_updated_by = request.user
    payout.delivery_status_updated_at = timezone.now()
    payout.save()

    order = payout.order_item.order
    if order.status not in {Order.STATUS_CANCELLED, Order.STATUS_PARTIALLY_CANCELLED}:
        previous_status = order.status
        order.status = order.resolve_fulfillment_status()
        if order.status != previous_status:
            order.save(update_fields=["status", "updated_at"])
            transaction.on_commit(lambda: handle_order_status_change(order))

    if new_status == SellerPayout.DELIVERY_DELIVERED and payout.delivery_mode == SellerProduct.OWN_DELIVERY:
        admin_message = (
            f"Seller {seller.business_name} marked order {payout.order_item.order.display_order_id} "
            f"({payout.order_item.product.name}) as Delivered with courier proof "
            f"(No: {payout.courier_number}). Ready for payout release."
        )
    else:
        admin_message = (
            f"Seller {seller.business_name} updated delivery status for order "
            f"{payout.order_item.order.display_order_id} ({payout.order_item.product.name}) to "
            f"{payout.get_delivery_status_display()}."
        )
    User = get_user_model()
    for admin_user in User.objects.filter(is_staff=True, is_active=True):
        SellerNotification.objects.update_or_create(
            recipient=admin_user,
            order_item=payout.order_item,
            notification_type=SellerNotification.TYPE_DELIVERY_UPDATE,
            defaults={"message": admin_message, "is_read": False},
        )

    if wants_json:
        return JsonResponse(
            {
                "ok": True,
                "message": "Delivery status updated.",
                "delivery_status": payout.delivery_status,
                "delivery_status_display": payout.get_delivery_status_display(),
                "delivery_status_updated_at": timezone.localtime(payout.delivery_status_updated_at).strftime("%b %d, %Y %I:%M %p") if payout.delivery_status_updated_at else "",
                "courier_number": payout.courier_number or "",
                "has_courier_slip": bool(payout.courier_slip),
                "courier_slip_url": payout.courier_slip.url if payout.courier_slip else "",
                "delivery_status_note": payout.delivery_status_note or "",
            }
        )

    messages.success(request, "Delivery status updated.")
    return redirect(dashboard_redirect)


@login_required
def seller_review_list(request):
    """Seller view to see reviews of their products and moderation history."""
    seller_profile, redirect_response = _get_approved_seller_or_redirect(request)
    if redirect_response:
        return redirect_response

    from products.models import Product
    from orders.models import Review, ReviewReport

    seller_products = Product.objects.filter(seller_product__seller=seller_profile)
    reviews = Review.objects.filter(
        product__in=seller_products,
    ).select_related("user", "product").prefetch_related("images", "reports").order_by("-created_at")
    seller_reported_review_ids = set(
        ReviewReport.objects.filter(
            review__product__in=seller_products,
            reported_by=request.user,
        ).values_list("review_id", flat=True)
    )
    report_history = ReviewReport.objects.filter(
        review__product__in=seller_products,
        reported_by=request.user,
    ).select_related("review", "review__product").order_by("-created_at")

    product_stats = []
    for product in seller_products:
        product_reviews = reviews.filter(product=product)
        avg_rating = product_reviews.aggregate(Avg("rating"))["rating__avg"]
        total_reviews = product_reviews.count()
        product_stats.append(
            {
                "product": product,
                "avg_rating": avg_rating,
                "total_reviews": total_reviews,
                "reviews": product_reviews[:5],
            }
        )

    return render(
        request,
        "sellers/seller_reviews.html",
        {
            "product_stats": product_stats,
            "seller": seller_profile,
            "seller_reported_review_ids": seller_reported_review_ids,
            "report_history": report_history,
            "review_report_reason_choices": ReviewReportForm.REASON_CHOICES,
        },
    )


@login_required
@never_cache
def seller_wallet_summary(request):
    seller, redirect_response = _get_approved_seller_or_redirect(request)
    if redirect_response:
        return redirect_response

    financial_snapshot = _build_display_financial_snapshot(seller)
    return render(
        request,
        "sellers/wallet_summary.html",
        {
            "seller": seller,
            "wallet": financial_snapshot["wallet"],
            "pending_payout": financial_snapshot["pending_payout"],
            "paid_payout": financial_snapshot["paid_payout"],
            "wallet_balance": financial_snapshot["wallet_balance"],
            "earnings": financial_snapshot["earnings"],
        },
    )


@login_required
@never_cache
def seller_ledger_history(request):
    seller, redirect_response = _get_approved_seller_or_redirect(request)
    if redirect_response:
        return redirect_response

    ledger_page = Paginator(
        SellerOrderPayout.objects.filter(seller=seller).select_related("order").order_by("-updated_at", "-id"),
        15,
    ).get_page(request.GET.get("page"))
    ledger_page = _attach_order_breakdown_rows(ledger_page, seller)
    return render(
        request,
        "sellers/ledger_history.html",
        {
            "seller": seller,
            "ledger_page": ledger_page,
        },
    )


@login_required
@never_cache
def seller_payout_history(request):
    seller, redirect_response = _get_approved_seller_or_redirect(request)
    if redirect_response:
        return redirect_response

    status_filter = request.GET.get('status', '')
    date_from = request.GET.get('date_from', '')
    date_to = request.GET.get('date_to', '')

    payout_runs = _build_recent_payout_runs(seller)

    if status_filter:
        payout_runs = [run for run in payout_runs if run["status"] == status_filter]

    if date_from:
        try:
            from_date = timezone.datetime.fromisoformat(date_from).date()
            payout_runs = [run for run in payout_runs if run["created_at"] and timezone.localtime(run["created_at"]).date() >= from_date]
        except ValueError:
            pass

    if date_to:
        try:
            to_date = timezone.datetime.fromisoformat(date_to).date()
            payout_runs = [run for run in payout_runs if run["created_at"] and timezone.localtime(run["created_at"]).date() <= to_date]
        except ValueError:
            pass

    payout_page = Paginator(payout_runs, 25).get_page(request.GET.get("page"))

    return render(
        request,
        "sellers/payout_history.html",
        {
            "seller": seller,
            "payout_page": payout_page,
            "status_choices": Payout.STATUS_CHOICES,
            "filters": {
                "status": status_filter,
                "date_from": date_from,
                "date_to": date_to,
            },
        },
    )


@login_required
@never_cache
def seller_order_earnings(request, order_id):
    seller, redirect_response = _get_approved_seller_or_redirect(request)
    if redirect_response:
        return redirect_response

    order = get_object_or_404(Order, id=order_id)
    payout_summary = get_object_or_404(SellerOrderPayout.objects.select_related("order"), seller=seller, order=order)
    _decorate_payout_summary(payout_summary)
    ledger_entries = SellerLedger.objects.filter(seller=seller, order=order).order_by("-created_at")
    calculator = PayoutCalculator()
    return render(
        request,
        "sellers/order_earnings_detail.html",
        {
            "seller": seller,
            "order": order,
            "payout_summary": payout_summary,
            "ledger_entries": ledger_entries,
            "calculation_preview": calculator.aggregate_for_seller_order(seller, order),
            "item_rows": _build_order_item_breakdown_rows(seller=seller, order=order),
        },
    )


@login_required
def trigger_manual_payout(request):
    seller, redirect_response = _get_approved_seller_or_redirect(request)
    if redirect_response:
        return redirect_response

    if request.method != "POST":
        return redirect("sellers:wallet_summary")

    try:
        payout = PayoutService().release_available_balance(
            seller=seller,
            idempotency_key=f"manual-payout:{seller.id}:{timezone.now().timestamp()}",
        )
        if payout.status == Payout.STATUS_COMPLETED:
            messages.success(request, f"Payout completed with reference {payout.reference}.")
        else:
            messages.warning(request, f"Payout created with status {payout.get_status_display()}.")
    except Exception as exc:
        messages.error(request, str(exc))
    return redirect("sellers:wallet_summary")




@login_required
@never_cache
def seller_invoice(request, order_id):
    seller, redirect_response = _get_approved_seller_or_redirect(request)
    if redirect_response:
        return redirect_response

    return_panel = (request.GET.get("panel") or "").strip()
    if return_panel not in {"active-payouts", "completed-orders", "notifications", "products", "dashboard"}:
        return_panel = "dashboard"

    order = get_object_or_404(
        Order.objects.prefetch_related("items", "items__product"),
        id=order_id,
    )

    seller_items = []
    seller_total = Decimal("0.00")
    taxable_total = Decimal("0.00")
    gst_total = Decimal("0.00")
    payout_items = (
        SellerPayout.objects.filter(
            seller=seller,
            order_item__order=order,
        )
        .select_related("order_item", "order_item__product")
        .order_by("order_item_id")
    )

    seller_state = _extract_invoice_state(getattr(seller, "registered_office_address", ""))

    for payout in payout_items:
        item = payout.order_item
        item_total = Decimal(str(getattr(item, "total_price", None) or item.get_net_cost()))
        item_price = Decimal(str(getattr(item, "price", getattr(item.product, "price", 0)) or 0))
        discount_amount = (item.get_cost() - item.get_net_cost()).quantize(Decimal("0.01"))
        if discount_amount < 0:
            discount_amount = Decimal("0.00")
        taxable_amount = Decimal(str(item.taxable_subtotal or 0)).quantize(Decimal("0.01"))
        tax_amount = Decimal(str(item.gst_subtotal or 0)).quantize(Decimal("0.01"))

        seller_items.append({
            "item": item,
            "quantity": getattr(item, "quantity", 1),
            "price": item_price,
            "total": item_total,
            "discount_amount": discount_amount,
            "taxable_amount": taxable_amount,
            "tax_rate": Decimal(str(getattr(item, "gst_rate", 0) or 0)).quantize(Decimal("0.01")),
            "tax_amount": tax_amount,
        })

        seller_total += item_total
        taxable_total += taxable_amount
        gst_total += tax_amount

    if not seller_items:
        for item in order.items.all():
            seller_product = getattr(item.product, "seller_product", None)

            if seller_product and seller_product.seller_id == seller.id:
                item_total = Decimal(str(getattr(item, "total_price", None) or item.get_net_cost()))
                discount_amount = (item.get_cost() - item.get_net_cost()).quantize(Decimal("0.01"))
                if discount_amount < 0:
                    discount_amount = Decimal("0.00")
                taxable_amount = Decimal(str(item.taxable_subtotal or 0)).quantize(Decimal("0.01"))
                tax_amount = Decimal(str(item.gst_subtotal or 0)).quantize(Decimal("0.01"))

                seller_items.append({
                    "item": item,
                    "quantity": getattr(item, "quantity", 1),
                    "price": getattr(item, "price", getattr(item.product, "price", 0)),
                    "total": item_total,
                    "discount_amount": discount_amount,
                    "taxable_amount": taxable_amount,
                    "tax_rate": Decimal(str(getattr(item, "gst_rate", 0) or 0)).quantize(Decimal("0.01")),
                    "tax_amount": tax_amount,
                })

                seller_total += item_total
                taxable_total += taxable_amount
                gst_total += tax_amount

    # If seller has no items in this order → go back to dashboard
    if not seller_items:
        messages.error(request, "Invoice is not available for this order.")
        return redirect("sellers:dashboard")

    payment_txn = None
    if hasattr(order, "payment_transactions"):
        payment_txn = order.payment_transactions.first()

    buyer_profile = Profile.objects.filter(user=order.user).first() if order.user_id else None
    default_address = Address.objects.filter(user=order.user, is_default=True).first() if order.user_id else None

    billing_details = _build_invoice_party_details(
        name=getattr(buyer_profile, "full_name", "") or order.full_name,
        email=order.email or getattr(order.user, "email", ""),
        phone=getattr(buyer_profile, "phone_number", "") or order.phone_number,
        address_line=getattr(default_address, "address_line", "") or getattr(buyer_profile, "address_line", ""),
        city=getattr(default_address, "city", "") or getattr(buyer_profile, "city", ""),
        state=getattr(default_address, "state", "") or getattr(buyer_profile, "state", ""),
        pincode=getattr(default_address, "pincode", "") or getattr(buyer_profile, "pincode", ""),
        country=getattr(default_address, "country", "") or getattr(buyer_profile, "country", ""),
    )

    if billing_details["address"] == "-":
        billing_details = _build_invoice_party_details(
            name=order.full_name,
            email=order.email,
            phone=order.phone_number,
            address_line=order.address,
            city=order.city,
            state=order.state,
            pincode=order.pincode,
            country=order.country,
        )

    shipping_details = _build_invoice_party_details(
        name=order.full_name,
        email=order.email,
        phone=order.phone_number,
        address_line=order.address,
        city=order.city,
        state=order.state,
        pincode=order.pincode,
        country=order.country,
    )

    shipping_state = shipping_details.get("state", "")
    tax_type = _get_invoice_tax_type(seller_state, shipping_state)
    invoice_total = (taxable_total + gst_total).quantize(Decimal("0.01"))

    for entry in seller_items:
        entry["tax_type"] = tax_type
        entry["gross_total"] = (entry["taxable_amount"] + entry["tax_amount"]).quantize(Decimal("0.01"))

    context = {
        "seller": seller,
        "order": order,
        "seller_items": seller_items,
        "seller_total": seller_total,
        "seller_total_words": _amount_to_words(invoice_total),
        "payment_txn": payment_txn,
        "billing_details": billing_details,
        "shipping_details": shipping_details,
        "seller_state": seller_state or "-",
        "seller_state_code": _get_invoice_state_code(seller_state),
        "tax_type": tax_type,
        "taxable_total": taxable_total.quantize(Decimal("0.01")),
        "gst_total": gst_total.quantize(Decimal("0.01")),
        "invoice_total": invoice_total,
        "place_of_supply": shipping_state or "-",
        "return_panel": return_panel,
    }

    return render(request, "sellers/sellers_invoice.html", context)


@staff_member_required
@never_cache
def admin_payout_management(request):
    """Admin view for managing seller payouts across all sellers."""
    sellers = SellerProfile.objects.filter(approval_status=SellerProfile.STATUS_APPROVED).select_related('user')
    
    seller_data = []
    for seller in sellers:
        try:
            snapshot = WalletService.get_financial_snapshot(seller)
            wallet = snapshot['wallet']
            seller_data.append({
                'seller': seller,
                'pending_balance': wallet.pending_balance,
                'hold_balance': wallet.hold_balance,
                'available_balance': wallet.available_balance,
                'paid_balance': wallet.paid_balance,
                'total_earnings': snapshot['wallet_balance'],
                'last_payout': Payout.objects.filter(seller=seller).order_by('-created_at').first(),
                'total_payouts': Payout.objects.filter(seller=seller, status=Payout.STATUS_COMPLETED).count(),
            })
        except Exception as e:
            seller_data.append({
                'seller': seller,
                'pending_balance': Decimal('0.00'),
                'hold_balance': Decimal('0.00'),
                'available_balance': Decimal('0.00'),
                'paid_balance': Decimal('0.00'),
                'total_earnings': Decimal('0.00'),
                'last_payout': None,
                'total_payouts': 0,
                'error': str(e),
            })
    
    # Sort by available balance descending
    seller_data.sort(key=lambda x: x['available_balance'], reverse=True)
    
    return render(request, 'admin/sellers/payout_management.html', {
        'seller_data': seller_data,
        'title': 'Seller Payout Management',
    })


@staff_member_required
def admin_release_payout(request, seller_id):
    """Admin endpoint to release payout for a specific seller."""
    if request.method != 'POST':
        return redirect('sellers:admin_payout_management')
    
    try:
        seller = SellerProfile.objects.get(id=seller_id, approval_status=SellerProfile.STATUS_APPROVED)
        payout = PayoutService().release_available_balance(
            seller=seller,
            idempotency_key=f"admin-manual:{seller.id}:{timezone.now().timestamp()}",
        )
        messages.success(request, f"Payout released for {seller.business_name}. Amount: ₹{payout.amount}")
    except SellerProfile.DoesNotExist:
        messages.error(request, "Seller not found or not approved.")
    except Exception as e:
        messages.error(request, f"Failed to release payout: {str(e)}")
    
    return redirect('sellers:admin_payout_management')


@login_required
@never_cache
def seller_returns(request):
    """View to list returns assigned to the logged in seller"""
    seller, redirect_response = _get_approved_seller_or_redirect(request)
    if redirect_response:
        return redirect_response

    from orders.models import ReturnRequest

    returns = ReturnRequest.objects.filter(
        product__seller_product__seller=seller,
        status__in=[ReturnRequest.STATUS_SHIPPED_BY_BUYER, ReturnRequest.STATUS_RECEIVED_BY_SELLER]
    ).select_related('order', 'product', 'user').prefetch_related('images').order_by('-updated_at')

    return render(request, "sellers/seller_returns.html", {
        "seller": seller,
        "returns": returns
    })

@login_required
@require_POST
def mark_return_received(request, return_id):
    """Seller marks a returned item as received"""
    seller, redirect_response = _get_approved_seller_or_redirect(request)
    if redirect_response:
        return redirect_response

    from orders.models import ReturnRequest

    return_request = get_object_or_404(
        ReturnRequest,
        id=return_id,
        product__seller_product__seller=seller
    )

    if return_request.status == ReturnRequest.STATUS_SHIPPED_BY_BUYER:
        return_request.status = ReturnRequest.STATUS_RECEIVED_BY_SELLER
        return_request.save(update_fields=["status", "updated_at"])
        messages.success(request, "Return marked as received successfully.")
    else:
        messages.error(request, "This return cannot be marked as received.")

    return redirect('sellers:returns')
