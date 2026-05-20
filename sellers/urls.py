from django.urls import path

from . import views

try:
    from . import api
except ImportError:
    api = None

app_name = "sellers"

urlpatterns = [
    path("", views.seller_dashboard, name="dashboard"),
    path("wallet/", views.seller_wallet_summary, name="wallet_summary"),
    path("wallet/payout/", views.trigger_manual_payout, name="trigger_manual_payout"),
    path("ledger/", views.seller_ledger_history, name="ledger_history"),
    path("payout-history/", views.seller_payout_history, name="payout_history"),
    path("orders/<int:order_id>/earnings/", views.seller_order_earnings, name="order_earnings"),
    path("profile/create/", views.create_seller_profile, name="create_profile"),
    path("profile/review/", views.review_seller_profile, name="review_profile"),
    path("registration/status/", views.registration_status, name="registration_status"),
    path("registration/withdraw/", views.withdraw_registration, name="withdraw_registration"),
    path("products/publish/", views.publish_product, name="publish_product"),
    path("products/<int:seller_product_id>/edit/", views.edit_product, name="edit_product"),
    path(
        "products/<int:seller_product_id>/delete/",
        views.delete_product,
        name="delete_product",
    ),
    path(
        "payouts/<int:payout_id>/update-own-delivery-status/",
        views.update_own_delivery_status,
        name="update_own_delivery_status",
    ),
    path(
        "notifications/<int:notification_id>/mark-read/",
        views.mark_notification_as_read,
        name="mark_notification_as_read",
    ),
    path("reviews/", views.seller_review_list, name="seller_reviews"),
    path("returns/", views.seller_returns, name="returns"),
    path("returns/<int:return_id>/receive/", views.mark_return_received, name="mark_return_received"),
    path("seller/invoice/<int:order_id>/", views.seller_invoice, name="seller_invoice"),
    path("admin/payout-management/", views.admin_payout_management, name="admin_payout_management"),
    path("admin/release-payout/<int:seller_id>/", views.admin_release_payout, name="admin_release_payout"),
]

if api is not None:
    urlpatterns += [
        path("api/wallet/", api.payout_wallet_api, name="api_wallet"),
        path("api/payout-history/", api.payout_history_api, name="api_payout_history"),
        path("api/order/<int:order_id>/earnings/", api.payout_order_earnings_api, name="api_order_earnings"),
        path("api/request-payout/", api.request_payout_api, name="api_request_payout"),
        path("api/products/<int:product_id>/approve/", api.approve_product_api, name="api_approve_product"),
        path("api/products/<int:product_id>/reject/", api.reject_product_api, name="api_reject_product"),
    ]
