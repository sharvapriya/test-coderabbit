from decimal import Decimal
from pathlib import Path

from django import forms
from django.core.exceptions import ValidationError
from django.utils.html import strip_tags
from products.models import Product

from .models import DeliveryAssignment, Order, ReturnRequest, Review, ReviewReport


class MultiFileInput(forms.ClearableFileInput):
    allow_multiple_selected = True


class MultiFileField(forms.FileField):
    widget = MultiFileInput

    def clean(self, data, initial=None):
        single_file_clean = super().clean
        if not data:
            return []
        if isinstance(data, (list, tuple)):
            return [single_file_clean(item, initial) for item in data]
        return [single_file_clean(data, initial)]


class OrderCreateForm(forms.ModelForm):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        input_class = (
            "w-full rounded-lg border border-slate-300 px-3 py-2 text-sm "
            "focus:border-indigo-500 focus:outline-none focus:ring-2 focus:ring-indigo-200"
        )
        for field in self.fields.values():
            field.widget.attrs.update({"class": input_class})
            
        self.fields["full_name"].widget.attrs.update({"autocomplete": "name"})
        self.fields["email"].widget.attrs.update({"autocomplete": "email"})
        self.fields["phone_number"].widget.attrs.update({"autocomplete": "tel"})
        self.fields["address"].widget.attrs.update({"autocomplete": "street-address"})
        self.fields["city"].widget.attrs.update({"autocomplete": "address-level2"})
        self.fields["state"].widget.attrs.update({"autocomplete": "address-level1"})
        self.fields["pincode"].widget.attrs.update({"autocomplete": "postal-code"})
        self.fields["country"].widget.attrs.update({"autocomplete": "country-name"})

    class Meta:
        model = Order
        fields = ["full_name", "email", "phone_number", "address", "city", "state", "pincode", "country"]


class DiscountApplyForm(forms.Form):
    code = forms.CharField(max_length=50, label="Discount Code")

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["code"].widget.attrs.update(
            {
                "class": "w-full rounded-lg border border-slate-300 px-3 py-2 text-sm focus:border-indigo-500 focus:outline-none focus:ring-2 focus:ring-indigo-200",
                "placeholder": "Enter discount code",
                "autocomplete": "off",
            }
        )

    def clean_code(self):
        return self.cleaned_data["code"].strip().upper()


class DeliveryAssignmentUpdateForm(forms.ModelForm):
    class Meta:
        model = DeliveryAssignment
        fields = [
            "status",
            "cod_payment_status",
            "cod_collected_amount",
            "customer_note",
            "internal_note",
        ]

    def __init__(self, *args, **kwargs):
        self.order = kwargs.pop("order", None)
        super().__init__(*args, **kwargs)
        input_class = (
            "w-full rounded-lg border border-slate-300 px-3 py-2 text-sm "
            "focus:border-indigo-500 focus:outline-none focus:ring-2 focus:ring-indigo-200"
        )
        for field_name, field in self.fields.items():
            if field_name in {"customer_note", "internal_note"}:
                field.widget.attrs.update({"class": input_class, "rows": 3})
            else:
                field.widget.attrs.update({"class": input_class})

        if not self.order or self.order.payment_method != Order.PAYMENT_COD:
            self.fields["cod_payment_status"].initial = DeliveryAssignment.COD_NOT_APPLICABLE
            self.fields["cod_payment_status"].disabled = True
            self.fields["cod_collected_amount"].disabled = True

    def clean(self):
        cleaned_data = super().clean()
        status = cleaned_data.get("status")
        cod_payment_status = cleaned_data.get("cod_payment_status")
        cod_collected_amount = cleaned_data.get("cod_collected_amount")

        if not self.order or self.order.payment_method != Order.PAYMENT_COD:
            cleaned_data["cod_payment_status"] = DeliveryAssignment.COD_NOT_APPLICABLE
            cleaned_data["cod_collected_amount"] = Decimal("0")
            return cleaned_data

        if status == DeliveryAssignment.STATUS_DELIVERED and cod_payment_status != DeliveryAssignment.COD_COLLECTED:
            self.add_error(
                "cod_payment_status",
                "For COD orders, mark payment as Collected when order is delivered.",
            )

        if cod_payment_status == DeliveryAssignment.COD_COLLECTED:
            expected = self.order.get_total_cost()
            amount = cod_collected_amount or Decimal("0")
            if amount <= 0:
                self.add_error("cod_collected_amount", "Enter the amount collected from the customer.")
            elif amount != expected:
                self.add_error(
                    "cod_collected_amount",
                    f"Collected amount should match order total ({expected}).",
                )

        if cod_payment_status != DeliveryAssignment.COD_COLLECTED:
            cleaned_data["cod_collected_amount"] = Decimal("0")

        return cleaned_data


class ReturnRequestForm(forms.ModelForm):
    photos = MultiFileField(
        required=False,
        widget=MultiFileInput(
            attrs={
                "class": "block w-full rounded-lg border border-slate-300 bg-white px-3 py-2 text-sm text-slate-600 file:mr-4 file:rounded-lg file:border-0 file:bg-indigo-50 file:px-4 file:py-2 file:text-sm file:font-semibold file:text-indigo-700 hover:file:bg-indigo-100",
                "multiple": True,
                "accept": ".jpg,.jpeg,.png,.gif,.webp",
            }
        ),
        help_text="Upload 1 to 5 screenshots or photos.",
    )
    product = forms.ModelChoiceField(
        queryset=Product.objects.none(),
        empty_label="-- Choose a product --",
        label="Select Product to Return",
        widget=forms.Select(attrs={
            "class": "w-full rounded-lg border border-slate-300 px-3 py-2 text-sm focus:border-indigo-500 focus:outline-none focus:ring-2 focus:ring-indigo-200"
        })
    )

    class Meta:
        model = ReturnRequest
        fields = ["product", "reason", "description"]

    def __init__(self, *args, **kwargs):
        self.order = kwargs.pop("order", None)
        super().__init__(*args, **kwargs)
        self.eligible_order_items = []
        self.single_product_choice = None

        input_class = (
            "w-full rounded-lg border border-slate-300 px-3 py-2 text-sm "
            "focus:border-indigo-500 focus:outline-none focus:ring-2 focus:ring-indigo-200"
        )

        textarea_class = (
            "w-full rounded-lg border border-slate-300 px-3 py-2 text-sm "
            "focus:border-indigo-500 focus:outline-none focus:ring-2 focus:ring-indigo-200"
        )

        # Populate product field with items from the order that have been delivered
        if self.order:
            from sellers.models import SellerPayout

            delivered_product_ids = []
            seen_product_ids = set()
            for item in self.order.items.select_related("product", "seller_payout"):
                try:
                    payout = item.seller_payout
                    if payout and payout.delivery_status == SellerPayout.DELIVERY_DELIVERED:
                        self.eligible_order_items.append(item)
                        if item.product_id not in seen_product_ids:
                            delivered_product_ids.append(item.product_id)
                            seen_product_ids.add(item.product_id)
                except Exception:
                    continue

            self.fields["product"].queryset = Product.objects.filter(
                id__in=delivered_product_ids
            ).order_by("name")

            if len(delivered_product_ids) == 1:
                self.single_product_choice = self.eligible_order_items[0]
                self.fields["product"].empty_label = None
                if not self.is_bound:
                    self.initial["product"] = delivered_product_ids[0]

        # Apply Tailwind styling
        for field_name, field in self.fields.items():
            if field_name == "description":
                field.widget.attrs.update({
                    "class": textarea_class,
                    "rows": 4,
                    "placeholder": "Provide additional details about why you want to return this item..."
                })
            elif field_name != "product":
                field.widget.attrs.update({"class": input_class})

    def clean(self):
        cleaned_data = super().clean()

        # Verify the product belongs to the order and is delivered
        if self.order and cleaned_data.get("product"):
            from sellers.models import SellerPayout

            product = cleaned_data.get("product")
            item = self.order.items.filter(product=product).select_related("seller_payout").first()

            if not item:
                raise forms.ValidationError("Selected product is not in this order.")

            try:
                payout = item.seller_payout
                if not payout or payout.delivery_status != SellerPayout.DELIVERY_DELIVERED:
                    raise forms.ValidationError("Selected product has not been delivered yet.")
            except Exception:
                raise forms.ValidationError("Unable to verify delivery status of selected product.")

        return cleaned_data

    def clean_photos(self):
        photos = self.files.getlist("photos")
        if not photos:
            return photos

        if len(photos) > 5:
            raise ValidationError("You can upload a maximum of 5 screenshots or photos.")

        allowed_extensions = [".jpg", ".jpeg", ".png", ".gif", ".webp"]
        for photo in photos:
            ext = Path(photo.name).suffix.lower()
            if ext not in allowed_extensions:
                raise ValidationError(f"File type '{ext}' not allowed. Please use JPG, JPEG, PNG, GIF, or WEBP.")
            if photo.size > 5 * 1024 * 1024:
                raise ValidationError(f"Image '{photo.name}' is too large. Maximum file size is 5MB.")

        return photos


class ReviewForm(forms.ModelForm):
    images = MultiFileField(
        required=False,
        widget=MultiFileInput(attrs={
            "multiple": True,
            "accept": ".jpg,.jpeg,.png,.gif",
            "class": "block w-full text-sm text-slate-500 file:mr-4 file:py-2 file:px-4 file:rounded-lg file:border-0 file:text-sm file:font-semibold file:bg-indigo-50 file:text-indigo-700 hover:file:bg-indigo-100"
        }),
        help_text="Upload 1-5 images (JPG, PNG, GIF)"
    )

    class Meta:
        model = Review
        fields = ["rating", "comment"]
        widgets = {
            "rating": forms.RadioSelect(choices=((i, f"{i} Star{'s' if i != 1 else ''}") for i in range(1, 6))),
            "comment": forms.Textarea(attrs={
                "rows": 4,
                "placeholder": "Share your experience with this product...",
                "class": "w-full rounded-lg border border-slate-300 px-3 py-2 text-sm focus:border-indigo-500 focus:outline-none focus:ring-2 focus:ring-indigo-200",
                "maxlength": "1000",
            })
        }

    def __init__(self, *args, **kwargs):
        self.user = kwargs.pop("user", None)
        self.product = kwargs.pop("product", None)
        super().__init__(*args, **kwargs)

        # Style the rating radio buttons
        self.fields["rating"].widget.attrs.update({
            "class": "mr-2 h-4 w-4 cursor-pointer accent-indigo-600"
        })

    def clean(self):
        return super().clean()

    def clean_comment(self):
        comment = strip_tags(self.cleaned_data.get("comment", ""))
        return " ".join(comment.split())

    def clean_images(self):
        images = self.files.getlist("images")

        # Check maximum number of images
        if len(images) > 5:
            raise ValidationError("You can upload a maximum of 5 images.")

        # Validate each image
        allowed_extensions = [".jpg", ".jpeg", ".png", ".gif"]
        for image in images:
            ext = Path(image.name).suffix.lower()
            if ext not in allowed_extensions:
                raise ValidationError(f"File type '{ext}' not allowed. Please use JPG, PNG, or GIF.")
            if image.size > 5 * 1024 * 1024:  # 5MB limit
                raise ValidationError(f"Image '{image.name}' is too large. Maximum file size is 5MB.")

        return images


class ReviewReportForm(forms.Form):
    REASON_FAKE = "fake_spam"
    REASON_NOT_PURCHASED = "not_purchased"
    REASON_ABUSIVE = "abusive_language"
    REASON_COMPETITOR = "competitor_manipulation"
    REASON_OTHER = "other"

    REASON_CHOICES = (
        (REASON_FAKE, "Fake / spam"),
        (REASON_NOT_PURCHASED, "User didn’t purchase"),
        (REASON_ABUSIVE, "Abusive language"),
        (REASON_COMPETITOR, "Competitor manipulation"),
        (REASON_OTHER, "Other"),
    )

    reason_choice = forms.ChoiceField(
        choices=REASON_CHOICES,
        widget=forms.Select(
            attrs={
                "class": "w-full rounded-xl border border-slate-300 px-3 py-2 text-sm text-slate-700",
                "data-report-reason-select": "",
            }
        ),
    )
    reason_details = forms.CharField(
        required=False,
        widget=forms.Textarea(
            attrs={
                "rows": 3,
                "placeholder": "Add more context for this report",
                "class": "w-full rounded-xl border border-slate-300 px-3 py-2 text-sm text-slate-700",
                "maxlength": "500",
                "data-report-reason-details": "",
            }
        ),
    )

    def clean(self):
        cleaned_data = super().clean()
        choice = cleaned_data.get("reason_choice", "")
        details = strip_tags(cleaned_data.get("reason_details", ""))
        details = " ".join(details.split())

        if choice == self.REASON_OTHER and len(details) < 5:
            raise ValidationError("Please add a short explanation when choosing Other.")

        choice_label = dict(self.REASON_CHOICES).get(choice, "")
        cleaned_data["reason"] = choice_label if choice != self.REASON_OTHER else f"Other: {details}"
        cleaned_data["reason_details"] = details
        return cleaned_data
