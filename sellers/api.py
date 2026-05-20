"""
REST API endpoints for seller payout management.
Provides read-only access to payout history and wallet information.
"""
from decimal import Decimal
from django.shortcuts import get_object_or_404
from django.http import JsonResponse
from django.views.decorators.http import require_http_methods
from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator
import json

from sellers.models import SellerProfile, Payout, SellerOrderPayout
from sellers.services import WalletService
from products.models import Product


def _seller_required(view_func):
    """Decorator to ensure user is an approved seller."""
    def wrapper(request, *args, **kwargs):
        try:
            seller = SellerProfile.objects.get(
                user=request.user,
                approval_status=SellerProfile.STATUS_APPROVED
            )
            request.seller = seller
            return view_func(request, *args, **kwargs)
        except SellerProfile.DoesNotExist:
            return JsonResponse({'error': 'Not an approved seller'}, status=403)
    return wrapper


def _staff_required(view_func):
    def wrapper(request, *args, **kwargs):
        if not request.user.is_authenticated:
            return JsonResponse({"error": "Authentication required"}, status=401)
        if not request.user.is_staff:
            return JsonResponse({"error": "Admin access required"}, status=403)
        return view_func(request, *args, **kwargs)
    return wrapper


@login_required
@require_http_methods(["GET"])
@_seller_required
def payout_wallet_api(request):
    """
    Get current wallet balance and financial snapshot.
    
    Response:
    {
        "seller_id": 1,
        "wallet": {
            "pending_balance": "1000.00",
            "hold_balance": "500.00",
            "available_balance": "2000.00",
            "paid_balance": "5000.00"
        },
        "total_earnings": "8500.00",
        "pending_payout": "3500.00",
        "paid_payout": "5000.00"
    }
    """
    seller = request.seller
    snapshot = WalletService.get_financial_snapshot(seller)
    wallet = snapshot['wallet']
    
    return JsonResponse({
        'seller_id': seller.id,
        'seller_name': seller.business_name,
        'wallet': {
            'pending_balance': str(wallet.pending_balance),
            'hold_balance': str(wallet.hold_balance),
            'available_balance': str(wallet.available_balance),
            'paid_balance': str(wallet.paid_balance),
        },
        'total_earnings': str(snapshot['wallet_balance']),
        'pending_payout': str(snapshot['pending_payout']),
        'paid_payout': str(snapshot['paid_payout']),
    })


@login_required
@require_http_methods(["GET"])
@_seller_required
def payout_history_api(request):
    """
    Get payout history with pagination.
    
    Query Parameters:
    - page: Page number (default: 1)
    - limit: Items per page (default: 20, max: 100)
    - status: Filter by status (initiated, processing, completed, failed)
    - start_date: Filter from date (YYYY-MM-DD)
    - end_date: Filter to date (YYYY-MM-DD)
    
    Response:
    {
        "count": 42,
        "page": 1,
        "page_size": 20,
        "total_pages": 3,
        "payouts": [
            {
                "id": 1,
                "amount": "1000.00",
                "status": "completed",
                "reference": "payout_12345",
                "created_at": "2026-04-15T10:30:00Z",
                "processed_at": "2026-04-15T11:00:00Z"
            },
            ...
        ]
    }
    """
    seller = request.seller
    page = int(request.GET.get('page', 1))
    limit = min(int(request.GET.get('limit', 20)), 100)  # Max 100 per page
    status_filter = request.GET.get('status', '')
    start_date = request.GET.get('start_date', '')
    end_date = request.GET.get('end_date', '')
    
    # Build queryset
    payouts = Payout.objects.filter(seller=seller)
    
    if status_filter:
        payouts = payouts.filter(status=status_filter)
    
    if start_date:
        try:
            from datetime import datetime
            start = datetime.fromisoformat(start_date).date()
            payouts = payouts.filter(created_at__date__gte=start)
        except ValueError:
            pass
    
    if end_date:
        try:
            from datetime import datetime
            end = datetime.fromisoformat(end_date).date()
            payouts = payouts.filter(created_at__date__lte=end)
        except ValueError:
            pass
    
    # Paginate
    paginator = Paginator(payouts.order_by('-created_at'), limit)
    payouts_page = paginator.get_page(page)
    
    payout_list = []
    for payout in payouts_page.object_list:
        payout_list.append({
            'id': payout.id,
            'amount': str(payout.amount),
            'status': payout.status,
            'status_display': payout.get_status_display(),
            'reference': payout.reference,
            'failure_reason': payout.failure_reason or None,
            'created_at': payout.created_at.isoformat(),
            'processed_at': payout.processed_at.isoformat() if payout.processed_at else None,
        })
    
    return JsonResponse({
        'count': paginator.count,
        'page': page,
        'page_size': limit,
        'total_pages': paginator.num_pages,
        'payouts': payout_list,
    })


@login_required
@require_http_methods(["GET"])
@_seller_required
def payout_order_earnings_api(request, order_id):
    """
    Get earnings breakdown for a specific order.
    
    Response:
    {
        "order_id": 12345,
        "gross_amount": "1000.00",
        "net_amount": "820.00",
        "status": "available",
        "breakdown": {
            "product_price": "1000.00",
            "commission": "100.00",
            "gateway_fee": "20.00",
            "shipping": "50.00",
            "gst": "180.00",
            "tds": "10.00"
        },
        "created_at": "2026-04-15T10:30:00Z"
    }
    """
    seller = request.seller
    
    payout_summary = get_object_or_404(
        SellerOrderPayout.objects.select_related('order'),
        seller=seller,
        order_id=order_id
    )
    
    breakdown = payout_summary.breakdown or {}
    
    return JsonResponse({
        'order_id': payout_summary.order_id,
        'gross_amount': str(payout_summary.gross_amount),
        'net_amount': str(payout_summary.net_amount),
        'status': payout_summary.status,
        'status_display': payout_summary.get_status_display(),
        'breakdown': breakdown,
        'delivered_at': payout_summary.delivered_at.isoformat() if payout_summary.delivered_at else None,
        'available_on': payout_summary.available_on.isoformat() if payout_summary.available_on else None,
        'paid_at': payout_summary.paid_at.isoformat() if payout_summary.paid_at else None,
        'created_at': payout_summary.created_at.isoformat(),
        'updated_at': payout_summary.updated_at.isoformat(),
    })


@login_required
@require_http_methods(["POST"])
@_seller_required
def request_payout_api(request):
    """
    Request a payout for available balance.
    
    Response:
    {
        "success": true,
        "payout_id": 42,
        "amount": "2000.00",
        "status": "processing",
        "reference": "payout_abc123",
        "message": "Payout has been initiated and will be processed within 24 hours"
    }
    """
    seller = request.seller
    from sellers.services import PayoutService
    from django.utils import timezone
    
    try:
        payout_service = PayoutService()
        payout = payout_service.release_available_balance(
            seller=seller,
            idempotency_key=f"api-payout:{seller.id}:{timezone.now().timestamp()}",
        )
        
        return JsonResponse({
            'success': True,
            'payout_id': payout.id,
            'amount': str(payout.amount),
            'status': payout.status,
            'reference': payout.reference,
            'message': f"Payout initiated. Reference: {payout.reference}",
        })
    except Exception as e:
        return JsonResponse({
            'success': False,
            'error': str(e),
        }, status=400)


@login_required
@require_http_methods(["POST"])
@_staff_required
def approve_product_api(request, product_id):
    product = get_object_or_404(Product, id=product_id)
    product.approve(save=True)
    return JsonResponse(
        {
            "success": True,
            "product_id": product.id,
            "status": product.status,
            "status_display": product.get_status_display(),
        }
    )


@login_required
@require_http_methods(["POST"])
@_staff_required
def reject_product_api(request, product_id):
    product = get_object_or_404(Product, id=product_id)
    payload = {}
    if request.content_type == "application/json":
        try:
            payload = json.loads(request.body.decode("utf-8") or "{}")
        except json.JSONDecodeError:
            payload = {}
    reason = (payload.get("rejection_reason") or request.POST.get("rejection_reason") or "").strip()
    if not reason:
        return JsonResponse(
            {
                "success": False,
                "error": "Rejection reason is required.",
            },
            status=400,
        )
    product.reject(reason=reason, save=True)
    return JsonResponse(
        {
            "success": True,
            "product_id": product.id,
            "status": product.status,
            "status_display": product.get_status_display(),
            "rejection_reason": product.rejection_reason,
        }
    )

