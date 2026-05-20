from django.contrib import admin
from django.urls import path, include
from django.conf import settings
from django.conf.urls.static import static
from accounts.views import profile_page, role_based_login, user_profile_api
from ecommercesite.views import (
    contact_page,
    privacy_policy_page,
    refund_cancellation_policy_page,
    shipping_delivery_policy_page,
    terms_conditions_page,
)
from orders.payment_views import create_order, payment_checkout_page, verify_payment

urlpatterns = [
    path("admin/login/", role_based_login, name="admin_login"),
    path("admin/", admin.site.urls),
    path("accounts/login/", role_based_login, name="login"),
    path("accounts/", include("django.contrib.auth.urls")),
    path("accounts/", include("accounts.urls")),
    path("profile/", profile_page, name="profile"),
    path("api/user/profile", user_profile_api, name="user_profile_api"),
    path("payments/checkout/", payment_checkout_page, name="payment_checkout"),
    path("create-order", create_order, name="create_order"),
    path("verify-payment", verify_payment, name="verify_payment"),
    path("contact-us/", contact_page, name="contact_us"),
    path("privacy-policy/", privacy_policy_page, name="privacy_policy"),
    path("terms-and-conditions/", terms_conditions_page, name="terms_conditions"),
    path("refund-cancellation-policy/", refund_cancellation_policy_page, name="refund_policy"),
    path("shipping-delivery-policy/", shipping_delivery_policy_page, name="shipping_policy"),
    path("i18n/", include("django.conf.urls.i18n")),
    path("wishlist/", include("wishlist.urls")),
    path("cart/", include("cart.urls")),
    path("orders/", include("orders.urls")),
    path("reviews/", include(("orders.review_urls", "reviews"), namespace="reviews")),
    path("seller/", include("sellers.urls")),
    path("", include(("products.urls", "products"), namespace="products")),
]

urlpatterns += static(settings.STATIC_URL, document_root=settings.STATIC_ROOT)
urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
