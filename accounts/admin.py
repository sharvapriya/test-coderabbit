from django.contrib import admin, messages
from django import forms
from django.contrib.auth import get_user_model
from django.contrib.auth.admin import UserAdmin as DjangoUserAdmin
from django.contrib.auth.forms import UserChangeForm as DjangoUserChangeForm
from django.contrib.auth.models import Group
from django.db.models import Q
from django.http import HttpResponseRedirect
from django.urls import path, reverse
from django.utils.html import format_html
from .models import Profile, Address, Notification


User = get_user_model()


try:
    admin.site.unregister(User)
except admin.sites.NotRegistered:
    pass


class UserAdminChangeForm(DjangoUserChangeForm):
    phone_number = forms.CharField(max_length=15, required=False)

    class Meta(DjangoUserChangeForm.Meta):
        model = User
        fields = "__all__"

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if self.instance.pk:
            self.fields["phone_number"].initial = getattr(
                getattr(self.instance, "profile", None),
                "phone_number",
                "",
            )

    def save(self, commit=True):
        user = super().save(commit=commit)
        if commit:
            Profile.objects.update_or_create(
                user=user,
                defaults={"phone_number": self.cleaned_data.get("phone_number", "")},
            )
        return user


@admin.register(User)
class UserAdmin(DjangoUserAdmin):
    form = UserAdminChangeForm
    change_list_template = "admin/auth/user/change_list.html"
    list_display = ("username", "email", "phone_number", "user_profile", "is_staff")
    actions = ("mark_as_seller", "mark_as_buyer")
    list_per_page = 50
    show_full_result_count = False
    fieldsets = DjangoUserAdmin.fieldsets + (
        ("Contact info", {"fields": ("phone_number",)}),
    )

    def get_queryset(self, request):
        queryset = super().get_queryset(request)
        return queryset.select_related("seller_profile", "profile").prefetch_related("groups")

    def _get_or_create_role_groups(self):
        seller_group, _ = Group.objects.get_or_create(name="Seller")
        buyer_group, _ = Group.objects.get_or_create(name="Buyer")
        return seller_group, buyer_group

    def _is_seller(self, obj):
        seller_profile = getattr(obj, "seller_profile", None)
        return bool(seller_profile and seller_profile.is_approved)

    @admin.display(description="User Profile")
    def user_profile(self, obj):
        if obj.is_superuser:
            return "Admin"
        if self._is_seller(obj):
            return "Seller"
        return "Buyer"

    @admin.display(description="Phone Number")
    def phone_number(self, obj):
        return getattr(getattr(obj, "profile", None), "phone_number", "-") or "-"

    @admin.display(description="Update Role")
    def update_user_role(self, obj):
        if obj.is_superuser:
            return "-"
        seller_url = reverse("admin:auth_user_set_role", args=[obj.pk, "seller"])
        buyer_url = reverse("admin:auth_user_set_role", args=[obj.pk, "buyer"])
        return format_html(
            '<a class="button" href="{}">Set Seller</a>&nbsp;<a class="button" href="{}">Set Buyer</a>',
            seller_url,
            buyer_url,
        )

    def get_urls(self):
        urls = super().get_urls()
        custom_urls = [
            path(
                "<int:user_id>/set-role/<str:role>/",
                self.admin_site.admin_view(self.set_user_role_view),
                name="auth_user_set_role",
            ),
        ]
        return custom_urls + urls

    def set_user_role_view(self, request, user_id, role):
        if not self.has_change_permission(request):
            return HttpResponseRedirect(reverse("admin:auth_user_changelist"))

        target_user = self.model.objects.filter(pk=user_id).first()
        if not target_user or target_user.is_superuser:
            return HttpResponseRedirect(request.META.get("HTTP_REFERER", reverse("admin:auth_user_changelist")))

        seller_group, buyer_group = self._get_or_create_role_groups()
        target_user.groups.remove(seller_group, buyer_group)
        if role == "seller":
            seller_profile = getattr(target_user, "seller_profile", None)
            if not seller_profile or not seller_profile.is_approved:
                self.message_user(
                    request,
                    "Only users with an approved seller registration can be marked as Seller.",
                    level=messages.ERROR,
                )
                return HttpResponseRedirect(
                    request.META.get("HTTP_REFERER", reverse("admin:auth_user_changelist"))
                )
            target_user.groups.add(seller_group)
        elif role == "buyer":
            target_user.groups.add(buyer_group)

        return HttpResponseRedirect(request.META.get("HTTP_REFERER", reverse("admin:auth_user_changelist")))

    @admin.action(description="Mark selected users as Seller")
    def mark_as_seller(self, request, queryset):
        seller_group, buyer_group = self._get_or_create_role_groups()
        skipped_count = 0
        for user in queryset.exclude(is_superuser=True):
            seller_profile = getattr(user, "seller_profile", None)
            if not seller_profile or not seller_profile.is_approved:
                skipped_count += 1
                continue
            user.groups.remove(buyer_group)
            user.groups.add(seller_group)
        if skipped_count:
            self.message_user(
                request,
                f"Skipped {skipped_count} user(s) because seller registration is not approved yet.",
                level=messages.WARNING,
            )

    @admin.action(description="Mark selected users as Buyer")
    def mark_as_buyer(self, request, queryset):
        seller_group, buyer_group = self._get_or_create_role_groups()
        for user in queryset.exclude(is_superuser=True):
            user.groups.remove(seller_group)
            user.groups.add(buyer_group)

    def changelist_view(self, request, extra_context=None):
        extra_context = extra_context or {}
        users = self.model.objects.filter(is_superuser=False)
        seller_condition = Q(seller_profile__approval_status="approved")
        seller_count = users.filter(seller_condition).distinct().count()
        buyer_count = users.exclude(seller_condition).distinct().count()
        extra_context["seller_count"] = seller_count
        extra_context["buyer_count"] = buyer_count
        return super().changelist_view(request, extra_context=extra_context)


# @admin.register(Address)
# class AddressAdmin(admin.ModelAdmin):
#     list_display = ("label", "user", "phone_number", "city", "state", "is_default", "created_at")
#     list_filter = ("is_default", "country", "created_at")
#     search_fields = ("label", "user__username", "phone_number", "city", "state")
#     readonly_fields = ("created_at", "updated_at")
#     list_select_related = ("user",)
#     list_per_page = 50
#     show_full_result_count = False
#     fieldsets = (
#         ("Address Details", {"fields": ("user", "label", "phone_number", "address_line")}),
#         ("Location", {"fields": ("city", "state", "country", "pincode")}),
#         ("Settings", {"fields": ("is_default",)}),
#         ("Timestamps", {"fields": ("created_at", "updated_at"), "classes": ("collapse",)}),
#     )


@admin.register(Notification)
class NotificationAdmin(admin.ModelAdmin):
    list_display = ("user", "notification_type", "title", "is_read", "created_at")
    list_filter = ("notification_type", "is_read", "created_at")
    search_fields = ("user__username", "title", "message")
    readonly_fields = ("created_at",)
    list_select_related = ("user",)
    list_per_page = 50
    show_full_result_count = False
    fieldsets = (
        ("Notification Details", {"fields": ("user", "notification_type", "title", "message")}),
        ("Status", {"fields": ("is_read",)}),
        ("Timestamps", {"fields": ("created_at",), "classes": ("collapse",)}),
    )
