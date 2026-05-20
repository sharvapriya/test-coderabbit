import asyncio
import hashlib
import hmac
import json
import logging
import time
from decimal import Decimal, ROUND_HALF_UP

import razorpay
from asgiref.sync import sync_to_async
from django.conf import settings
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.http import HttpRequest, JsonResponse
from django.shortcuts import redirect, render
from django.urls import reverse
from django.views.decorators.http import require_GET, require_http_methods, require_POST

from .models import Order, PaymentTransaction
from .views import (
    _build_checkout_context,
    _get_checkout_cart_or_redirect,
    _get_selected_payment_method,
    
)



logger = logging.getLogger("orders.payment")


def _resolve_authenticated_user(request: HttpRequest):
    user = getattr(request, "user", None)
    if user and user.is_authenticated:
        return user
    return None


def _read_json_body(request: HttpRequest) -> dict:
    try:
        return json.loads(request.body.decode("utf-8") or "{}")
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError("Invalid JSON payload.") from exc


def _decimal_to_paise(amount: Decimal) -> int:
    normalized = Decimal(amount or "0").quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    if normalized <= 0:
        return 0
    return int((normalized * 100).to_integral_value(rounding=ROUND_HALF_UP))


def _clear_checkout_payment_session(request: HttpRequest, *, keep_selection: bool = True) -> None:
    keys_to_clear = [
        "online_payment_confirmed",
        "razorpay_order_id",
        "razorpay_payment_id",
        "razorpay_signature",
        "razorpay_transaction_id",
        "razorpay_amount",
        "razorpay_amount_paise",
    ]
    if not keep_selection:
        keys_to_clear.extend(["checkout_payment_method", "checkout_use_wallet"])
    for key in keys_to_clear:
        request.session.pop(key, None)


def _build_razorpay_client() -> razorpay.Client:
    return razorpay.Client(
        auth=(settings.RAZORPAY_KEY_ID, settings.RAZORPAY_KEY_SECRET),
    )


def _create_remote_order(order_payload: dict) -> dict:
    client = _build_razorpay_client()
    return client.order.create(
        data=order_payload,
        timeout=settings.RAZORPAY_REQUEST_TIMEOUT_SECONDS,
    )


def _get_checkout_state(request: HttpRequest):
    cart = _get_checkout_cart_or_redirect(request)
    if not cart:
        return None, None, None

    cart_items = list(cart.items.select_related("product", "variant"))
    selected_payment_method = _get_selected_payment_method(request)
    checkout = _build_checkout_context(request, cart_items, payment_method=selected_payment_method)
    return cart, cart_items, checkout


def _build_payment_template_context(request: HttpRequest, checkout: dict, cart_items: list):
    already_paid = bool(request.session.get("online_payment_confirmed", False))
    remaining_payable = checkout["remaining_payable"]
    return {
        "cart_items": cart_items,
        "razorpay_key_id": settings.RAZORPAY_KEY_ID,
        "razorpay_currency": settings.RAZORPAY_CURRENCY,
        "subtotal": checkout["subtotal"],
        "discount_amount": checkout["discount_amount"],
        "discount_percent": checkout["discount_percent"],
        "coupon_code": checkout["coupon_code"],
        "wallet_balance": checkout["wallet_balance"],
        "wallet_eligible": checkout["wallet_eligible"],
        "wallet_applied": checkout["wallet_applied"],
        "final_total": checkout["final_total"],
        "remaining_payable": remaining_payable,
        "remaining_payable_paise": _decimal_to_paise(remaining_payable),
        "selected_payment_method": checkout["selected_payment_method"],
        "effective_payment_method": checkout["effective_payment_method"],
        "wallet_only": checkout["wallet_only"],
        "wallet_requires_online": checkout["wallet_requires_online"],
        "available_offers": checkout["available_offers"],
        "online_payment_confirmed": already_paid,
        "razorpay_order_id": request.session.get("razorpay_order_id", ""),
    }


def _log_request_start(endpoint: str, request_id: str, payload: dict) -> None:
    logger.info(
        "payment_request_started",
        extra={"endpoint": endpoint, "request_id": request_id, "payload": payload},
    )


def _log_request_end(endpoint: str, request_id: str, started_at: float, status_code: int) -> None:
    logger.info(
        "payment_request_finished",
        extra={
            "endpoint": endpoint,
            "request_id": request_id,
            "duration_ms": round((time.monotonic() - started_at) * 1000, 2),
            "status_code": status_code,
        },
    )


@login_required
@require_http_methods(["GET", "POST"])
def payment_step(request: HttpRequest):
    cart, cart_items, checkout = _get_checkout_state(request)
    if not cart:
        return redirect("cart:cart_detail")

    if request.method == "GET":
        return render(
            request,
            "orders/payment_step.html",
            {
                "cart": cart,
                "cart_items": cart_items,
                **checkout,
            },
        )

    selected_option = (request.POST.get("payment_method") or Order.PAYMENT_ONLINE).strip()
    if selected_option not in {Order.PAYMENT_ONLINE, Order.PAYMENT_WALLET}:
        selected_option = Order.PAYMENT_ONLINE

    _clear_checkout_payment_session(request, keep_selection=False)

    # if selected_option == Order.PAYMENT_WALLET:
    #     request.session["checkout_use_wallet"] = True
    #     request.session["checkout_payment_method"] = (
    #         Order.PAYMENT_WALLET if checkout["wallet_balance"] >= checkout["final_total"] else Order.PAYMENT_ONLINE
    #     )
    # else:
    #     request.session["checkout_use_wallet"] = False
    #     request.session["checkout_payment_method"] = Order.PAYMENT_ONLINE

    # if selected_option == Order.PAYMENT_WALLET:
    if selected_option == Order.PAYMENT_WALLET and checkout["wallet_has_funds"]:
        request.session["checkout_use_wallet"] = True

        # allow partial wallet payment
        request.session["checkout_payment_method"] = Order.PAYMENT_ONLINE

    else:
        request.session["checkout_use_wallet"] = False
        request.session["checkout_payment_method"] = Order.PAYMENT_ONLINE

    request.session.modified = True

    _, _, updated_checkout = _get_checkout_state(request)
    if updated_checkout["wallet_only"]:
        messages.success(request, "Wallet balance covers this purchase. Continue to checkout details.")
        return redirect("orders:order_create")

    return redirect("orders:payment_online")

@login_required
@require_GET
def payment_online(request: HttpRequest):
    cart, cart_items, checkout = _get_checkout_state(request)
    if not cart:
        return redirect("cart:cart_detail")

    if checkout["wallet_only"]:
        return redirect("orders:order_create")

    return render(
        request,
        "orders/payment_checkout.html",
        _build_payment_template_context(request, checkout, cart_items),
    )


@login_required
@require_GET
def payment_checkout_page(request: HttpRequest):
    return payment_online(request)


@login_required
@require_POST
async def create_order(request: HttpRequest):
    request_id = request.headers.get("X-Request-ID") or f"rzp-create-{int(time.time() * 1000)}"
    started_at = time.monotonic()
    payment_transaction = None

    try:
        payload = _read_json_body(request)
        _log_request_start("create-order", request_id, {"source": payload.get("source", "checkout")})

        cart, _, checkout = await sync_to_async(_get_checkout_state, thread_sensitive=True)(request)
        if not cart:
            response = JsonResponse({"success": False, "message": "Your cart is empty."}, status=400)
            _log_request_end("create-order", request_id, started_at, response.status_code)
            return response

        amount_decimal = checkout["remaining_payable"]
        amount_paise = _decimal_to_paise(amount_decimal)
        if amount_paise <= 0:
            response = JsonResponse({"success": False, "message": "No online payment is required for this checkout."}, status=400)
            _log_request_end("create-order", request_id, started_at, response.status_code)
            return response

        _clear_checkout_payment_session(request)
        authenticated_user = await sync_to_async(_resolve_authenticated_user, thread_sensitive=True)(request)

        payment_transaction = await sync_to_async(PaymentTransaction.objects.create)(
            order=None,
            user=authenticated_user,
            payment_method=Order.PAYMENT_ONLINE,
            gateway=PaymentTransaction.GATEWAY_RAZORPAY,
            status=PaymentTransaction.STATUS_INITIATED,
            amount=amount_decimal,
            currency=settings.RAZORPAY_CURRENCY,
            raw_response={"stage": "create_order_requested", "request_id": request_id},
        )

        order_payload = {
            "amount": amount_paise,
            "currency": settings.RAZORPAY_CURRENCY,
            "payment_capture": 1,
            "receipt": f"txn_{payment_transaction.id}",
            "notes": {
                "transaction_id": str(payment_transaction.id),
            },
        }

        remote_order = await asyncio.wait_for(
            asyncio.to_thread(_create_remote_order, order_payload),
            timeout=settings.RAZORPAY_REQUEST_TIMEOUT_SECONDS + 1,
        )

        payment_transaction.gateway_order_id = remote_order["id"]
        payment_transaction.raw_response = {
            "stage": "create_order_completed",
            "request_id": request_id,
            "razorpay_order": remote_order,
        }
        await sync_to_async(payment_transaction.save)(update_fields=["gateway_order_id", "raw_response", "updated_at"])

        request.session["razorpay_order_id"] = remote_order["id"]
        request.session["razorpay_transaction_id"] = payment_transaction.id
        request.session["razorpay_amount"] = str(amount_decimal)
        request.session["razorpay_amount_paise"] = amount_paise
        request.session["online_payment_confirmed"] = False
        request.session.modified = True

        response = JsonResponse(
            {
                "success": True,
                "order_id": remote_order["id"],
                "transaction_id": payment_transaction.id,
                "amount": amount_paise,
                "display_amount": str(amount_decimal),
                "currency": settings.RAZORPAY_CURRENCY,
                "key": settings.RAZORPAY_KEY_ID,
            },
            status=201,
        )
        _log_request_end("create-order", request_id, started_at, response.status_code)
        return response
    except ValueError as exc:
        logger.warning("payment_request_invalid", extra={"endpoint": "create-order", "request_id": request_id, "error": str(exc)})
        response = JsonResponse({"success": False, "message": str(exc)}, status=400)
        _log_request_end("create-order", request_id, started_at, response.status_code)
        return response
    except asyncio.TimeoutError:
        if payment_transaction is not None:
            payment_transaction.status = PaymentTransaction.STATUS_FAILED
            payment_transaction.failure_reason = "Timed out while creating Razorpay order."
            payment_transaction.raw_response = {"stage": "create_order_timeout", "request_id": request_id}
            await sync_to_async(payment_transaction.save)(
                update_fields=["status", "failure_reason", "raw_response", "updated_at"]
            )
        logger.exception("razorpay_create_order_timeout", extra={"endpoint": "create-order", "request_id": request_id})
        response = JsonResponse({"success": False, "message": "Timed out while creating Razorpay order."}, status=504)
        _log_request_end("create-order", request_id, started_at, response.status_code)
        return response
    except (
        razorpay.errors.BadRequestError,
        razorpay.errors.GatewayError,
        razorpay.errors.ServerError,
        ConnectionError,
        TimeoutError,
    ) as exc:
        if payment_transaction is not None:
            payment_transaction.status = PaymentTransaction.STATUS_FAILED
            payment_transaction.failure_reason = str(exc)
            payment_transaction.raw_response = {"stage": "create_order_failed", "request_id": request_id}
            await sync_to_async(payment_transaction.save)(
                update_fields=["status", "failure_reason", "raw_response", "updated_at"]
            )
        logger.exception("razorpay_create_order_failed", extra={"endpoint": "create-order", "request_id": request_id})
        response = JsonResponse({"success": False, "message": f"Unable to create Razorpay order: {exc}"}, status=502)
        _log_request_end("create-order", request_id, started_at, response.status_code)
        return response
    except Exception:
        if payment_transaction is not None:
            payment_transaction.status = PaymentTransaction.STATUS_FAILED
            payment_transaction.failure_reason = "Unexpected server error."
            payment_transaction.raw_response = {"stage": "create_order_unhandled_error", "request_id": request_id}
            await sync_to_async(payment_transaction.save)(
                update_fields=["status", "failure_reason", "raw_response", "updated_at"]
            )
        logger.exception("payment_request_unhandled_error", extra={"endpoint": "create-order", "request_id": request_id})
        response = JsonResponse({"success": False, "message": "Unexpected server error."}, status=500)
        _log_request_end("create-order", request_id, started_at, response.status_code)
        return response


@login_required
@require_POST
def verify_payment(request: HttpRequest):
    request_id = request.headers.get("X-Request-ID") or f"rzp-verify-{int(time.time() * 1000)}"
    started_at = time.monotonic()

    try:
        payload = _read_json_body(request)
        _log_request_start(
            "verify-payment",
            request_id,
            {
                "razorpay_order_id": payload.get("razorpay_order_id"),
                "razorpay_payment_id": payload.get("razorpay_payment_id"),
            },
        )

        razorpay_order_id = (payload.get("razorpay_order_id") or "").strip()
        razorpay_payment_id = (payload.get("razorpay_payment_id") or "").strip()
        razorpay_signature = (payload.get("razorpay_signature") or "").strip()

        if not razorpay_order_id or not razorpay_payment_id or not razorpay_signature:
            raise ValueError("razorpay_order_id, razorpay_payment_id and razorpay_signature are required.")

        payment_transaction = PaymentTransaction.objects.filter(
            id=request.session.get("razorpay_transaction_id"),
            gateway_order_id=razorpay_order_id,
            gateway=PaymentTransaction.GATEWAY_RAZORPAY,
        ).first()

        if payment_transaction is None:
            response = JsonResponse({"success": False, "message": "Payment transaction not found."}, status=404)
            _log_request_end("verify-payment", request_id, started_at, response.status_code)
            return response

        generated_signature = hmac.new(
            settings.RAZORPAY_KEY_SECRET.encode("utf-8"),
            f"{razorpay_order_id}|{razorpay_payment_id}".encode("utf-8"),
            hashlib.sha256,
        ).hexdigest()
        signature_is_valid = hmac.compare_digest(generated_signature, razorpay_signature)

        payment_transaction.gateway_payment_id = razorpay_payment_id
        payment_transaction.gateway_signature = razorpay_signature

        if not signature_is_valid:
            payment_transaction.status = PaymentTransaction.STATUS_FAILED
            payment_transaction.failure_reason = "Signature verification failed."
            payment_transaction.raw_response = {
                "stage": "verify_payment_failed",
                "request_id": request_id,
                "reason": "signature_mismatch",
            }
            payment_transaction.save(
                update_fields=[
                    "gateway_payment_id",
                    "gateway_signature",
                    "status",
                    "failure_reason",
                    "raw_response",
                    "updated_at",
                ]
            )
            request.session["online_payment_confirmed"] = False
            request.session.modified = True
            response = JsonResponse({"success": False, "message": "Signature verification failed."}, status=400)
            _log_request_end("verify-payment", request_id, started_at, response.status_code)
            return response

        payment_transaction.status = PaymentTransaction.STATUS_SUCCESS
        payment_transaction.failure_reason = ""
        payment_transaction.raw_response = {
            "stage": "verify_payment_completed",
            "request_id": request_id,
            "verified": True,
        }
        payment_transaction.save(
            update_fields=[
                "gateway_payment_id",
                "gateway_signature",
                "status",
                "failure_reason",
                "raw_response",
                "updated_at",
            ]
        )

        request.session["online_payment_confirmed"] = True
        request.session["razorpay_order_id"] = razorpay_order_id
        request.session["razorpay_payment_id"] = razorpay_payment_id
        request.session["razorpay_signature"] = razorpay_signature
        request.session["razorpay_transaction_id"] = payment_transaction.id
        request.session.modified = True

        response = JsonResponse(
            {
                "success": True,
                "message": "Payment verified successfully.",
                "transaction_id": payment_transaction.id,
                "redirect_url": reverse("orders:order_create"),
            }
        )
        _log_request_end("verify-payment", request_id, started_at, response.status_code)
        return response
    except ValueError as exc:
        logger.warning("payment_verify_invalid", extra={"endpoint": "verify-payment", "request_id": request_id, "error": str(exc)})
        response = JsonResponse({"success": False, "message": str(exc)}, status=400)
        _log_request_end("verify-payment", request_id, started_at, response.status_code)
        return response
    except Exception:
        logger.exception("payment_verify_unhandled_error", extra={"endpoint": "verify-payment", "request_id": request_id})
        response = JsonResponse({"success": False, "message": "Unexpected server error."}, status=500)
        _log_request_end("verify-payment", request_id, started_at, response.status_code)
        return response
