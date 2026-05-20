from django.urls import path

from . import views
from .views import role_based_login, signup

app_name = "accounts"

urlpatterns = [
    path("login/", role_based_login, name="login"),
    path("signup/", signup, name="signup"),
    path("signup/username-availability/", views.username_availability, name="username_availability"),
    path("signup/username-suggestions/", views.username_suggestions, name="username_suggestions"),
    path("profile/", views.profile_page, name="profile"),
    path("api/user/profile", views.user_profile_api, name="user_profile_api"),
    path("api/addresses/add/", views.add_address, name="add_address"),
    path("api/addresses/<int:address_id>/delete/", views.delete_address, name="delete_address"),
    path("api/addresses/<int:address_id>/set-default/", views.set_default_address, name="set_default_address"),
    path("forgot-password-check/", views.forgot_password_check, name="forgot_password_check"),
    path("forgot-password/", views.change_password_view, name="change_password"),
    path("change-password/", views.change_password_view),
    path("send-verification-code/", views.send_verification_code, name="send_verification_code"),
    path("notifications/", views.notifications_view, name="notifications"),
    path("api/notifications/<int:notification_id>/mark-read/", views.mark_notification_read, name="mark_notification_read"),
]
