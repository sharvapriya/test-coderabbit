from django.urls import path
from . import views
# from .payment_views import payment_online_redirect, payment_step_redirect
from .payment_views import payment_online, payment_step

from .views import (
    delivery_dashboard,
    delivery_update,
    discount_step,
    order_confirmation,
    order_create,
    order_tracking_detail,
    order_tracking_list,
    # payment_online_placeholder,
    # payment_step,
    cancel_order,
    cancel_order_item,
    return_request_create,
    return_request_list,
    withdraw_return_request,
    wallet_detail,
    review_create,
    admin_review_list,
    confirm_return_shipment,
)

app_name = "orders"


urlpatterns = [
    path("discount/", discount_step, name="discount_step"),
    # path("payment/", payment_step_redirect, name="payment_step"),
    # path("payment/online/", payment_online_redirect, name="payment_online"),
    path("payment/", payment_step, name="payment_step"),
    path("payment/online/", payment_online, name="payment_online"),
    # path("payment-online/", views.payment_online, name="payment_online"),
    # path("payment-status/", views.payment_status, name="payment_status"), # not necessary
    # path("payment/online/<int:order_id>/", payment_online_placeholder, name="payment_online_placeholder"),
    # path("payment-success/", views.payment_success, name="payment_success"),
    path("create", order_create, name="order_create"),
    path("confirmation/<int:order_id>", order_confirmation, name="order_confirmation"),
    path("<int:order_id>/cancel/", cancel_order, name="cancel_order_api"),
    path("tracking/", order_tracking_list, name="order_tracking_list"),
    path("tracking/<int:order_id>/", order_tracking_detail, name="order_tracking_detail"),
    path("tracking/<int:order_id>/cancel/", cancel_order, name="cancel_order"),
    path("items/<int:order_item_id>/cancel/", cancel_order_item, name="cancel_order_item"),
    path("tracking/<int:order_id>/return/", return_request_create, name="return_request_create"),
    path("returns/", return_request_list, name="return_request_list"),
    path("returns/<int:return_id>/withdraw/", withdraw_return_request, name="withdraw_return_request"),
    path("returns/<int:return_id>/confirm-shipment/", confirm_return_shipment, name="confirm_return_shipment"),
    path("wallet/", wallet_detail, name="wallet_detail"),
    path("delivery/", delivery_dashboard, name="delivery_dashboard"),
    path("delivery/<int:assignment_id>/update/", delivery_update, name="delivery_update"),
    # Review URLs
    path("review/create/<int:order_item_id>/", review_create, name="review_create"),
    path("admin/reviews/", admin_review_list, name="admin_review_list"),
    path("invoice/<int:order_id>/",views.order_invoice, name="order_invoice"),
    path("invoice/<int:order_id>/download/", views.order_invoice_pdf, name="order_invoice_pdf"),
]
