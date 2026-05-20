from decimal import Decimal

import json

import logging



from django import forms

from django.db.models import Sum

from django.forms import BaseFormSet, formset_factory

import re

from django.core.validators import URLValidator

from django.utils.text import slugify



from products.models import Category, Product, ProductImage, ProductVariant

from orders.models import Coupon



from .models import SellerProduct, SellerProfile

from .services import PayoutCalculator





logger = logging.getLogger(__name__)





class MultipleImageInput(forms.ClearableFileInput):

    allow_multiple_selected = True





class MultipleImageField(forms.FileField):

    def __init__(self, *args, **kwargs):

        kwargs.setdefault(

            "widget",

            MultipleImageInput(

                attrs={"accept": ".jpg,.jpeg,.png,.webp", "multiple": True}

            ),

        )

        super().__init__(*args, **kwargs)



    def clean(self, data, initial=None):

        if not data:

            return []

        files = data if isinstance(data, (list, tuple)) else [data]

        cleaned_files = []

        allowed_extensions = {".jpg", ".jpeg", ".png", ".webp"}

        allowed_content_types = {"image/jpeg", "image/png", "image/webp"}



        if len(files) > 6:

            raise forms.ValidationError("You can upload up to 6 images only.")



        for uploaded in files:

            super().clean(uploaded, initial)

            file_name = (uploaded.name or "").lower()

            extension = f".{file_name.rsplit('.', 1)[-1]}" if "." in file_name else ""

            content_type = (getattr(uploaded, "content_type", "") or "").lower()

            if extension not in allowed_extensions or content_type not in allowed_content_types:

                raise forms.ValidationError("Upload only JPG, PNG, or WEBP images.")

            cleaned_files.append(uploaded)

        return cleaned_files





class SellerProductEntryForm(forms.Form):

    DISCOUNT_CHOICES = [

        ("", "Choose discount"),

        ("5", "5%"),

        ("10", "10%"),

        ("20", "20%"),

        ("30", "30%"),

        ("50", "50%"),

        ("75", "75%"),

        ("100", "100%"),

    ]

    DISCOUNT_TOGGLE_CHOICES = [

        ("no", "No"),

        ("yes", "Yes"),

    ]



    category = forms.ModelChoiceField(queryset=Category.objects.none(), required=False)

    new_category_name = forms.CharField(max_length=250, required=False)

    gst_rate = forms.TypedChoiceField(

        choices=Category.GST_RATE_CHOICES,

        coerce=Decimal,

        required=False,

        initial=Decimal("18.00"),

    )

    hsn_code = forms.CharField(max_length=20, required=False)

    name = forms.CharField(max_length=250)

    slug = forms.CharField(max_length=250, required=False)

    images = MultipleImageField(required=False)

    description = forms.CharField(widget=forms.Textarea, required=False)

    price = forms.DecimalField(max_digits=10, decimal_places=2, min_value=Decimal("0.01"), required=False)

    stock = forms.IntegerField(min_value=0, required=False)

    has_variants = forms.BooleanField(required=False)

    variant_sizes = forms.CharField(

        max_length=250,

        required=False,

        widget=forms.TextInput(attrs={"placeholder": "S, M, L, XL"}),

    )

    variant_colors = forms.CharField(

        max_length=250,

        required=False,

        widget=forms.TextInput(attrs={"placeholder": "Red, Blue, Black"}),

    )

    variant_payload = forms.CharField(required=False, widget=forms.HiddenInput)

    offer_discount = forms.ChoiceField(

        choices=DISCOUNT_TOGGLE_CHOICES,

        initial="no",

        widget=forms.RadioSelect,

    )

    discount_percent = forms.ChoiceField(

        choices=DISCOUNT_CHOICES,

        required=False,

    )

    discounted_amount = forms.DecimalField(

        max_digits=10,

        decimal_places=2,

        required=False,

        widget=forms.NumberInput(

            attrs={"readonly": "readonly", "tabindex": "-1"}

        ),

    )

    def __init__(self, *args, **kwargs):

        super().__init__(*args, **kwargs)

        self.fields["category"].queryset = Category.objects.all().order_by("name")

        self.fields["category"].empty_label = "Select existing category"

        self.fields["new_category_name"].widget.attrs.setdefault(

            "placeholder", "Type a new category if not listed above"

        )

        base_input = (

            "w-full rounded-xl border border-slate-200 bg-white px-3 py-2.5 text-sm "

            "text-slate-900 shadow-sm placeholder:text-slate-400 "

            "focus:border-indigo-500 focus:outline-none focus:ring-2 focus:ring-indigo-200"

        )

        select_input = (

            "w-full rounded-xl border border-slate-200 bg-white px-3 py-2.5 text-sm "

            "text-slate-900 shadow-sm focus:border-indigo-500 focus:outline-none "

            "focus:ring-2 focus:ring-indigo-200"

        )

        textarea_input = (

            "w-full rounded-xl border border-slate-200 bg-white px-3 py-2.5 text-sm "

            "text-slate-900 shadow-sm placeholder:text-slate-400 "

            "focus:border-indigo-500 focus:outline-none focus:ring-2 focus:ring-indigo-200"

        )

        data_fields = {

            "name": "name",

            "slug": "slug",

            "images": "images",

            "description": "description",

            "price": "price",

            "stock": "stock",

            "has_variants": "has-variants",

            "variant_sizes": "variant-sizes",

            "variant_colors": "variant-colors",

            "variant_payload": "variant-payload",

            "offer_discount": "offer-discount",

            "discount_percent": "discount-percent",

            "discounted_amount": "discounted-amount",

            "category": "category",

            "new_category_name": "new-category",

            "gst_rate": "gst-rate",

            "hsn_code": "hsn-code",

        }

        for name, field in self.fields.items():

            if isinstance(field.widget, forms.Select):

                field.widget.attrs.setdefault("class", select_input)

            elif isinstance(field.widget, forms.Textarea):

                field.widget.attrs.setdefault("class", textarea_input)

                field.widget.attrs.setdefault("rows", 4)

            elif isinstance(field.widget, forms.RadioSelect):

                field.widget.attrs.setdefault("class", "hidden")

            elif isinstance(field.widget, forms.CheckboxInput):

                field.widget.attrs.setdefault("class", "h-4 w-4 rounded border-slate-300")

            else:

                field.widget.attrs.setdefault("class", base_input)

            if name in data_fields:

                field.widget.attrs.setdefault("data-field", data_fields[name])

        self.fields["images"].widget.attrs["class"] = "sr-only"

        self.fields["discounted_amount"].widget.attrs["class"] = (

            f"{base_input} bg-slate-100 text-slate-600"

        )



    def clean_new_category_name(self):

        new_category_name = (self.cleaned_data.get("new_category_name") or "").strip()

        if not new_category_name:

            return ""

        if not slugify(new_category_name):

            raise forms.ValidationError(

                "Enter a valid category name using letters or numbers."

            )

        return new_category_name



    def clean_slug(self):

        slug = slugify((self.cleaned_data.get("slug") or "").strip())

        name = (self.data.get(self.add_prefix("name")) or "").strip()

        if not slug and not name and not self.has_meaningful_input():

            return ""

        if slug:

            return slug

        auto_slug = slugify(name)

        if not auto_slug:

            raise forms.ValidationError("Enter a product name to generate a slug.")

        return auto_slug



    


    def clean(self):
        cleaned_data = super().clean()
        if not self.has_meaningful_input():
            cleaned_data["variant_list"] = []
            cleaned_data["discount_percent"] = Decimal("0.00")
            cleaned_data["discount_amount"] = Decimal("0.00")
            cleaned_data["discounted_amount"] = Decimal("0.00")
            return cleaned_data

        new_category_name = cleaned_data.get("new_category_name") or ""
        category = cleaned_data.get("category")
        if not (cleaned_data.get("name") or "").strip():
            self.add_error("name", "Enter a product name.")
        if cleaned_data.get("price") in (None, ""):
            self.add_error("price", "Enter a valid price for this product.")
        if not category and not new_category_name:
            self.add_error("category", "Choose a category or enter a new one.")



        # Validate stock field

        has_variants = cleaned_data.get("has_variants")

        stock = cleaned_data.get("stock")

        if not has_variants and stock is None:

            self.add_error("stock", "Enter stock quantity for this product.")



        price = cleaned_data.get("price") or Decimal("0.00")

        offer_discount = cleaned_data.get("offer_discount") or "no"

        raw_percent = cleaned_data.get("discount_percent") or ""

        if offer_discount == "yes":

            if not raw_percent:

                self.add_error("discount_percent", "Choose a discount percentage.")

            else:

                percent = Decimal(raw_percent)

                discount_value = (price * percent) / Decimal("100")

                discounted_amount = price - discount_value

                if discounted_amount < 0:

                    discounted_amount = Decimal("0.00")

                cleaned_data["discount_percent"] = percent

                cleaned_data["discounted_amount"] = discounted_amount.quantize(

                    Decimal("0.01")

                )

                cleaned_data["discount_amount"] = discount_value.quantize(

                    Decimal("0.01")

                )

        else:

            cleaned_data["discount_percent"] = Decimal("0.00")

            cleaned_data["discount_amount"] = Decimal("0.00")

            cleaned_data["discounted_amount"] = price.quantize(Decimal("0.01")) if price else Decimal("0.00")



        # Only validate variants if has_variants is checked

        if has_variants:

            sizes = [item.strip() for item in re.split(r"[\n,;]+", cleaned_data.get("variant_sizes") or "") if item.strip()]

            colors = [item.strip() for item in re.split(r"[\n,;]+", cleaned_data.get("variant_colors") or "") if item.strip()]

            if not sizes and not colors:

                self.add_error("variant_sizes", "Add at least one size or color for variants.")

                self.add_error("variant_colors", "Add at least one size or color for variants.")



            variant_payload = cleaned_data.get("variant_payload") or ""

            variant_list = []

            if variant_payload:

                try:

                    variant_list = json.loads(variant_payload)

                except json.JSONDecodeError:

                    self.add_error("variant_payload", "Variant data is malformed.")

                    variant_list = []



            if not variant_list:

                self.add_error("variant_payload", "Build variants before submitting.")

            else:

                seen = set()

                validated = []

                for entry in variant_list:

                    size = (entry.get("size") or "").strip() or None

                    color = (entry.get("color") or "").strip() or None

                    sku = (entry.get("sku") or "").strip()

                    stock_quantity = entry.get("stock_quantity")

                    if stock_quantity is None:

                        self.add_error("variant_payload", "Each variant must include stock quantity.")

                        continue

                    try:

                        stock_quantity = int(stock_quantity)

                    except (ValueError, TypeError):

                        self.add_error("variant_payload", "Variant stock must be a whole number.")

                        continue

                    if stock_quantity < 0:

                        self.add_error("variant_payload", "Variant stock cannot be negative.")

                        continue

                    combo = (size, color)

                    if combo in seen:

                        self.add_error("variant_payload", "Duplicate variants are not allowed.")

                        continue

                    seen.add(combo)

                    validated.append({

                        "size": size,

                        "color": color,

                        "stock_quantity": stock_quantity,

                        "sku": sku,

                    })

                cleaned_data["variant_list"] = validated

        else:

            # No variants - clear variant fields and set empty list

            cleaned_data["variant_list"] = []



        return cleaned_data



    def has_meaningful_input(self):

        if not self.is_bound:

            return False



        delete_name = self.add_prefix("DELETE")

        if (self.data.get(delete_name) or "").lower() in {"on", "true", "1"}:

            return False



        data_fields = [

            "category",

            "new_category_name",

            "name",

            "slug",

            "description",

            "price",

            "stock",

            "variant_sizes",

            "variant_colors",

            "variant_payload",

            "discount_percent",

            "discounted_amount",

        ]

        for field_name in data_fields:

            value = self.data.get(self.add_prefix(field_name))

            if value not in (None, "") and str(value).strip():

                return True



        if self.data.get(self.add_prefix("offer_discount")) == "yes":

            return True

        if self.data.get(self.add_prefix("has_variants")) in {"on", "true", "1"}:

            return True

        if self.files.getlist(self.add_prefix("images")):

            return True

        return False



    def _generate_variant_sku(self, product, variant):

        pieces = [str(product.id)]

        if variant.get("size"):

            pieces.append(variant["size"].upper().replace(" ", ""))

        if variant.get("color"):

            pieces.append(variant["color"].upper().replace(" ", ""))

        return "-".join(pieces)



    def _build_unique_category_slug(self, name):

        base_slug = slugify(name)

        candidate = base_slug

        suffix = 1

        while Category.objects.filter(slug=candidate).exists():

            suffix += 1

            candidate = f"{base_slug}-{suffix}"

        return candidate



    def resolve_category(self):

        category = self.cleaned_data.get("category")

        new_category_name = self.cleaned_data.get("new_category_name")

        gst_rate = self.cleaned_data.get("gst_rate") or Decimal("18.00")

        hsn_code = (self.cleaned_data.get("hsn_code") or "").strip()

        if new_category_name:

            category = Category.objects.filter(name__iexact=new_category_name).first()

            if category is None:

                category = Category.objects.create(

                    name=new_category_name,

                    slug=self._build_unique_category_slug(new_category_name),

                    gst_rate=gst_rate,

                    hsn_code=hsn_code,

                )

        elif category is None:

            category, _ = Category.objects.get_or_create(

                slug="general",

                defaults={"name": "General"},

            )

        return category



    def save(self, seller, shared_settings):

        category = self.resolve_category()

        hsn_code = (self.cleaned_data.get("hsn_code") or "").strip() or category.hsn_code

        

        product = Product.objects.create(

            category=category,

            gst_rate=category.gst_rate,

            hsn_code=hsn_code,

            name=self.cleaned_data["name"],

            slug=self.cleaned_data["slug"],

            description=self.cleaned_data.get("description") or "",

            price=self.cleaned_data["price"],

            discount_percent=self.cleaned_data.get("discount_percent") or Decimal("0.00"),

            discount_amount=self.cleaned_data.get("discount_amount") or Decimal("0.00"),

            stock=self.cleaned_data.get('stock') or 0,

            available=False,

            status=Product.STATUS_PENDING,

            rejection_reason="",

        )

        created_images = []

        for index, uploaded in enumerate(self.cleaned_data.get("images") or []):

            created_images.append(

                ProductImage.objects.create(

                    product=product,

                    image=uploaded,

                    sort_order=index,

                )

            )

        if created_images:

            product.image = created_images[0].image.name

            product.save(update_fields=["image"])



        if self.cleaned_data.get("has_variants"):

            variant_list = self.cleaned_data.get("variant_list") or []

            product.stock = 0

            product.save(update_fields=["stock"])

            for variant in variant_list:

                sku = variant.get("sku") or self._generate_variant_sku(product, variant)

                ProductVariant.objects.create(

                    product=product,

                    size=variant.get("size"),

                    color=variant.get("color"),

                    stock_quantity=variant.get("stock_quantity", 0),

                    sku=sku,

                    is_active=True,

                )

            product.stock = product.variants.aggregate(total=Sum("stock_quantity"))["total"] or 0

            product.save(update_fields=["stock"])

        else:

            product.stock = self.cleaned_data["stock"]

            product.save(update_fields=["stock"])



        seller_product = SellerProduct(
            seller=seller,
            product=product,
            delivery_mode=shared_settings.get("delivery_mode", SellerProduct.OWN_DELIVERY),
            delivery_type=shared_settings.get(
                "delivery_type",
                SellerProduct.DELIVERY_TYPE_OWN,
            ),
            estimated_delivery_charge=shared_settings.get(
                "estimated_delivery_charge",
                Decimal("0.00"),
            ),
            shipping_details=shared_settings.get("shipping_details", ""),
            hub_name=shared_settings.get("hub_name", ""),
            hub_address=shared_settings.get("hub_address", ""),
            handover_instructions=shared_settings.get("handover_instructions", ""),
            payout_rate_own_delivery=shared_settings.get(
                "payout_rate_own_delivery",
                Decimal("90.00"),
            ),
            payout_rate_hub_delivery=shared_settings.get(
                "payout_rate_hub_delivery",
                Decimal("82.00"),
            ),
        )

        seller_product.save()

        return seller_product





class BaseSellerProductEntryFormSet(BaseFormSet):

    def clean(self):

        super().clean()

        active_forms = 0

        for form in self.forms:

            if not form.is_bound:

                continue

            if form.has_meaningful_input():

                active_forms += 1



        if active_forms == 0:

            raise forms.ValidationError("Add at least one product before submitting.")





SellerProductEntryFormSet = formset_factory(

    SellerProductEntryForm,

    formset=BaseSellerProductEntryFormSet,

    extra=1,

    can_delete=True,

)





class SellerProductSharedSettingsForm(forms.ModelForm):

    class Meta:

        model = SellerProduct

        fields = [
            "shipping_details",
            "payout_rate_own_delivery",
            "payout_rate_hub_delivery",
        ]
       



    def __init__(self, *args, **kwargs):

        super().__init__(*args, **kwargs)

        base_input = (

            "w-full rounded-xl border border-slate-200 bg-white px-3 py-2.5 text-sm "

            "text-slate-900 shadow-sm placeholder:text-slate-400 "

            "focus:border-indigo-500 focus:outline-none focus:ring-2 focus:ring-indigo-200"

        )

        select_input = (

            "w-full rounded-xl border border-slate-200 bg-white px-3 py-2.5 text-sm "

            "text-slate-900 shadow-sm focus:border-indigo-500 focus:outline-none "

            "focus:ring-2 focus:ring-indigo-200"

        )

        textarea_input = (

            "w-full rounded-xl border border-slate-200 bg-white px-3 py-2.5 text-sm "

            "text-slate-900 shadow-sm placeholder:text-slate-400 "

            "focus:border-indigo-500 focus:outline-none focus:ring-2 focus:ring-indigo-200"

        )

        # # Make all delivery fields optional

        # for field_name in ["estimated_delivery_charge", "shipping_details", "hub_name", "hub_address", "handover_instructions", "payout_rate_own_delivery", "payout_rate_hub_delivery"]:

        #     if field_name in self.fields:

        #         self.fields[field_name].required = False

        self.fields["shipping_details"].required = True
        self.fields["shipping_details"].widget.attrs.setdefault(
            "placeholder",
            "Share dispatch timing, shipping zones, courier process, and any delivery notes for buyers.",
        )
        self.fields["payout_rate_own_delivery"].required = False
        self.fields["payout_rate_own_delivery"].initial = Decimal("90.00")
        self.fields["payout_rate_own_delivery"].widget = forms.HiddenInput()
        self.fields["payout_rate_hub_delivery"].required = False
        self.fields["payout_rate_hub_delivery"].initial = Decimal("82.00")
        self.fields["payout_rate_hub_delivery"].widget = forms.HiddenInput()


        

        for field in self.fields.values():

            if isinstance(field.widget, forms.Select):

                field.widget.attrs.setdefault("class", select_input)

            elif isinstance(field.widget, forms.Textarea):

                field.widget.attrs.setdefault("class", textarea_input)

                field.widget.attrs.setdefault("rows", 4)

            else:

                field.widget.attrs.setdefault("class", base_input)



    def clean(self):

        cleaned_data = super().clean()

        cleaned_data["shipping_details"] = (
            cleaned_data.get("shipping_details") or ""
        ).strip()
        if not cleaned_data["shipping_details"]:
            self.add_error("shipping_details", "Enter shipping details for buyers.")
        cleaned_data["payout_rate_own_delivery"] = (
            cleaned_data.get("payout_rate_own_delivery") or Decimal("90.00")
        )
        cleaned_data["payout_rate_hub_delivery"] = (
            cleaned_data.get("payout_rate_hub_delivery") or Decimal("82.00")
        )
        cleaned_data["delivery_mode"] = SellerProduct.OWN_DELIVERY
        cleaned_data["delivery_type"] = SellerProduct.DELIVERY_TYPE_OWN
        cleaned_data["estimated_delivery_charge"] = Decimal("0.00")
        cleaned_data["hub_name"] = ""
        cleaned_data["hub_address"] = ""
        cleaned_data["handover_instructions"] = ""
        return cleaned_data





class SellerCouponForm(forms.Form):

    coupon_code = forms.CharField(max_length=50, required=False)

    coupon_discount_percent = forms.IntegerField(min_value=0, max_value=100, required=False)

    coupon_active = forms.BooleanField(required=False, initial=False)

    coupon_minimum_purchase_amount = forms.DecimalField(

        max_digits=10,

        decimal_places=2,

        min_value=0,

        required=False,

    )

    coupon_valid_from = forms.DateTimeField(

        required=False,

        input_formats=["%Y-%m-%dT%H:%M"],

        widget=forms.DateTimeInput(

            attrs={"type": "datetime-local"},

            format="%Y-%m-%dT%H:%M",

        ),

    )

    coupon_valid_to = forms.DateTimeField(

        required=False,

        input_formats=["%Y-%m-%dT%H:%M"],

        widget=forms.DateTimeInput(

            attrs={"type": "datetime-local"},

            format="%Y-%m-%dT%H:%M",

        ),

    )



    def __init__(self, *args, seller=None, **kwargs):

        super().__init__(*args, **kwargs)

        self.seller = seller

        base_input = (

            "w-full rounded-xl border border-slate-200 bg-white px-3 py-2.5 text-sm "

            "text-slate-900 shadow-sm placeholder:text-slate-400 "

            "focus:border-indigo-500 focus:outline-none focus:ring-2 focus:ring-indigo-200"

        )

        for name, field in self.fields.items():

            if isinstance(field.widget, forms.CheckboxInput):

                field.widget.attrs.setdefault("class", "h-4 w-4 rounded border-slate-300")

            else:

                field.widget.attrs.setdefault("class", base_input)

            field.widget.attrs.setdefault(

                "data-field",

                {

                    "coupon_code": "coupon-code",

                    "coupon_discount_percent": "coupon-discount-percent",

                    "coupon_active": "coupon-active",

                    "coupon_minimum_purchase_amount": "coupon-minimum-purchase-amount",

                    "coupon_valid_from": "coupon-valid-from",

                    "coupon_valid_to": "coupon-valid-to",

                }[name],

            )



    def clean(self):

        cleaned_data = super().clean()

        coupon_code = (cleaned_data.get("coupon_code") or "").strip().upper()

        coupon_percent = cleaned_data.get("coupon_discount_percent")

        coupon_valid_from = cleaned_data.get("coupon_valid_from")

        coupon_valid_to = cleaned_data.get("coupon_valid_to")

        coupon_active = bool(cleaned_data.get("coupon_active"))

        has_coupon_details = bool(coupon_code or coupon_percent or coupon_valid_from or coupon_valid_to or coupon_active)

        cleaned_data["coupon_code"] = coupon_code

        if has_coupon_details:

            if not coupon_code:

                self.add_error("coupon_code", "Enter a coupon code or generate one.")

            if coupon_percent is None:

                self.add_error("coupon_discount_percent", "Enter a coupon discount percent.")

            if coupon_valid_from and coupon_valid_to and coupon_valid_to <= coupon_valid_from:

                self.add_error("coupon_valid_to", "Valid To must be after Valid From.")

            if coupon_code:

                existing = Coupon.objects.filter(code__iexact=coupon_code)

                if self.seller is not None:

                    existing = existing.exclude(seller=self.seller)

                if existing.exists():

                    self.add_error("coupon_code", "This coupon code is already in use.")

        return cleaned_data



    def save(self, seller, products):

        coupon_code = self.cleaned_data.get("coupon_code") or ""

        if not coupon_code:

            return None

        coupon, _ = Coupon.objects.update_or_create(

            seller=seller,

            code=coupon_code,

            defaults={

                "discount_percent": self.cleaned_data["coupon_discount_percent"],

                "active": bool(self.cleaned_data.get("coupon_active")),

                "valid_from": self.cleaned_data.get("coupon_valid_from"),

                "valid_to": self.cleaned_data.get("coupon_valid_to"),

                "minimum_purchase_amount": self.cleaned_data.get("coupon_minimum_purchase_amount") or 0,

                "product": None,

            },

        )

        return coupon

        coupon_code = self.cleaned_data.get("coupon_code") or ""

        if not coupon_code:

            return None

        coupon, _ = Coupon.objects.update_or_create(

            seller=seller,

            code=coupon_code,

            defaults={

                "discount_percent": self.cleaned_data["coupon_discount_percent"],

                "active": bool(self.cleaned_data.get("coupon_active")),

                "valid_from": self.cleaned_data.get("coupon_valid_from"),

                "valid_to": self.cleaned_data.get("coupon_valid_to"),

                "product": None,

            },

        )

        return coupon





class SellerProductPublishForm(forms.ModelForm):

    gst_rate = forms.TypedChoiceField(

        choices=Category.GST_RATE_CHOICES,

        coerce=Decimal,

        required=False,

        initial=Decimal("18.00"),

    )

    hsn_code = forms.CharField(max_length=20, required=False)

    category = forms.ModelChoiceField(queryset=Category.objects.all(), required=False)

    new_category_name = forms.CharField(max_length=250, required=False)

    name = forms.CharField(max_length=250, required=False)

    slug = forms.SlugField(max_length=250)

    description = forms.CharField(widget=forms.Textarea, required=False)

    price = forms.DecimalField(max_digits=10, decimal_places=2)

    discount_percent = forms.DecimalField(

        max_digits=5,

        decimal_places=2,

        min_value=0,

        max_value=100,

        required=False,

    )

    discount_amount = forms.DecimalField(

        max_digits=10,

        decimal_places=2,

        min_value=0,

        required=False,

    )

    stock = forms.IntegerField(min_value=0)

    has_variants = forms.BooleanField(required=False)

    variant_sizes = forms.CharField(

        max_length=250,

        required=False,

        widget=forms.TextInput(attrs={"placeholder": "S, M, L, XL"}),

    )

    variant_colors = forms.CharField(

        max_length=250,

        required=False,

        widget=forms.TextInput(attrs={"placeholder": "Red, Blue, Black"}),

    )

    variant_payload = forms.CharField(required=False, widget=forms.HiddenInput)

    image = forms.ImageField(required=False)

    images = MultipleImageField(required=False)

    clear_image = forms.BooleanField(required=False, widget=forms.HiddenInput)

    delete_image_ids = forms.CharField(required=False, widget=forms.HiddenInput)

    coupon_code = forms.CharField(max_length=50, required=False)

    coupon_discount_percent = forms.IntegerField(min_value=1, max_value=100, required=False)

    coupon_active = forms.BooleanField(required=False, initial=False)

    coupon_valid_from = forms.DateTimeField(

        required=False,

        input_formats=["%Y-%m-%dT%H:%M"],

        widget=forms.DateTimeInput(

            attrs={"type": "datetime-local"},

            format="%Y-%m-%dT%H:%M",

        ),

    )

    coupon_valid_to = forms.DateTimeField(

        required=False,

        input_formats=["%Y-%m-%dT%H:%M"],

        widget=forms.DateTimeInput(

            attrs={"type": "datetime-local"},

            format="%Y-%m-%dT%H:%M",

        ),

    )



    class Meta:

        model = SellerProduct

        fields = [

            "delivery_mode",

            "delivery_type",

            "estimated_delivery_charge",

            "shipping_details",

            "hub_name",

            "hub_address",

            "handover_instructions",

            "payout_rate_own_delivery",

            "payout_rate_hub_delivery",

        ]



    def __init__(self, *args, **kwargs):

        super().__init__(*args, **kwargs)

        self._existing_coupon = None

        self.fields["category"].queryset = Category.objects.all().order_by("name")

        self.fields["category"].empty_label = "Select existing category"

        self.fields["new_category_name"].widget.attrs.setdefault(

            "placeholder", "Type a new category if not listed above"

        )

        base_input = (

            "w-full rounded-lg border border-slate-200 bg-white px-3 py-2 text-sm "

            "text-slate-900 shadow-sm placeholder:text-slate-400 "

            "focus:border-indigo-500 focus:outline-none focus:ring-2 focus:ring-indigo-200"

        )

        select_input = (

            "w-full rounded-lg border border-slate-200 bg-white px-3 py-2 text-sm "

            "text-slate-900 shadow-sm focus:border-indigo-500 focus:outline-none "

            "focus:ring-2 focus:ring-indigo-200"

        )

        textarea_input = (

            "w-full rounded-lg border border-slate-200 bg-white px-3 py-2 text-sm "

            "text-slate-900 shadow-sm placeholder:text-slate-400 "

            "focus:border-indigo-500 focus:outline-none focus:ring-2 focus:ring-indigo-200"

        )

        data_fields = {

            "category": "category",

            "new_category_name": "new-category",

            "gst_rate": "gst-rate",

            "hsn_code": "hsn-code",

        }

        for name, field in self.fields.items():

            if isinstance(field.widget, forms.Select):

                field.widget.attrs.setdefault("class", select_input)

            elif isinstance(field.widget, forms.Textarea):

                field.widget.attrs.setdefault("class", textarea_input)

                field.widget.attrs.setdefault("rows", 4)

            elif isinstance(field.widget, forms.CheckboxInput):

                field.widget.attrs.setdefault("class", "h-4 w-4 text-indigo-600")

            else:

                field.widget.attrs.setdefault("class", base_input)

            if name in data_fields:

                field.widget.attrs.setdefault("data-field", data_fields[name])
        self.fields["images"].widget.attrs["class"] = "sr-only"
        self._existing_gallery_images = []

        product = getattr(self.instance, "product", None)

        if product:
            self._existing_gallery_images = list(product.images.order_by("sort_order", "id"))

            self.fields["category"].initial = product.category

            self.fields["gst_rate"].initial = product.gst_rate or getattr(product.category, "gst_rate", None)

            self.fields["hsn_code"].initial = product.hsn_code or getattr(product.category, "hsn_code", "")

            self.fields["name"].initial = product.name

            self.fields["slug"].initial = product.slug

            self.fields["description"].initial = product.description

            self.fields["price"].initial = product.price

            self.fields["discount_percent"].initial = product.discount_percent

            self.fields["discount_amount"].initial = product.discount_amount

            self.fields["stock"].initial = product.stock

            variants = list(product.variants.filter(is_active=True).order_by("size", "color"))

            if variants:

                self.fields["has_variants"].initial = True

                self.fields["variant_sizes"].initial = ", ".join(sorted({variant.size for variant in variants if variant.size}))

                self.fields["variant_colors"].initial = ", ".join(sorted({variant.color for variant in variants if variant.color}))

                self.fields["variant_payload"].initial = json.dumps([

                    {

                        "size": variant.size,

                        "color": variant.color,

                        "stock_quantity": variant.stock_quantity,

                        "sku": variant.sku,

                    }

                    for variant in variants

                ])

            seller = getattr(self.instance, "seller", None)

            coupon_qs = Coupon.objects.filter(product=product)

            if seller:

                coupon_qs = coupon_qs.filter(seller=seller)

            self._existing_coupon = coupon_qs.first()

            if self._existing_coupon:

                self.fields["coupon_code"].initial = self._existing_coupon.code

                self.fields["coupon_discount_percent"].initial = (

                    self._existing_coupon.discount_percent

                )

                self.fields["coupon_active"].initial = self._existing_coupon.active

                self.fields["coupon_valid_from"].initial = self._existing_coupon.valid_from

                self.fields["coupon_valid_to"].initial = self._existing_coupon.valid_to
            for gallery_image in self._existing_gallery_images:
                field_name = f"replace_image_{gallery_image.id}"
                self.fields[field_name] = forms.ImageField(required=False)
                self.fields[field_name].widget.attrs.update(
                    {
                        "accept": ".jpg,.jpeg,.png,.webp",
                        "class": "hidden",
                    }
                )



    def clean_new_category_name(self):

        new_category_name = (self.cleaned_data.get("new_category_name") or "").strip()

        if not new_category_name:

            return ""

        if not slugify(new_category_name):

            raise forms.ValidationError(

                "Enter a valid category name using letters or numbers."

            )

        return new_category_name



    def _build_unique_category_slug(self, name):

        base_slug = slugify(name)

        candidate = base_slug

        suffix = 1

        while Category.objects.filter(slug=candidate).exists():

            suffix += 1

            candidate = f"{base_slug}-{suffix}"

        return candidate



    def clean_coupon_code(self):

        code = (self.cleaned_data.get("coupon_code") or "").strip().upper()

        return code



    def _generate_variant_sku(self, product, variant):

        pieces = [str(product.id)]

        if variant.get("size"):

            pieces.append(variant["size"].upper().replace(" ", ""))

        if variant.get("color"):

            pieces.append(variant["color"].upper().replace(" ", ""))

        return "-".join(pieces)

    def _parse_delete_image_ids(self):

        raw_value = (self.cleaned_data.get("delete_image_ids") or "").strip()

        if not raw_value:

            return set()

        valid_ids = {image.id for image in self._existing_gallery_images}

        parsed_ids = set()

        for chunk in raw_value.split(","):

            chunk = chunk.strip()

            if not chunk:

                continue

            try:

                image_id = int(chunk)

            except (TypeError, ValueError):

                self.add_error("delete_image_ids", "Image removal request is invalid.")

                return set()

            if image_id not in valid_ids:

                self.add_error("delete_image_ids", "One of the selected images could not be updated.")

                return set()

            parsed_ids.add(image_id)

        return parsed_ids



    def clean(self):

        cleaned_data = super().clean()

        code = cleaned_data.get("coupon_code") or ""

        discount = cleaned_data.get("coupon_discount_percent")

        valid_from = cleaned_data.get("coupon_valid_from")

        valid_to = cleaned_data.get("coupon_valid_to")

        active = bool(cleaned_data.get("coupon_active"))

        has_coupon_details = bool(code or discount or valid_from or valid_to or active)



        if has_coupon_details:

            if not code:

                self.add_error("coupon_code", "Enter a coupon code to enable a discount.")

            if not discount:

                self.add_error(

                    "coupon_discount_percent",

                    "Enter a discount percent for this coupon.",

                )

        if valid_from and valid_to and valid_to < valid_from:

            self.add_error(

                "coupon_valid_to",

                "Valid-to date must be after the valid-from date.",

            )



        discount_percent = cleaned_data.get("discount_percent") or 0

        discount_amount = cleaned_data.get("discount_amount") or 0

        price = cleaned_data.get("price") or 0

        if discount_percent and discount_amount:

            self.add_error(

                "discount_percent",

                "Choose either a discount percent or a discount amount, not both.",

            )

            self.add_error(

                "discount_amount",

                "Choose either a discount percent or a discount amount, not both.",

            )

        if discount_amount and price and discount_amount >= price:

            self.add_error(

                "discount_amount",

                "Discount amount must be less than the product price.",

            )

        delete_image_ids = self._parse_delete_image_ids()

        cleaned_data["parsed_delete_image_ids"] = delete_image_ids

        kept_gallery_count = sum(
            1 for gallery_image in self._existing_gallery_images if gallery_image.id not in delete_image_ids
        )

        has_existing_cover = bool(getattr(getattr(self.instance, "product", None), "image", None))

        has_cover_after_submit = bool(cleaned_data.get("image")) or (
            has_existing_cover and not cleaned_data.get("clear_image")
        )

        final_media_count = kept_gallery_count + len(cleaned_data.get("images") or [])

        if has_cover_after_submit and not self._existing_gallery_images:

            final_media_count += 1

        if final_media_count > 6:

            self.add_error("images", "You can keep up to 6 images only.")



        if code:

            existing = Coupon.objects.filter(code__iexact=code)

            if self._existing_coupon:

                existing = existing.exclude(id=self._existing_coupon.id)

            if existing.exists():

                self.add_error("coupon_code", "This coupon code is already in use.")



        if cleaned_data.get("has_variants"):

            sizes = [item.strip() for item in re.split(r"[\n,;]+", cleaned_data.get("variant_sizes") or "") if item.strip()]

            colors = [item.strip() for item in re.split(r"[\n,;]+", cleaned_data.get("variant_colors") or "") if item.strip()]

            if not sizes and not colors:

                self.add_error("variant_sizes", "Add at least one size or color for variants.")

                self.add_error("variant_colors", "Add at least one size or color for variants.")



            variant_payload = cleaned_data.get("variant_payload") or ""

            variant_list = []

            if variant_payload:

                try:

                    variant_list = json.loads(variant_payload)

                except json.JSONDecodeError:

                    self.add_error("variant_payload", "Variant data is malformed.")

                    variant_list = []



            if not variant_list:

                self.add_error("variant_payload", "Build variants before saving.")

            else:

                seen = set()

                validated = []

                for entry in variant_list:

                    size = (entry.get("size") or "").strip() or None

                    color = (entry.get("color") or "").strip() or None

                    sku = (entry.get("sku") or "").strip()

                    stock_quantity = entry.get("stock_quantity")

                    if stock_quantity is None:

                        self.add_error("variant_payload", "Each variant must include stock quantity.")

                        continue

                    try:

                        stock_quantity = int(stock_quantity)

                    except (ValueError, TypeError):

                        self.add_error("variant_payload", "Variant stock must be a whole number.")

                        continue

                    if stock_quantity < 0:

                        self.add_error("variant_payload", "Variant stock cannot be negative.")

                        continue

                    combo = (size, color)

                    if combo in seen:

                        self.add_error("variant_payload", "Duplicate variants are not allowed.")

                        continue

                    seen.add(combo)

                    validated.append({

                        "size": size,

                        "color": color,

                        "stock_quantity": stock_quantity,

                        "sku": sku,

                    })

                cleaned_data["variant_list"] = validated

        else:

            cleaned_data["variant_list"] = []



        delivery_type = cleaned_data.get("delivery_type") or SellerProduct.DELIVERY_TYPE_PLATFORM

        estimated_delivery_charge = cleaned_data.get("estimated_delivery_charge") or Decimal("0.00")

        price = cleaned_data.get("price") or Decimal("0.00")

        if delivery_type == SellerProduct.DELIVERY_TYPE_OWN:

            cleaned_data["estimated_delivery_charge"] = Decimal("0.00")

        if estimated_delivery_charge and price and estimated_delivery_charge > price:

            self.add_error(

                "estimated_delivery_charge",

                "Estimated delivery charge cannot exceed the product price.",

            )

        return cleaned_data



    def save(self, seller, commit=True):

        product = getattr(self.instance, "product", None)

        is_create = product is None



        category = self.cleaned_data.get("category")

        new_category_name = self.cleaned_data.get("new_category_name")

        gst_rate = self.cleaned_data.get("gst_rate") or Decimal("18.00")

        hsn_code = (self.cleaned_data.get("hsn_code") or "").strip()

        if new_category_name:

            category = Category.objects.filter(name__iexact=new_category_name).first()

            if category is None:

                category = Category.objects.create(

                    name=new_category_name,

                    slug=self._build_unique_category_slug(new_category_name),

                    gst_rate=gst_rate,

                    hsn_code=hsn_code,

                )

        elif category is None:

            category, _ = Category.objects.get_or_create(

                slug="general",

                defaults={"name": "General"},

            )



        if is_create:

            product = Product(

                available=False,

                status=Product.STATUS_PENDING,

                rejection_reason="",

            )



        product.category = category

        product.gst_rate = category.gst_rate

        product.hsn_code = hsn_code or category.hsn_code

        product.name = self.cleaned_data["name"]

        product.slug = self.cleaned_data["slug"]

        product.description = self.cleaned_data["description"]

        product.price = self.cleaned_data["price"]

        product.discount_percent = self.cleaned_data.get("discount_percent") or 0

        product.discount_amount = self.cleaned_data.get("discount_amount") or 0

        product.status = Product.STATUS_PENDING

        product.rejection_reason = ""

        product.available = False

        if self.cleaned_data.get("image"):

            product.image = self.cleaned_data["image"]

        if commit:

            product.save()

            deleted_image_ids = self.cleaned_data.get("parsed_delete_image_ids") or set()

            gallery_images = list(product.images.order_by("sort_order", "id"))

            for gallery_image in gallery_images:

                replacement = self.cleaned_data.get(f"replace_image_{gallery_image.id}")

                if replacement:

                    gallery_image.image = replacement

                    gallery_image.save(update_fields=["image"])

            if deleted_image_ids:

                product.images.filter(id__in=deleted_image_ids).delete()

            next_sort_order = product.images.count()

            for uploaded in self.cleaned_data.get("images") or []:

                ProductImage.objects.create(

                    product=product,

                    image=uploaded,

                    sort_order=next_sort_order,

                )

                next_sort_order += 1

            remaining_gallery = list(product.images.order_by("sort_order", "id"))

            for index, gallery_image in enumerate(remaining_gallery):

                if gallery_image.sort_order != index:

                    gallery_image.sort_order = index

                    gallery_image.save(update_fields=["sort_order"])

            if self.cleaned_data.get("clear_image"):

                product.image = None

            if remaining_gallery:

                product.image = remaining_gallery[0].image.name

            elif self.cleaned_data.get("image"):

                product.image = self.cleaned_data["image"]

            elif self.cleaned_data.get("clear_image"):

                product.image = None

            product.save(update_fields=["image"])



        if self.cleaned_data.get("has_variants"):

            variant_list = self.cleaned_data.get("variant_list") or []

            if not is_create and product.id:

                product.variants.all().delete()

            for variant in variant_list:

                sku = variant.get("sku") or self._generate_variant_sku(product, variant)

                ProductVariant.objects.create(

                    product=product,

                    size=variant.get("size"),

                    color=variant.get("color"),

                    stock_quantity=variant.get("stock_quantity", 0),

                    sku=sku,

                    is_active=True,

                )

            product.stock = product.variants.aggregate(total=Sum("stock_quantity"))["total"] or 0

        else:

            if not is_create and product.variants.exists():

                product.variants.all().delete()

            product.stock = self.cleaned_data["stock"]



        if commit:

            product.save()



        seller_product = super().save(commit=False)

        seller_product.seller = seller

        seller_product.product = product

        if seller_product.delivery_mode == SellerProduct.OWN_DELIVERY:

            seller_product.delivery_type = SellerProduct.DELIVERY_TYPE_OWN



        if commit:

            seller_product.save()

            code = (self.cleaned_data.get("coupon_code") or "").strip().upper()

            discount = self.cleaned_data.get("coupon_discount_percent")

            active = bool(self.cleaned_data.get("coupon_active"))

            valid_from = self.cleaned_data.get("coupon_valid_from")

            valid_to = self.cleaned_data.get("coupon_valid_to")

            if code and discount:

                if self._existing_coupon:

                    self._existing_coupon.code = code

                    self._existing_coupon.discount_percent = discount

                    self._existing_coupon.active = active

                    self._existing_coupon.valid_from = valid_from

                    self._existing_coupon.valid_to = valid_to

                    self._existing_coupon.seller = seller

                    self._existing_coupon.product = product

                    self._existing_coupon.save()

                else:

                    Coupon.objects.create(

                        code=code,

                        discount_percent=discount,

                        active=active,

                        valid_from=valid_from,

                        valid_to=valid_to,

                        seller=seller,

                        product=product,

                    )

            elif self._existing_coupon:

                self._existing_coupon.active = False

                self._existing_coupon.save(update_fields=["active"])

        return seller_product



    @property

    def approximate_payout(self):

        if not hasattr(self, "cleaned_data"):

            return None

        price = self.cleaned_data.get("price")

        if price is None:

            return None

        delivery_type = self.cleaned_data.get("delivery_type") or SellerProduct.DELIVERY_TYPE_PLATFORM

        estimated_delivery_charge = self.cleaned_data.get("estimated_delivery_charge") or Decimal("0.00")

        try:

            return PayoutCalculator().calculate_approximate_payout(

                price=price,

                delivery_type=delivery_type,

                estimated_delivery_charge=estimated_delivery_charge,

            )

        except forms.ValidationError:

            return None



class SellerProfileRegistrationForm(forms.ModelForm):

    product_categories = forms.ModelMultipleChoiceField(

        queryset=Category.objects.none(),

        required=True,

        widget=forms.CheckboxSelectMultiple,

    )



    class Meta:

        model = SellerProfile

        fields = [

            "business_name",

            "brand_name",

            "phone",

            "website",

            "pan_card_number",

            # "pan_card_photo",

            "business_pan_card_number",

            # "business_pan_card_photo",

            "aadhar_number",

            "gst_number",

            "payout_upi_id",

            "payout_phonepay_gpay_number",

            "supplier_details",

            # "msme_details",

            "registered_office_address",

            "contact_person_name",

            "contact_email",

            "alternate_phone",

            "seller_signature",

            "product_categories",

            "payout_account_name",

            "payout_account_number",

            "payout_ifsc",

            "terms_accepted",

        ]



    # def __init__(self, *args, **kwargs):

    #     super().__init__(*args, **kwargs)

    #     self.fields["product_categories"].queryset = Category.objects.order_by("name")

    #     input_class = (

    #         "w-full rounded border border-gray-300 px-3 py-2 text-sm "

    #         "focus:border-indigo-500 focus:outline-none"

    #     )

    def __init__(self, *args, **kwargs):

        has_saved_signature = kwargs.pop("has_saved_signature", False)

        super().__init__(*args, **kwargs)

        self.has_saved_signature = has_saved_signature

        self.fields["product_categories"].queryset = Category.objects.order_by("name")

        self.fields["seller_signature"].required = not (

            bool(getattr(self.instance, "pk", None)) or has_saved_signature

        )

        self.fields["business_pan_card_number"].required = False

        self.fields["seller_signature"].widget.attrs.setdefault("accept", "image/*")

        self.fields["website"].widget = forms.TextInput()

        input_class = (

            "w-full rounded border border-gray-300 px-3 py-2 text-sm "

            "focus:border-indigo-500 focus:outline-none"

        )

        for field in self.fields.values():

            if isinstance(field.widget, forms.CheckboxInput):

                field.widget.attrs.setdefault("class", "h-4 w-4")

            elif isinstance(field.widget, forms.CheckboxSelectMultiple):

                field.widget.attrs.setdefault("class", "space-y-1")

            elif isinstance(field.widget, forms.Textarea):

                field.widget.attrs.setdefault("class", input_class)

                field.widget.attrs.setdefault("rows", 3)

            else:

                field.widget.attrs.setdefault("class", input_class)

        

    def clean_pan_card_number(self):

        pan_number = (self.cleaned_data.get("pan_card_number") or "").strip().upper()

        if not re.fullmatch(r"[A-Z]{5}[0-9]{4}[A-Z]", pan_number):

            raise forms.ValidationError("Enter a valid PAN number (example: ABCDE1234F).")

        return pan_number



    def clean_business_pan_card_number(self):

        bus_pan = (self.cleaned_data.get("business_pan_card_number") or "").strip().upper()

        if bus_pan and not re.fullmatch(r"[A-Z]{5}[0-9]{4}[A-Z]", bus_pan):

            raise forms.ValidationError("Enter a valid business PAN number (example: ABCDE1234F).")

        return bus_pan



    def clean_aadhar_number(self):

        aadhar = (self.cleaned_data.get("aadhar_number") or "").strip()

        if aadhar and not re.fullmatch(r"\d{12}", aadhar):

            raise forms.ValidationError("Enter a valid 12-digit Aadhaar number.")

        return aadhar



    def clean_gst_number(self):

        gst = (self.cleaned_data.get("gst_number") or "").strip().upper()

        if gst and not re.fullmatch(r"[0-9]{2}[A-Z]{5}[0-9]{4}[A-Z]{1}[1-9A-Z]{1}Z[0-9A-Z]{1}", gst):

            raise forms.ValidationError("Enter a valid GSTIN.")

        return gst



    def clean_website(self):

        website = (self.cleaned_data.get("website") or "").strip()

        if not website:

            return ""



        normalized = website

        if normalized.startswith("http://"):

            normalized = "https://" + normalized[len("http://"):]

        elif not normalized.startswith("https://"):

            normalized = f"https://{normalized}"



        if not re.fullmatch(

            r"^https://(?:www\.)?(?:[A-Za-z0-9-]+\.)+[A-Za-z]{2,}(?::\d+)?(?:[/?#][^\s]*)?$",

            normalized,

        ):

            raise forms.ValidationError("Enter a valid website URL.")



        URLValidator(schemes=["https"])(normalized)

        return normalized



    def clean_payout_upi_id(self):

        upi = (self.cleaned_data.get("payout_upi_id") or "").strip()

        if upi and not re.fullmatch(r"^[\w.\-]{2,256}@[\w]{2,64}$", upi):

            raise forms.ValidationError("Enter a valid UPI ID (example: name@bank).")

        return upi



    def clean_payout_phonepay_gpay_number(self):

        payout_number = (self.cleaned_data.get("payout_phonepay_gpay_number") or "").strip()

        if not payout_number:

            return ""



        normalized = re.sub(r"[\s\-]", "", payout_number)

        if normalized.startswith("+91"):

            normalized = normalized[3:]

        elif normalized.startswith("91") and len(normalized) == 12:

            normalized = normalized[2:]



        if not re.fullmatch(r"\d{10}", normalized):

            raise forms.ValidationError("Enter a valid 10-digit PhonePe/GPay number.")

        return normalized



    def clean_brand_name(self):

        return (self.cleaned_data.get("brand_name") or "").strip()



    def clean(self):

        cleaned_data = super().clean()

        if not cleaned_data.get("seller_signature") and not self.has_saved_signature:

            self.add_error("seller_signature", "Upload your signature before continuing.")

        if not cleaned_data.get("terms_accepted"):

            self.add_error("terms_accepted", "You must agree to the terms and conditions to submit registration.")

        categories = cleaned_data.get("product_categories")

        if not categories:

            self.add_error("product_categories", "Select at least one product category.")

        return cleaned_data

