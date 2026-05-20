from decimal import Decimal

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from .admin_forms import ProductAdminForm
from sellers.models import SellerProfile, SellerProduct

from .models import Category, Product


User = get_user_model()


class ProductApprovalWorkflowTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.user = User.objects.create_user(
            username="shopper",
            email="shopper@example.com",
            password="testpass123",
        )
        cls.admin_user = User.objects.create_user(
            username="staffadmin",
            email="staff@example.com",
            password="testpass123",
            is_staff=True,
        )
        cls.seller_user = User.objects.create_user(
            username="seller-owner",
            email="seller-owner@example.com",
            password="testpass123",
        )
        cls.category = Category.objects.create(name="Shoes", slug="shoes")
        cls.seller = SellerProfile.objects.create(
            user=cls.seller_user,
            business_name="Approval Seller",
            phone="9999999999",
            pan_card_number="ABCDE1234F",
            pan_card_photo="seller_documents/pan.jpg",
            supplier_details="Supplier details",
            registered_office_address="Chennai",
            contact_person_name="Seller User",
            contact_email="seller@example.com",
            payout_account_name="Approval Seller",
            payout_account_number="1234567890",
            payout_ifsc="ABCD0123456",
            terms_accepted=True,
            approval_status=SellerProfile.STATUS_APPROVED,
        )

    def create_product(self, *, name="Pending Runner", status=Product.STATUS_PENDING, available=False):
        product = Product.objects.create(
            category=self.category,
            name=name,
            slug=name.lower().replace(" ", "-"),
            description="Test product",
            price=Decimal("1200.00"),
            stock=5,
            available=available,
            status=status,
        )
        SellerProduct.objects.create(
            seller=self.seller,
            product=product,
            delivery_mode=SellerProduct.OWN_DELIVERY,
            delivery_type=SellerProduct.DELIVERY_TYPE_OWN,
            shipping_details="Ships directly",
        )
        return product

    def test_pending_product_is_hidden_from_public_listing_and_detail(self):
        product = self.create_product()

        list_response = self.client.get(reverse("products:product_list"))
        detail_response = self.client.get(
            reverse("products:product_detail", args=[product.id, product.slug])
        )

        self.assertNotContains(list_response, product.name)
        self.assertEqual(detail_response.status_code, 404)

    def test_admin_approval_makes_product_visible(self):
        product = self.create_product()

        product.approve(save=True)

        list_response = self.client.get(reverse("products:product_list"))
        detail_response = self.client.get(
            reverse("products:product_detail", args=[product.id, product.slug])
        )

        self.assertContains(list_response, product.name)
        self.assertEqual(detail_response.status_code, 200)

    def test_rejected_product_stays_hidden(self):
        product = self.create_product()

        product.reject(reason="Policy mismatch", save=True)

        list_response = self.client.get(reverse("products:product_list"))
        detail_response = self.client.get(
            reverse("products:product_detail", args=[product.id, product.slug])
        )

        self.assertNotContains(list_response, product.name)
        self.assertEqual(detail_response.status_code, 404)

    def test_only_approved_product_is_purchasable(self):
        product = self.create_product()

        add_response = self.client.post(reverse("cart:cart_add", args=[product.id]))
        self.assertEqual(add_response.status_code, 404)

        product.approve(save=True)
        approved_response = self.client.post(
            reverse("cart:cart_add", args=[product.id]),
            HTTP_REFERER=reverse("products:product_detail", args=[product.id, product.slug]),
        )
        self.assertEqual(approved_response.status_code, 302)

    def test_staff_only_approve_and_reject_api(self):
        product = self.create_product()

        anonymous_response = self.client.post(
            reverse("sellers:api_approve_product", args=[product.id])
        )
        self.assertEqual(anonymous_response.status_code, 302)

        self.client.login(username="staffadmin", password="testpass123")
        approve_response = self.client.post(
            reverse("sellers:api_approve_product", args=[product.id])
        )
        self.assertEqual(approve_response.status_code, 200)
        product.refresh_from_db()
        self.assertEqual(product.status, Product.STATUS_APPROVED)

        reject_response = self.client.post(
            reverse("sellers:api_reject_product", args=[product.id]),
            data={"rejection_reason": "Needs better images"},
        )
        self.assertEqual(reject_response.status_code, 200)
        product.refresh_from_db()
        self.assertEqual(product.status, Product.STATUS_REJECTED)
        self.assertEqual(product.rejection_reason, "Needs better images")

    def test_reject_api_requires_reason(self):
        product = self.create_product()
        self.client.login(username="staffadmin", password="testpass123")

        response = self.client.post(
            reverse("sellers:api_reject_product", args=[product.id]),
            data={"rejection_reason": ""},
        )

        self.assertEqual(response.status_code, 400)
        product.refresh_from_db()
        self.assertEqual(product.status, Product.STATUS_PENDING)


class ProductAdminFormTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.category = Category.objects.create(name="Accessories", slug="accessories")

    def test_rejection_reason_required_when_status_is_rejected(self):
        form = ProductAdminForm(
            data={
                "category": self.category.id,
                "brand": "",
                "name": "Bracelet",
                "slug": "bracelet",
                "description": "Test",
                "price": "50.00",
                "discount_percent": "0.00",
                "discount_amount": "0.00",
                "stock": "5",
                "available": "",
                "status": Product.STATUS_REJECTED,
                "rejection_reason": "",
            }
        )

        self.assertFalse(form.is_valid())
        self.assertIn("rejection_reason", form.errors)


class ProductPricingTests(TestCase):
    def test_discounted_price_with_gst_keeps_seller_entered_price_fixed(self):
        category = Category.objects.create(
            name="Stationery",
            slug="stationery",
            gst_rate=Decimal("18.00"),
        )
        product = Product.objects.create(
            category=category,
            name="Pen Set",
            slug="pen-set",
            price=Decimal("10.00"),
            discount_percent=Decimal("0.00"),
            discount_amount=Decimal("0.00"),
            stock=4,
            available=True,
            status=Product.STATUS_APPROVED,
        )

        self.assertEqual(product.discounted_price, Decimal("10.00"))
        self.assertEqual(product.discounted_price_with_gst, Decimal("10.00"))
        self.assertEqual(product.gst_amount_for_price(), Decimal("1.53"))

    def test_no_gst_category_is_supported(self):
        category = Category.objects.create(
            name="Exempt",
            slug="exempt",
            gst_rate=Decimal("0.00"),
        )
        product = Product.objects.create(
            category=category,
            name="Fresh Produce",
            slug="fresh-produce",
            price=Decimal("10.00"),
            stock=3,
            available=True,
            status=Product.STATUS_APPROVED,
        )

        self.assertEqual(product.effective_gst_rate, Decimal("0.00"))
        self.assertEqual(product.discounted_price_with_gst, Decimal("10.00"))
        self.assertEqual(product.gst_amount_for_price(), Decimal("0.00"))
