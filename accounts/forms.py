import re

from django import forms
from django.contrib.auth.forms import UserCreationForm
from django.contrib.auth.models import User

from .models import Profile
from .utils.email import send_welcome_email


USERNAME_FALLBACK = "user"


def sanitize_username(value):
    value = (value or "").strip().lower()
    if "@" in value:
        value = value.split("@", 1)[0]
    value = re.sub(r"\s+", "_", value)
    value = re.sub(r"[^a-z0-9._]", "", value)
    value = re.sub(r"_+", "_", value)
    value = re.sub(r"\.+", ".", value)
    value = value.strip("._")
    return value or USERNAME_FALLBACK

class SignUpForm(UserCreationForm):
    email = forms.EmailField(required=True)
    phone_number = forms.CharField(
        max_length=15,
        required=True,
        widget=forms.TextInput(
            attrs={
                "class": "w-full border border-slate-300 rounded-lg px-3 py-2",
                "placeholder": "Phone Number",
            }
        ),
    )

    class Meta:
        model = User
        fields = ("username", "email", "phone_number", "password1", "password2")

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["username"].widget.attrs.update(
            {
                "class": "w-full border border-slate-300 rounded-lg px-3 py-2",
                "placeholder": "Username",
                "autocapitalize": "none",
                "spellcheck": "false",
            }
        )
        self.fields["email"].widget.attrs.update(
            {
                "class": "w-full border border-slate-300 rounded-lg px-3 py-2",
                "placeholder": "Email Address",
            }
        )
        self.fields["password1"].widget.attrs.update(
            {
                "class": "w-full border border-slate-300 rounded-lg px-3 py-2",
                "placeholder": "Password",
            }
        )
        self.fields["password2"].widget.attrs.update(
            {
                "class": "w-full border border-slate-300 rounded-lg px-3 py-2",
                "placeholder": "Confirm Password",
            }
        )

    def clean_email(self):
        return (self.cleaned_data.get("email") or "").strip().lower()

    def clean_username(self):
        username = sanitize_username(self.cleaned_data.get("username"))
        if User.objects.filter(username__iexact=username).exists():
            raise forms.ValidationError("This username is already taken.")
        return username

    def save(self, commit=True):
        user = super().save(commit=False)
        user.username = self.cleaned_data["username"]
        user.email = self.cleaned_data["email"]

        if commit:
            user.save()

            Profile.objects.update_or_create(
                user=user,
                defaults={
                    "phone_number": self.cleaned_data["phone_number"],
                },
            )

            try:
                send_welcome_email(user)
            except Exception as exc:
                print("Email failed:", exc)

        return user


class ProfileUpdateForm(forms.ModelForm):
    email = forms.EmailField(required=True)

    class Meta:
        model = Profile
        fields = [
            "full_name",
            "phone_number",
            "address_line",
            "city",
            "state",
            "country",
            "pincode",
        ]

    def __init__(self, *args, user=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.user = user

    def clean_full_name(self):
        return (self.cleaned_data.get("full_name") or "").strip()

    def clean_phone_number(self):
        phone = (self.cleaned_data.get("phone_number") or "").strip()
        if phone and not phone.replace("+", "").replace(" ", "").replace("-", "").isdigit():
            raise forms.ValidationError("Enter a valid phone number.")
        return phone

    def clean_pincode(self):
        return (self.cleaned_data.get("pincode") or "").strip()

    def clean_city(self):
        return (self.cleaned_data.get("city") or "").strip()

    def clean_state(self):
        return (self.cleaned_data.get("state") or "").strip()

    def clean_country(self):
        return (self.cleaned_data.get("country") or "").strip()

    def clean_address_line(self):
        return (self.cleaned_data.get("address_line") or "").strip()

    def clean_email(self):
        email = (self.cleaned_data.get("email") or "").strip().lower()
        if User.objects.exclude(pk=getattr(self.user, "pk", None)).filter(email__iexact=email).exists():
            raise forms.ValidationError("This email address is already in use.")
        return email

    def clean(self):
        cleaned_data = super().clean()
        required_fields = {
            "full_name": "Full name is required.",
            "phone_number": "Phone number is required.",
            "address_line": "Address line is required.",
            "city": "City is required.",
            "state": "State is required.",
            "country": "Country is required.",
            "pincode": "Pincode is required.",
        }
        for field_name, message in required_fields.items():
            if not (cleaned_data.get(field_name) or "").strip():
                self.add_error(field_name, message)
        return cleaned_data

    def save(self, commit=True):
        profile = super().save(commit=False)
        if self.user is not None:
            self.user.email = self.cleaned_data["email"]
            if commit:
                self.user.save(update_fields=["email"])
        if commit:
            profile.save()
        return profile
