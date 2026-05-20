import base64
import binascii
import json
import random
import time
from functools import reduce
from operator import or_

from django.conf import settings
from django.contrib import messages
from django.contrib.auth import get_user_model, login
from django.contrib.auth.forms import AuthenticationForm
from django.contrib.auth.decorators import login_required
from django.core.files.base import ContentFile
from django.db import IntegrityError, transaction
from django.db.models import Q
from django.http import JsonResponse
from django.shortcuts import redirect, render
from django.urls import reverse
from django.utils.http import url_has_allowed_host_and_scheme
from django.views.decorators.http import require_http_methods

from .forms import ProfileUpdateForm, SignUpForm, sanitize_username
from .models import Profile, Address, Notification


USERNAME_SUGGESTION_LIMIT = 5
USERNAME_SUGGESTION_MINIMUM = 3
USERNAME_SUFFIXES = ("shop", "dev", "hub", "co", "online")


def role_based_login(request):
    if request.user.is_authenticated:
        if request.user.is_staff:
            return redirect("admin:index")
        return redirect("products:home")

    next_url = request.POST.get("next") or request.GET.get("next") or ""

    form = AuthenticationForm(request, data=request.POST or None)

    if request.method == "POST" and form.is_valid():
        user = form.get_user()
        login(request, user)

        # Check if next_url is safe
        if next_url and url_has_allowed_host_and_scheme(
            url=next_url,
            allowed_hosts={request.get_host()},
            require_https=request.is_secure(),
        ):
            return redirect(next_url)

        if user.is_staff:
            return redirect("admin:index")

        return redirect("products:home")

    return render(
        request,
        "registration/login.html",
        {
            "form": form,
            "next": next_url,
        },
    )


def signup(request):
    if request.user.is_authenticated:
        return redirect("products:home")

    if request.method == "POST":
        form = SignUpForm(request.POST)
        if form.is_valid():
            try:
                with transaction.atomic():
                    username = form.cleaned_data["username"]
                    if get_user_model().objects.filter(username__iexact=username).exists():
                        form.add_error("username", "This username was just taken. Please choose another one.")
                    else:
                        user = form.save()
                        login(request, user)
                        return redirect("products:home")
            except IntegrityError:
                form.add_error("username", "This username was just taken. Please choose another one.")
    else:
        form = SignUpForm()

    return render(
        request,
        "accounts/signup.html",
        {
            "form": form,
        },
    )


def _username_variants(base_username):
    clean_base = sanitize_username(base_username)
    return [
        clean_base,
        f"{clean_base}_{random.randint(11, 99)}",
        f"{clean_base}{random.randint(100, 999)}",
        f"{clean_base}{random.choice(USERNAME_SUFFIXES)}",
        f"{clean_base}.{random.randint(10, 99)}",
        f"{clean_base}_{random.choice(USERNAME_SUFFIXES)}",
    ]


def _available_usernames(candidates, limit=USERNAME_SUGGESTION_LIMIT):
    normalized = []
    seen = set()
    for candidate in candidates:
        clean_candidate = sanitize_username(candidate)
        if clean_candidate in seen:
            continue
        seen.add(clean_candidate)
        normalized.append(clean_candidate)

    if normalized:
        username_filter = reduce(or_, (Q(username__iexact=name) for name in normalized))
        existing = {
            username.lower()
            for username in get_user_model().objects.filter(username_filter).values_list("username", flat=True)
        }
    else:
        existing = set()

    return [candidate for candidate in normalized if candidate.lower() not in existing][:limit]


def _build_username_suggestions(username=""):
    base = sanitize_username(username)
    if not (username or "").strip():
        return []

    candidate_pool = _username_variants(base)

    suggestions = _available_usernames(candidate_pool, limit=USERNAME_SUGGESTION_LIMIT)

    while len(suggestions) < USERNAME_SUGGESTION_MINIMUM:
        suggestions = _available_usernames(
            suggestions + _username_variants(f"{base}{random.randint(100, 999)}"),
            limit=USERNAME_SUGGESTION_LIMIT,
        )

    return suggestions[:USERNAME_SUGGESTION_LIMIT]


@require_http_methods(["GET"])
def username_availability(request):
    raw_username = request.GET.get("username", "")
    username = sanitize_username(raw_username)
    available = not get_user_model().objects.filter(username__iexact=username).exists()
    message = "Available" if available else "Already taken"
    return JsonResponse(
        {
            "username": username,
            "available": available,
            "message": message,
        }
    )


@require_http_methods(["GET"])
def username_suggestions(request):
    username = request.GET.get("username", "")
    suggestions = _build_username_suggestions(username=username)
    return JsonResponse({"suggestions": suggestions})


def _get_or_create_profile(user):
    return Profile.objects.get_or_create(user=user)[0]


def _get_account_role(user):
    seller_profile = getattr(user, "seller_profile", None)
    if user.is_staff:
        return "Admin"
    if seller_profile and seller_profile.is_approved:
        return "Seller"
    return "User"


def _serialize_profile(user, profile):
    return {
        "id": profile.id,
        "fullName": profile.full_name or user.get_full_name() or user.username,
        "email": user.email or "",
        "phone": profile.phone_number or "",
        "address": {
            "line": profile.address_line or "",
            "city": profile.city or "",
            "state": profile.state or "",
            "country": profile.country or "",
            "pincode": profile.pincode or "",
        },
        "username": user.username,
        "role": _get_account_role(user),
        "createdAt": user.date_joined.isoformat() if user.date_joined else "",
        "profilePictureUrl": profile.profile_picture.url if profile.profile_picture else "",
        "addressBook": [
            {
                "id": addr.id,
                "label": addr.label,
                "phone": addr.phone_number or "",
                "line": addr.address_line or "",
                "city": addr.city or "",
                "state": addr.state or "",
                "country": addr.country or "",
                "pincode": addr.pincode or "",
                "isDefault": addr.is_default,
            }
            for addr in user.addresses.all()
        ],
    }


def _decode_profile_picture(data_url):
    if not data_url:
        return None
    try:
        header, encoded = data_url.split(",", 1)
        extension = "png"
        if "image/jpeg" in header:
            extension = "jpg"
        elif "image/webp" in header:
            extension = "webp"
        elif "image/png" not in header:
            raise ValueError("Unsupported image format.")
        decoded = base64.b64decode(encoded)
    except (ValueError, binascii.Error):
        raise ValueError("Invalid profile picture data.")
    return ContentFile(decoded, name=f"profile-{int(time.time())}.{extension}")


@login_required
def profile_page(request):
    return render(request, "accounts/profile.html")


@login_required
@require_http_methods(["GET", "PUT"])
def user_profile_api(request):
    profile = _get_or_create_profile(request.user)

    if request.method == "GET":
        return JsonResponse(_serialize_profile(request.user, profile))

    try:
        payload = json.loads(request.body.decode("utf-8") or "{}")
    except json.JSONDecodeError:
        return JsonResponse({"message": "Invalid JSON payload."}, status=400)

    profile_data = {
        "full_name": payload.get("fullName", ""),
        "phone_number": payload.get("phone", ""),
        "address_line": (payload.get("address") or {}).get("line", ""),
        "city": (payload.get("address") or {}).get("city", ""),
        "state": (payload.get("address") or {}).get("state", ""),
        "country": (payload.get("address") or {}).get("country", ""),
        "pincode": (payload.get("address") or {}).get("pincode", ""),
        "email": payload.get("email", ""),
    }
    form = ProfileUpdateForm(profile_data, instance=profile, user=request.user)
    if not form.is_valid():
        return JsonResponse({"message": "Please fix the highlighted fields.", "errors": form.errors}, status=400)

    profile_picture_data = payload.get("profilePictureDataUrl")
    if profile_picture_data:
        try:
            profile.profile_picture = _decode_profile_picture(profile_picture_data)
        except ValueError as exc:
            return JsonResponse({"message": str(exc)}, status=400)

    profile = form.save()
    return JsonResponse(
        {
            "message": "Profile updated successfully.",
            "profile": _serialize_profile(request.user, profile),
        }
    )


@login_required
@require_http_methods(["POST"])
def add_address(request):
    """Add a new address to the user's address book."""
    try:
        payload = json.loads(request.body.decode("utf-8") or "{}")
    except json.JSONDecodeError:
        return JsonResponse({"message": "Invalid JSON payload."}, status=400)

    errors = {}
    required_fields = ["label", "line", "city", "state", "country", "pincode"]
    for field in required_fields:
        if not payload.get(field, "").strip():
            errors[field] = f"{field.capitalize()} is required."

    if errors:
        return JsonResponse({"message": "Please fill all required fields.", "errors": errors}, status=400)

    # If this is the first address, make it default
    is_default = payload.get("isDefault", False) or (request.user.addresses.count() == 0)

    # If setting as default, unset other defaults
    if is_default:
        request.user.addresses.update(is_default=False)

    profile = _get_or_create_profile(request.user)
    address = Address.objects.create(
        user=request.user,
        label=payload["label"].strip(),
        phone_number=(payload.get("phone") or profile.phone_number or "").strip(),
        address_line=payload["line"].strip(),
        city=payload["city"].strip(),
        state=payload["state"].strip(),
        country=payload["country"].strip(),
        pincode=payload["pincode"].strip(),
        is_default=is_default,
    )
    return JsonResponse(
        {
            "message": "Address added successfully.",
            "profile": _serialize_profile(request.user, profile),
        }
    )


@login_required
@require_http_methods(["DELETE"])
def delete_address(request, address_id):
    """Delete an address from the user's address book."""
    try:
        address = Address.objects.get(id=address_id, user=request.user)
    except Address.DoesNotExist:
        return JsonResponse({"message": "Address not found."}, status=404)

    was_default = address.is_default
    address.delete()

    # If the deleted address was default, set the first remaining as default
    if was_default and request.user.addresses.exists():
        first_address = request.user.addresses.first()
        first_address.is_default = True
        first_address.save()

    profile = _get_or_create_profile(request.user)
    return JsonResponse(
        {
            "message": "Address deleted successfully.",
            "profile": _serialize_profile(request.user, profile),
        }
    )


@login_required
@require_http_methods(["POST"])
def set_default_address(request, address_id):
    """Set an address as the default address."""
    try:
        address = Address.objects.get(id=address_id, user=request.user)
    except Address.DoesNotExist:
        return JsonResponse({"message": "Address not found."}, status=404)

    # Unset other defaults
    request.user.addresses.exclude(id=address_id).update(is_default=False)
    
    # Set this as default
    address.is_default = True
    address.save()

    profile = _get_or_create_profile(request.user)
    return JsonResponse(
        {
            "message": "Default address updated.",
            "profile": _serialize_profile(request.user, profile),
        }
    )



# Replace the existing FORGOT PASSWORD section in views.py with this block.
# These three views replace: send_verification_code, change_password_view
# and add a new: forgot_password_check
def forgot_password_check(request):
    """
    AJAX — given a username, returns whether the account has a real email.
    Response: { has_email: bool, masked_email: str|null }
    """
    username = request.GET.get('username', '').strip()
    if not username:
        return JsonResponse({'status': 'error', 'message': 'Username is required.'}, status=400)
    UserModel = get_user_model()
    try:
        user = UserModel.objects.get(username=username)
    except UserModel.DoesNotExist:
        return JsonResponse({'status': 'error', 'message': 'No account found with that username.'}, status=404)
    email = user.email or ''
    has_email = bool(email) and email.lower() not in ('n/a', 'na', '')
    masked = None
    if has_email:
        parts = email.split('@')
        visible = parts[0][:2] if len(parts[0]) >= 2 else parts[0]
        masked = f"{visible}{'*' * (len(parts[0]) - len(visible))}@{parts[1]}"
    # Store username in session so send_verification_code can use it
    request.session['reset_username'] = username
    return JsonResponse({
        'status': 'success',
        'has_email': has_email,
        'masked_email': masked,
    })
def send_verification_code(request):
    """
    AJAX — sends a 6-digit OTP to the given email.
    Also validates that the email belongs to the account (or is a new one for no-email users).
    """
    try:
        email = request.GET.get('email', '').strip()
        if not email:
            return JsonResponse({'status': 'error', 'message': 'Email is required.'}, status=400)
        UserModel = get_user_model()
        username = request.session.get('reset_username', '')
        if username:
            # Validate the email matches the account (or allow any email for no-email accounts)
            try:
                user = UserModel.objects.get(username=username)
                account_email = user.email or ''
                has_real_email = bool(account_email) and account_email.lower() not in ('n/a', 'na', '')
                if has_real_email and account_email.lower() != email.lower():
                    return JsonResponse({
                        'status': 'error',
                        'message': 'This email does not match our records for your account.'
                    }, status=400)
                # For no-email users: check the new email isn't taken by someone else
                if not has_real_email:
                    if UserModel.objects.filter(email=email).exclude(username=username).exists():
                        return JsonResponse({
                            'status': 'error',
                            'message': 'This email is already registered to another account.'
                        }, status=400)
            except UserModel.DoesNotExist:
                return JsonResponse({'status': 'error', 'message': 'Account not found.'}, status=404)
        else:
            # Fallback: just check email exists
            if not UserModel.objects.filter(email=email).exists():
                return JsonResponse({'status': 'error', 'message': 'No account found with that email address.'}, status=404)
        # Generate 6-digit code and store with timestamp for expiry
        code = random.randint(100000, 999999)
        request.session['password_reset_code'] = str(code)
        request.session['reset_email'] = email
        request.session['reset_code_time'] = time.time()
        email_message = build_email_message(
            "Your Password Reset Code",
            (
                f"Hello,\n\n"
                f"Your verification code is: {code}\n\n"
                f"This code is valid for 10 minutes.\n"
                f"If you did not request this, please ignore this email."
            ),
            [email],
            settings.ACCOUNT_NOTIFICATIONS_EMAIL,
        )
        email_message.send(fail_silently=False)
        return JsonResponse({'status': 'success', 'message': 'Code sent! Check your inbox.'})
    except Exception as e:
        return JsonResponse({'status': 'error', 'message': str(e)}, status=500)
    
def change_password_view(request):
    """Renders the forgot-password page and handles the password update POST."""
    if request.method == 'POST':
        UserModel = get_user_model()
        username     = request.session.get('reset_username', '')
        email        = request.session.get('reset_email')
        input_code   = request.POST.get('verification_code', '').strip()
        session_code = request.session.get('password_reset_code')
        code_time    = request.session.get('reset_code_time', 0)
        new_password = request.POST.get('new_password', '')
        confirm_pass = request.POST.get('confirm_password', '')
        # 1. Check code expiry (10 minutes)
        if time.time() - code_time > 600:
            messages.error(request, 'Verification code has expired. Please request a new one.')
            return render(request, 'accounts/change_password.html')
        # 2. Validate code
        if not session_code or input_code != session_code:
            messages.error(request, 'Invalid verification code. Please try again.')
            return render(request, 'accounts/change_password.html')
        # 3. Validate passwords match
        if new_password != confirm_pass:
            messages.error(request, 'Passwords do not match.')
            return render(request, 'accounts/change_password.html')
        if len(new_password) < 6:
            messages.error(request, 'Password must be at least 6 characters.')
            return render(request, 'accounts/change_password.html')
        # 4. Find user — prefer by username, fall back to email
        try:
            if username:
                user = UserModel.objects.get(username=username)
            else:
                user = UserModel.objects.get(email=email)
            user.set_password(new_password)
            # If the user had no email (N/A), save the new email they used for OTP
            account_email = user.email or ''
            had_no_email = not account_email or account_email.lower() in ('n/a', 'na', '')
            if had_no_email and email:
                user.email = email
            user.save()
            if user.email:
                send_password_changed_email(user.email)
            # Clear session reset keys
            for key in ('password_reset_code', 'reset_email', 'reset_code_time', 'reset_username'):
                request.session.pop(key, None)
            # messages.success(request, 'Password updated successfully. Please login.')
            messages.success(
                request,
                'Your password has been changed successfully. Please sign in with your new password.',
                extra_tags='password-change',
            )
            return redirect('login')
        except UserModel.DoesNotExist:
            messages.error(request, 'Account not found.')
    return render(request, 'accounts/change_password.html')



# view for welcome email notification
from .utils.email import build_email_message, send_password_changed_email, send_welcome_email

def signup_view(request):
    if request.method == "POST":
        user = User.objects.create_user(
            username=request.POST["username"],
            email=request.POST["email"],
            password=request.POST["password"]
        )

        # ✅ ONLY HERE (not in login)
        try:
            send_welcome_email(user)
        except Exception as e:
            print("Email failed:", e)

        return redirect("login")


@login_required
def notifications_view(request):
    """Display user's notifications."""
    notifications = request.user.notifications.all()
    unread_count = notifications.filter(is_read=False).count()
    
    return render(request, "accounts/notifications.html", {
        "notifications": notifications,
        "unread_count": unread_count,
    })


@login_required
@require_http_methods(["POST"])
def mark_notification_read(request, notification_id):
    """Mark a notification as read."""
    try:
        notification = Notification.objects.get(id=notification_id, user=request.user)
        notification.is_read = True
        notification.save()
        return JsonResponse({"message": "Notification marked as read."})
    except Notification.DoesNotExist:
        return JsonResponse({"message": "Notification not found."}, status=404)
