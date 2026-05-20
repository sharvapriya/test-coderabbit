from decimal import Decimal

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from .models import Cart, CartItem
from orders.models import Coupon
from products.models import Category, Product, ProductVariant


class VariantCartAddTests(TestCase):
    def setUp(self):
        self.category = Category.objects.create(name="Shoes", slug="shoes")
        self.product = Product.objects.create(
            category=self.category,
            name="Runner",
            slug="runner",
            price=Decimal("1999.00"),
            stock=0,
            available=True,
            status=Product.STATUS_APPROVED,
        )
        self.variant = ProductVariant.objects.create(
            product=self.product,
            size="8",
            color="Blue",
            stock_quantity=3,
            sku="RUNNER-8-BLUE",
            is_active=True,
        )

    def test_variant_product_requires_variant_selection(self):
        response = self.client.post(
            reverse("cart:cart_add", args=[self.product.id]),
            HTTP_X_REQUESTED_WITH="XMLHttpRequest",
        )

        self.assertEqual(response.status_code, 400)
        self.assertJSONEqual(
            response.content,
            {
                "success": False,
                "message": "Please select an available variant before continuing.",
            },
        )

    def test_variant_product_adds_selected_variant_to_cart(self):
        response = self.client.post(
            reverse("cart:cart_add", args=[self.product.id]),
            {"variant_id": self.variant.id},
            HTTP_X_REQUESTED_WITH="XMLHttpRequest",
        )

        self.assertEqual(response.status_code, 200)
        cart_item = CartItem.objects.get()
        self.assertEqual(cart_item.variant, self.variant)
        self.assertEqual(cart_item.quantity, 1)

    def test_variant_quantity_increase_respects_variant_stock(self):
        self.client.post(reverse("cart:cart_add", args=[self.product.id]), {"variant_id": self.variant.id})
        self.client.post(reverse("cart:cart_add", args=[self.product.id]), {"variant_id": self.variant.id})
        self.client.post(reverse("cart:cart_add", args=[self.product.id]), {"variant_id": self.variant.id})

        response = self.client.post(
            reverse("cart:cart_add", args=[self.product.id]),
            {"variant_id": self.variant.id},
            HTTP_X_REQUESTED_WITH="XMLHttpRequest",
        )

        self.assertEqual(response.status_code, 400)
        self.assertIn("Only 3 unit(s) available", response.json()["message"])


class BuyNowRedirectTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(
            username="buyer",
            email="buyer@example.com",
            password="testpass123",
        )
        self.category = Category.objects.create(name="Electronics", slug="electronics")
        self.product = Product.objects.create(
            category=self.category,
            name="Speaker",
            slug="speaker",
            price=Decimal("1499.00"),
            stock=5,
            available=True,
            status=Product.STATUS_APPROVED,
        )

    def test_buy_now_redirects_to_payment_step(self):
        self.client.force_login(self.user)

        response = self.client.get(reverse("cart:buy_now", args=[self.product.id]))

        self.assertRedirects(response, reverse("orders:payment_step"), fetch_redirect_response=False)


class CartPricingTests(TestCase):
    def test_cart_uses_seller_entered_price_without_adding_gst(self):
        category = Category.objects.create(
            name="Books",
            slug="books",
            gst_rate=Decimal("12.00"),
        )
        product = Product.objects.create(
            category=category,
            name="Notebook",
            slug="notebook",
            price=Decimal("10.00"),
            stock=5,
            available=True,
            status=Product.STATUS_APPROVED,
        )
        cart = Cart.objects.create()
        cart_item = CartItem.objects.create(product=product, cart=cart, quantity=2)

        self.assertEqual(cart_item.unit_price, Decimal("10.00"))
        self.assertEqual(cart_item.gst_amount, Decimal("1.07"))
        self.assertEqual(cart_item.get_total_price(), Decimal("20.00"))

    def test_cart_detail_checkout_button_targets_payment_step(self):
        category = Category.objects.create(name="Fashion", slug="fashion")
        product = Product.objects.create(
            category=category,
            name="T-Shirt",
            slug="t-shirt",
            price=Decimal("799.00"),
            stock=5,
            available=True,
            status=Product.STATUS_APPROVED,
        )
        cart = Cart.objects.create()
        CartItem.objects.create(product=product, cart=cart, quantity=1)
        session = self.client.session
        session["cart_id"] = cart.id
        session.save()

        response = self.client.get(reverse("cart:cart_detail"))

        self.assertContains(response, f'action="{reverse("orders:payment_step")}"', html=False)

    def test_cart_detail_shows_discounted_final_total_from_checkout_session(self):
        user = get_user_model().objects.create_user(
            username="discountbuyer",
            email="discountbuyer@example.com",
            password="testpass123",
        )
        category = Category.objects.create(name="Accessories", slug="accessories")
        product = Product.objects.create(
            category=category,
            name="Watch",
            slug="watch",
            price=Decimal("1000.00"),
            stock=5,
            available=True,
            status=Product.STATUS_APPROVED,
        )
        cart = Cart.objects.create(user=user)
        CartItem.objects.create(product=product, cart=cart, quantity=1)
        Coupon.objects.create(
            code="SAVE10",
            discount_percent=10,
            active=True,
        )

        self.client.force_login(user)
        session = self.client.session
        session["checkout_discount"] = {
            "code": "SAVE10",
            "percent": "10.00",
            "amount": "100.00",
        }
        session.save()

        response = self.client.get(reverse("cart:cart_detail"))

        self.assertContains(response, "Discount (SAVE10)")
        self.assertContains(response, "Rs.900.00")
