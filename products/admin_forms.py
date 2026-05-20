from django import forms

from .models import Product


class ProductRejectionForm(forms.Form):
    _selected_action = forms.CharField(widget=forms.MultipleHiddenInput)
    rejection_reason = forms.CharField(
        label="Rejection reason",
        required=True,
        widget=forms.Textarea(
            attrs={
                "rows": 5,
                "placeholder": "Explain clearly why this product is being rejected.",
                "class": "vLargeTextField",
            }
        ),
    )


class ProductAdminForm(forms.ModelForm):
    class Meta:
        model = Product
        fields = "__all__"
        widgets = {
            "rejection_reason": forms.Textarea(
                attrs={
                    "rows": 4,
                    "placeholder": "Enter the rejection reason when status is Rejected.",
                }
            )
        }

    def clean(self):
        cleaned_data = super().clean()
        status = cleaned_data.get("status")
        reason = (cleaned_data.get("rejection_reason") or "").strip()

        if status == Product.STATUS_REJECTED and not reason:
            self.add_error("rejection_reason", "Enter a rejection reason before rejecting this product.")

        if status != Product.STATUS_REJECTED:
            cleaned_data["rejection_reason"] = ""

        return cleaned_data
