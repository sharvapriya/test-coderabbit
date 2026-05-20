from django.test import TestCase



# Create your tests here.



import json

import hashlib

import hmac

from decimal import Decimal

from unittest.mock import patch



import razorpay

from django.conf import settings

from django.contrib.auth import get_user_model

from django.core import mail

from django.core.files.uploadedfile import SimpleUploadedFile

from django.utils.datastructures import MultiValueDict

from django.test import Client, TestCase

from django.urls import reverse

from accounts.models import Address



from cart.models import Cart, CartItem

from orders.forms import OrderCreateForm, ReviewForm

from orders.models import DeliveryAssignment, Order, OrderItem, OrderStatusHistory, PaymentTransaction, Wallet, WalletTransaction

from orders.views import _create_order_with_items, _sync_order_status_from_delivery

from orders.utils.email import handle_order_status_change

from products.models import Category, Product





class CancelOrderTests(TestCase):

    def setUp(self):

        self.client = Client()

        self.user = get_user_model().objects.create_user(

            username="buyer",

            email="buyer@example.com",

            password="testpass123",

        )

        self.client.force_login(self.user)

        self.category = Category.objects.create(name="Electronics", slug="electronics")

        self.product = Product.objects.create(

            category=self.category,

            name="Headphones",

            slug="headphones",

            price=Decimal("500.00"),

            stock=3,

            available=True,

        )

        self.second_product = Product.objects.create(

            category=self.category,

            name="Keyboard",

            slug="keyboard",

            price=Decimal("300.00"),

            stock=8,

            available=True,

        )



    def _create_order(

        self,

        *,

        status=Order.STATUS_PLACED,

        payment_method=Order.PAYMENT_ONLINE,

        paid=True,

        total_amount=Decimal("1000.00"),

        discount_amount=Decimal("0.00"),

        delivery_charge=Decimal("0.00"),

    ):

        order = Order.objects.create(

            user=self.user,

            full_name="Buyer One",

            email="buyer@example.com",

            address="123 Street",

            paid=paid,

            payment_method=payment_method,

            total_amount=total_amount,

            discount_amount=discount_amount,

            delivery_charge=delivery_charge,

            status=status,

        )

        order_item = OrderItem.objects.create(

            order=order,

            product=self.product,

            price=Decimal("500.00"),

            quantity=2,

        )

        return order, order_item



    def test_cancel_paid_order_restores_stock_and_refunds_wallet(self):

        order, _ = self._create_order(status=Order.STATUS_CONFIRMED, payment_method=Order.PAYMENT_ONLINE, paid=True)



        response = self.client.post(

            reverse("orders:cancel_order_api", args=[order.id]),

            {"reason": "Customer changed mind"},

            HTTP_ACCEPT="application/json",

            HTTP_X_REQUESTED_WITH="XMLHttpRequest",

        )



        self.assertEqual(response.status_code, 200)

        order.refresh_from_db()

        self.product.refresh_from_db()

        wallet = Wallet.objects.get(user=self.user)



        self.assertEqual(order.status, Order.STATUS_CANCELLED)

        self.assertEqual(order.cancelled_by, self.user)

        self.assertEqual(order.cancellation_reason, "Customer changed mind")

        self.assertIsNotNone(order.cancelled_at)

        self.assertEqual(self.product.stock, 5)

        self.assertEqual(wallet.balance, Decimal("1000.00"))

        self.assertEqual(OrderStatusHistory.objects.filter(order=order).count(), 2)





class OrderItemGstFreezeTests(TestCase):

    def setUp(self):

        self.client = Client()

        self.user = get_user_model().objects.create_user(

            username="gstbuyer",

            email="gstbuyer@example.com",

            password="testpass123",

        )

        self.client.force_login(self.user)

        self.category = Category.objects.create(

            name="Books",

            slug="books",

            gst_rate=Decimal("12.00"),

            hsn_code="4901",

        )

        self.product = Product.objects.create(

            category=self.category,

            name="Tax Guide",

            slug="tax-guide",

            price=Decimal("100.00"),

            gst_rate=Decimal("12.00"),

            hsn_code="4901",

            stock=3,

            available=True,

        )

        self.second_product = Product.objects.create(

            category=self.category,

            name="Ledger Book",

            slug="ledger-book",

            price=Decimal("300.00"),

            gst_rate=Decimal("12.00"),

            hsn_code="4901",

            stock=8,

            available=True,

        )

        self.cart = Cart.objects.create()

        self.cart_item = CartItem.objects.create(

            cart=self.cart,

            product=self.product,

            quantity=2,

        )



    def _create_order(

        self,

        *,

        status=Order.STATUS_PLACED,

        payment_method=Order.PAYMENT_ONLINE,

        paid=True,

        total_amount=Decimal("1000.00"),

        discount_amount=Decimal("0.00"),

        delivery_charge=Decimal("0.00"),

    ):

        order = Order.objects.create(

            user=self.user,

            full_name="Buyer One",

            email="buyer@example.com",

            address="123 Street",

            paid=paid,

            payment_method=payment_method,

            total_amount=total_amount,

            discount_amount=discount_amount,

            delivery_charge=delivery_charge,

            status=status,

        )

        order_item = OrderItem.objects.create(

            order=order,

            product=self.product,

            price=Decimal("500.00"),

            quantity=2,

        )

        return order, order_item



    def test_create_order_freezes_product_gst_on_order_item(self):
        form = OrderCreateForm(
            data={
                "full_name": "GST Buyer",
                "email": "gstbuyer@example.com",
                "phone_number": "9999999999",
                "address": "123 Tax Street",
            }
        )

        self.assertTrue(form.is_valid(), form.errors)

        order = _create_order_with_items(
            self.user,
            form,
            "",
            Decimal("0.00"),
            self.cart_item.get_total_price().quantize(Decimal("0.01")),
            Order.PAYMENT_ONLINE,
            [self.cart_item],
        )

        order_item = order.items.get()

        self.assertEqual(order.total_amount, Decimal("200.00"))
        self.assertEqual(order_item.price, Decimal("100.00"))
        self.assertEqual(order_item.gst_rate, Decimal("12.00"))
        self.assertEqual(order_item.gst_amount, Decimal("10.71"))
        self.assertEqual(order_item.taxable_subtotal, Decimal("200.00"))
        self.assertEqual(order_item.gst_subtotal, Decimal("21.42"))
        self.assertEqual(order_item.get_cost(), Decimal("200.00"))

    def test_return_form_accepts_up_to_five_photos(self):
        order_item = OrderItem.objects.create(
            order=self.order,
            product=self.product,
            price=Decimal("799.00"),
            quantity=1,
        )
        self._mark_item_delivered(order_item)
        files = MultiValueDict(
            {
                "photos": [
                    SimpleUploadedFile(f"image-{index}.jpg", b"fake-image", content_type="image/jpeg")
                    for index in range(5)
                ]
            }
        )

        form = ReturnRequestForm(
            data={"product": str(self.product.id), "reason": "defective", "description": "Needs return"},
            files=files,
            order=self.order,
        )

        self.assertTrue(form.is_valid(), form.errors)
        self.assertEqual(len(form.cleaned_data["photos"]), 5)

    def test_return_form_rejects_more_than_five_photos(self):
        order_item = OrderItem.objects.create(
            order=self.order,
            product=self.product,
            price=Decimal("799.00"),
            quantity=1,
        )
        self._mark_item_delivered(order_item)
        files = MultiValueDict(
            {
                "photos": [
                    SimpleUploadedFile(f"image-{index}.jpg", b"fake-image", content_type="image/jpeg")
                    for index in range(6)
                ]
            }
        )

        form = ReturnRequestForm(
            data={"product": str(self.product.id), "reason": "defective", "description": "Needs return"},
            files=files,
            order=self.order,
        )

        self.assertFalse(form.is_valid())
        self.assertIn("photos", form.errors)

    def test_review_form_accepts_up_to_five_images(self):
        files = MultiValueDict(
            {
                "images": [
                    SimpleUploadedFile(f"review-{index}.jpg", b"fake-image", content_type="image/jpeg")
                    for index in range(5)
                ]
            }
        )

        form = ReviewForm(
            data={"rating": "5", "comment": "Great product"},
            files=files,
            user=self.user,
            product=self.product,
        )

        self.assertTrue(form.is_valid(), form.errors)
        self.assertEqual(len(form.cleaned_data["images"]), 5)

    def test_review_form_image_widget_supports_multiple_selection(self):
        form = ReviewForm(user=self.user, product=self.product)

        self.assertTrue(form.fields["images"].widget.allow_multiple_selected)
        self.assertTrue(form.fields["images"].widget.attrs.get("multiple"))



    def test_cancel_paid_order_refunds_delivery_charge_when_entire_order_is_cancelled(self):

        order, _ = self._create_order(

            status=Order.STATUS_CONFIRMED,

            payment_method=Order.PAYMENT_ONLINE,

            paid=True,

            total_amount=Decimal("1080.00"),

            delivery_charge=Decimal("80.00"),

        )



        response = self.client.post(

            reverse("orders:cancel_order_api", args=[order.id]),

            {"reason": "Customer changed mind"},

            HTTP_ACCEPT="application/json",

            HTTP_X_REQUESTED_WITH="XMLHttpRequest",

        )



        self.assertEqual(response.status_code, 200)

        order.refresh_from_db()

        wallet = Wallet.objects.get(user=self.user)



        self.assertEqual(order.status, Order.STATUS_CANCELLED)

        self.assertEqual(wallet.balance, Decimal("1080.00"))



    def test_cancel_single_item_refunds_only_item_net_amount_without_delivery_charge(self):

        order = Order.objects.create(

            user=self.user,

            full_name="Buyer One",

            email="buyer@example.com",

            address="123 Street",

            paid=True,

            payment_method=Order.PAYMENT_ONLINE,

            total_amount=Decimal("560.00"),

            discount_amount=Decimal("40.00"),

            delivery_charge=Decimal("60.00"),

            status=Order.STATUS_CONFIRMED,

        )

        item_one = OrderItem.objects.create(

            order=order,

            product=self.product,

            price=Decimal("300.00"),

            quantity=1,

        )

        OrderItem.objects.create(

            order=order,

            product=self.second_product,

            price=Decimal("300.00"),

            quantity=1,

        )



        response = self.client.post(

            reverse("orders:cancel_order_item", args=[item_one.id]),

            {"reason": "Changed mind"},

            HTTP_ACCEPT="application/json",

            HTTP_X_REQUESTED_WITH="XMLHttpRequest",

        )



        self.assertEqual(response.status_code, 200)

        order.refresh_from_db()

        item_one.refresh_from_db()

        self.product.refresh_from_db()

        wallet = Wallet.objects.get(user=self.user)



        self.assertEqual(item_one.status, OrderItem.STATUS_CANCELLED)

        self.assertEqual(order.status, Order.STATUS_PARTIALLY_CANCELLED)

        self.assertEqual(wallet.balance, Decimal("280.00"))

        self.assertEqual(order.total_amount, Decimal("280.00"))

        self.assertEqual(self.product.stock, 4)

    def test_cancel_wallet_paid_item_refunds_full_line_amount_to_wallet(self):

        order = Order.objects.create(

            user=self.user,

            full_name="Buyer One",

            email="buyer@example.com",

            address="123 Street",

            paid=True,

            payment_method=Order.PAYMENT_WALLET,

            wallet_amount_used=Decimal("100.00"),

            total_amount=Decimal("100.00"),

            status=Order.STATUS_CONFIRMED,

        )

        item_one = OrderItem.objects.create(

            order=order,

            product=self.product,

            price=Decimal("100.00"),

            quantity=1,

        )

        Wallet.objects.create(user=self.user, balance=Decimal("0.00"))

        response = self.client.post(

            reverse("orders:cancel_order_item", args=[item_one.id]),

            {"reason": "Changed mind"},

            HTTP_ACCEPT="application/json",

            HTTP_X_REQUESTED_WITH="XMLHttpRequest",

        )

        self.assertEqual(response.status_code, 200)

        wallet = Wallet.objects.get(user=self.user)

        self.assertEqual(wallet.balance, Decimal("100.00"))

    def test_cancel_partial_quantity_creates_cancelled_split_and_refunds_selected_quantity(self):

        order = Order.objects.create(

            user=self.user,

            full_name="Buyer One",

            email="buyer@example.com",

            address="123 Street",

            paid=True,

            payment_method=Order.PAYMENT_ONLINE,

            total_amount=Decimal("300.00"),

            status=Order.STATUS_CONFIRMED,

        )

        item_one = OrderItem.objects.create(

            order=order,

            product=self.product,

            price=Decimal("100.00"),

            quantity=3,

        )

        response = self.client.post(

            reverse("orders:cancel_order_item", args=[item_one.id]),

            {"reason": "Changed mind", "cancel_quantity": "2"},

            HTTP_ACCEPT="application/json",

            HTTP_X_REQUESTED_WITH="XMLHttpRequest",

        )

        self.assertEqual(response.status_code, 200)

        wallet = Wallet.objects.get(user=self.user)

        item_one.refresh_from_db()

        self.assertEqual(wallet.balance, Decimal("200.00"))

        self.assertEqual(item_one.quantity, 1)

        self.assertEqual(

            OrderItem.objects.filter(order=order, product=self.product, status=OrderItem.STATUS_CANCELLED).count(),

            1,

        )



    def test_cancel_order_rejected_when_order_is_shipped(self):

        order, _ = self._create_order(status=Order.STATUS_SHIPPED, payment_method=Order.PAYMENT_ONLINE, paid=True)



        response = self.client.post(

            reverse("orders:cancel_order_api", args=[order.id]),

            {"reason": "Too late"},

            HTTP_ACCEPT="application/json",

            HTTP_X_REQUESTED_WITH="XMLHttpRequest",

        )



        self.assertEqual(response.status_code, 409)

        order.refresh_from_db()

        self.product.refresh_from_db()

        self.assertEqual(order.status, Order.STATUS_SHIPPED)

        self.assertEqual(self.product.stock, 3)

        self.assertFalse(Wallet.objects.filter(user=self.user).exists())



    def test_cancel_invalid_order_returns_404(self):

        response = self.client.post(

            reverse("orders:cancel_order_api", args=[999999]),

            {"reason": "Invalid"},

            HTTP_ACCEPT="application/json",

            HTTP_X_REQUESTED_WITH="XMLHttpRequest",

        )



        self.assertEqual(response.status_code, 404)





class OrderNotificationTests(TestCase):

    def setUp(self):

        self.user = get_user_model().objects.create_user(

            username="notifybuyer",

            email="notifybuyer@example.com",

            password="testpass123",

        )

        self.category = Category.objects.create(name="Books", slug="books")

        self.product = Product.objects.create(

            category=self.category,

            name="Novel",

            slug="novel",

            price=Decimal("750.00"),

            stock=10,

            available=True,

        )

        self.order = Order.objects.create(

            user=self.user,

            full_name="Notify Buyer",

            email=self.user.email,

            address="123 Street",

            paid=True,

            payment_method=Order.PAYMENT_ONLINE,

            total_amount=Decimal("750.00"),

            status=Order.STATUS_PLACED,

        )

        OrderItem.objects.create(

            order=self.order,

            product=self.product,

            price=Decimal("750.00"),

            quantity=1,

        )



    def test_status_change_to_shipped_sends_customer_notification(self):

        mail.outbox = []



        self.order.status = Order.STATUS_SHIPPED

        self.order.save(update_fields=["status", "updated_at"])



        self.assertEqual(len(mail.outbox), 1)

        self.assertIn("shipped", mail.outbox[0].subject.lower())

        self.assertEqual(mail.outbox[0].from_email, "no-reply@mykartstore.com")

        self.assertIn(f"Order ID: {self.order.id}", mail.outbox[0].body)



    def test_refund_notification_includes_amount(self):

        mail.outbox = []

        self.order.status = Order.STATUS_REFUNDED



        handle_order_status_change(self.order)



        self.assertEqual(len(mail.outbox), 1)

        self.assertIn("refund processed", mail.outbox[0].subject.lower())

        self.assertIn("Amount: Rs.750.00", mail.outbox[0].body)



    def test_delivery_sync_to_delivered_sends_customer_notification(self):

        mail.outbox = []

        assignment = DeliveryAssignment.objects.create(

            order=self.order,

            status=DeliveryAssignment.STATUS_ASSIGNED,

            cod_payment_status=DeliveryAssignment.COD_NOT_APPLICABLE,

        )



        assignment.status = DeliveryAssignment.STATUS_DELIVERED

        assignment.save(update_fields=["status", "updated_at"])



        with self.captureOnCommitCallbacks(execute=True):

            _sync_order_status_from_delivery(self.order, assignment, send_notification=True)



        self.order.refresh_from_db()

        self.assertEqual(self.order.status, Order.STATUS_DELIVERED)

        self.assertEqual(len(mail.outbox), 1)

        self.assertIn("delivered", mail.outbox[0].subject.lower())





class WalletCheckoutTests(TestCase):

    def setUp(self):

        self.client = Client()

        self.user = get_user_model().objects.create_user(

            username="walletbuyer",

            email="walletbuyer@example.com",

            password="testpass123",

        )

        self.client.force_login(self.user)

        self.category = Category.objects.create(name="Wallet Category", slug="wallet-category")

        self.product = Product.objects.create(

            category=self.category,

            name="Wallet Product",

            slug="wallet-product",

            price=Decimal("100.00"),

            stock=10,

            available=True,

        )



    def _prepare_cart(self, quantity=1):

        cart = Cart.objects.create()

        CartItem.objects.create(cart=cart, product=self.product, quantity=quantity)

        session = self.client.session

        session["cart_id"] = cart.id

        session.save()

        return cart



    def test_payment_step_switches_partial_wallet_checkout_to_online(self):

        self._prepare_cart()

        Wallet.objects.create(user=self.user, balance=Decimal("30.00"))



        response = self.client.post(

            reverse("orders:payment_step"),

            {

                "payment_method": Order.PAYMENT_WALLET,

            },

        )



        self.assertRedirects(response, reverse("orders:payment_online"), fetch_redirect_response=False)

        session = self.client.session

        self.assertEqual(session["checkout_payment_method"], Order.PAYMENT_ONLINE)

        self.assertTrue(session["checkout_use_wallet"])



        def test_payment_step_disables_wallet_option_when_balance_is_zero(self):

        self._prepare_cart()

        Wallet.objects.create(user=self.user, balance=Decimal("0.00"))



        response = self.client.get(reverse("orders:payment_step"))



        self.assertContains(response, 'value="wallet"')

        self.assertContains(response, "disabled") 

        self.assertContains(response, "Wallet payment is unavailable because your wallet amount is Rs.0.00.")



        submit_response = self.client.post(

            reverse("orders:payment_step"),

            {

                "payment_method": Order.PAYMENT_WALLET,

            },

        )



        self.assertRedirects(submit_response, reverse("orders:payment_online"), fetch_redirect_response=False)

        session = self.client.session

        self.assertEqual(session["checkout_payment_method"], Order.PAYMENT_ONLINE)

        self.assertFalse(session["checkout_use_wallet"])


    
    def test_order_create_with_full_wallet_marks_order_paid_and_debits_wallet(self):

        self._prepare_cart()

        Wallet.objects.create(user=self.user, balance=Decimal("150.00"))

        session = self.client.session

        session["checkout_use_wallet"] = True

        session["checkout_payment_method"] = Order.PAYMENT_ONLINE

        session.save()



        response = self.client.post(

            reverse("orders:order_create"),

            {

                "full_name": "Wallet Buyer",

                "email": self.user.email,

                "phone_number": "9999999999",

                "address": "123 Wallet Street",

            },

        )



        order = Order.objects.latest("id")

        self.assertRedirects(response, reverse("orders:order_confirmation", args=[order.id]))

        self.assertEqual(order.payment_method, Order.PAYMENT_WALLET)

        self.assertTrue(order.paid)

        self.assertEqual(order.wallet_amount_used, Decimal("100.00"))

        self.assertEqual(order.gateway_amount_paid, Decimal("0.00"))

        self.user.wallet.refresh_from_db()

        self.assertEqual(self.user.wallet.balance, Decimal("50.00"))

        self.assertTrue(WalletTransaction.objects.filter(order=order, transaction_type=WalletTransaction.TYPE_DEBIT).exists())

        self.assertTrue(PaymentTransaction.objects.filter(order=order, gateway=PaymentTransaction.GATEWAY_WALLET).exists())



    def test_order_create_with_wallet_and_online_records_split_payment(self):

        self._prepare_cart()

        Wallet.objects.create(user=self.user, balance=Decimal("30.00"))

        payment_txn = PaymentTransaction.objects.create(

            order=None,

            user=self.user,

            payment_method=Order.PAYMENT_ONLINE,

            gateway=PaymentTransaction.GATEWAY_RAZORPAY,

            status=PaymentTransaction.STATUS_SUCCESS,

            amount=Decimal("70.00"),

            gateway_order_id="order_test",

            gateway_payment_id="pay_test",

            gateway_signature="sig_test",

            raw_response={"source": "test", "result": "success"},

        )

        session = self.client.session

        session["checkout_use_wallet"] = True

        session["checkout_payment_method"] = Order.PAYMENT_ONLINE

        session["online_payment_confirmed"] = True

        session["razorpay_transaction_id"] = payment_txn.id

        session["razorpay_order_id"] = "order_test"

        session["razorpay_payment_id"] = "pay_test"

        session["razorpay_signature"] = "sig_test"

        session.save()



        response = self.client.post(

            reverse("orders:order_create"),

            {

                "full_name": "Wallet Buyer",

                "email": self.user.email,

                "phone_number": "9999999999",

                "address": "123 Wallet Street",

            },

        )



        order = Order.objects.latest("id")

        self.assertRedirects(response, reverse("orders:order_confirmation", args=[order.id]))

        self.assertEqual(order.payment_method, Order.PAYMENT_ONLINE)

        self.assertTrue(order.paid)

        self.assertEqual(order.wallet_amount_used, Decimal("30.00"))

        self.assertEqual(order.gateway_amount_paid, Decimal("70.00"))

        self.user.wallet.refresh_from_db()

        self.assertEqual(self.user.wallet.balance, Decimal("0.00"))

        payment_txn.refresh_from_db()

        self.assertEqual(payment_txn.order, order)

        self.assertEqual(payment_txn.amount, Decimal("70.00"))

        self.assertTrue(WalletTransaction.objects.filter(order=order, transaction_type=WalletTransaction.TYPE_DEBIT).exists())

        



class RazorpayCheckoutInitializationTests(TestCase):

    def setUp(self):

        self.client = Client()

        self.user = get_user_model().objects.create_user(

            username="checkoutbuyer",

            email="checkoutbuyer@example.com",

            password="testpass123",

        )

        self.client.force_login(self.user)

        self.category = Category.objects.create(name="Checkout Category", slug="checkout-category")

        self.product = Product.objects.create(

            category=self.category,

            name="Checkout Product",

            slug="checkout-product",

            price=Decimal("100.00"),

            stock=10,

            available=True,

        )

        cart = Cart.objects.create()

        CartItem.objects.create(cart=cart, product=self.product, quantity=1)

        session = self.client.session

        session["cart_id"] = cart.id

        session["checkout_payment_method"] = Order.PAYMENT_ONLINE

        session.save()



    @patch("orders.views._validate_razorpay_checkout")

    @patch("orders.views._get_razorpay_client")

    def test_payment_online_creates_backend_order_and_stores_same_session_order_id(self, get_client, validate_checkout):

        get_client.return_value.order.create.return_value = {"id": "order_created_123"}



        response = self.client.get(reverse("orders:payment_online"))



        self.assertEqual(response.status_code, 200)

        get_client.return_value.order.create.assert_called_once_with(

            {

                "amount": 10000,

                "currency": "INR",

                "payment_capture": 1,

            }

        )

        self.assertEqual(response.context["amount"], 10000)

        self.assertEqual(response.context["razorpay_order_id"], "order_created_123")

        session = self.client.session

        self.assertEqual(session["razorpay_order_id"], "order_created_123")

        self.assertEqual(session["razorpay_amount_paise"], 10000)

        self.assertFalse(session["online_payment_confirmed"])

        validate_checkout.assert_called_once()





class CheckoutPrefillTests(TestCase):

    def setUp(self):

        self.client = Client()

        self.user = get_user_model().objects.create_user(

            username="prefillbuyer",

            email="prefillbuyer@example.com",

            password="testpass123",

            first_name="Prefill",

            last_name="Buyer",

        )

        self.client.force_login(self.user)

        self.category = Category.objects.create(name="Prefill Category", slug="prefill-category")

        self.product = Product.objects.create(

            category=self.category,

            name="Prefill Product",

            slug="prefill-product",

            price=Decimal("250.00"),

            stock=5,

            available=True,

        )



    def test_order_create_prefills_saved_checkout_details(self):

        cart = Cart.objects.create()

        CartItem.objects.create(cart=cart, product=self.product, quantity=1)

        session = self.client.session

        session["cart_id"] = cart.id

        session.save()



        Order.objects.create(

            user=self.user,

            full_name="Saved Buyer",

            email="savedbuyer@example.com",

            address="42 Market Road, Chennai",

            payment_method=Order.PAYMENT_ONLINE,

            total_amount=Decimal("250.00"),

            status=Order.STATUS_PLACED,

        )



        response = self.client.get(reverse("orders:order_create"))



        self.assertEqual(response.status_code, 200)

        form = response.context["form"]

        self.assertEqual(form["full_name"].value(), "Saved Buyer")

        self.assertEqual(form["email"].value(), "savedbuyer@example.com")

        self.assertEqual(form["address"].value(), "42 Market Road, Chennai")

    def test_order_create_prefills_default_saved_address_before_latest_order_address(self):

        cart = Cart.objects.create()

        CartItem.objects.create(cart=cart, product=self.product, quantity=1)

        session = self.client.session

        session["cart_id"] = cart.id

        session.save()

        Address.objects.create(

            user=self.user,

            label="Home",

            address_line="9 Default Street",

            city="Coimbatore",

            state="Tamil Nadu",

            country="India",

            pincode="641001",

            is_default=True,

        )

        Order.objects.create(

            user=self.user,

            full_name="Saved Buyer",

            email="savedbuyer@example.com",

            address="42 Market Road, Chennai",

            city="Chennai",

            state="Tamil Nadu",

            pincode="600001",

            country="India",

            payment_method=Order.PAYMENT_ONLINE,

            total_amount=Decimal("250.00"),

            status=Order.STATUS_PLACED,

        )

        response = self.client.get(reverse("orders:order_create"))

        self.assertEqual(response.status_code, 200)

        form = response.context["form"]

        self.assertEqual(form["address"].value(), "9 Default Street")

        self.assertEqual(form["city"].value(), "Coimbatore")

        self.assertEqual(form["pincode"].value(), "641001")





class InvoiceViewTests(TestCase):

    def setUp(self):

        self.client = Client()

        self.user = get_user_model().objects.create_user(

            username="invoicebuyer",

            email="invoicebuyer@example.com",

            password="testpass123",

        )

        self.client.force_login(self.user)

        self.category = Category.objects.create(

            name="Invoice Category",

            slug="invoice-category",

            gst_rate=Decimal("12.00"),

            hsn_code="6109",

        )

        self.product = Product.objects.create(

            category=self.category,

            name="Premium Tee",

            slug="premium-tee",

            price=Decimal("50.00"),

            gst_rate=Decimal("12.00"),

            hsn_code="6109",

            stock=10,

            available=True,

            status=Product.STATUS_APPROVED,

        )

        self.order = Order.objects.create(

            user=self.user,

            full_name="Invoice Buyer",

            email="invoicebuyer@example.com",

            phone_number="9999999999",

            address="12 Market Street",

            city="Chennai",

            state="Tamil Nadu",

            pincode="600001",

            country="India",

            paid=True,

            payment_method=Order.PAYMENT_ONLINE,

            gateway_amount_paid=Decimal("50.00"),

            total_amount=Decimal("50.00"),

            status=Order.STATUS_PAID,

        )

        OrderItem.objects.create(

            order=self.order,

            product=self.product,

            price=Decimal("50.00"),

            gst_rate=Decimal("12.00"),

            gst_amount=Decimal("5.36"),

            quantity=1,

        )

        PaymentTransaction.objects.create(

            order=self.order,

            user=self.user,

            payment_method=Order.PAYMENT_ONLINE,

            gateway=PaymentTransaction.GATEWAY_RAZORPAY,

            status=PaymentTransaction.STATUS_SUCCESS,

            amount=Decimal("50.00"),

            gateway_order_id="order_invoice_test_123",

            gateway_payment_id="pay_invoice_test_123",

        )

    def test_invoice_uses_tax_inclusive_total_without_adding_gst_twice(self):

        response = self.client.get(reverse("orders:order_invoice", args=[self.order.id]))

        self.assertEqual(response.status_code, 200)

        self.assertEqual(response.context["grand_total"], Decimal("50.00"))

        self.assertEqual(response.context["items_total"], Decimal("50.00"))

        self.assertEqual(response.context["subtotal"], Decimal("44.00"))

        self.assertEqual(response.context["gst_amount"], Decimal("6.00"))

        self.assertEqual(response.context["payment_transaction_id"], "pay_invoice_test_123")

        self.assertEqual(response.context["invoice_line_items"][0]["line_gst"], Decimal("6.00"))

        self.assertEqual(response.context["invoice_line_items"][0]["line_taxable"], Decimal("44.00"))

        self.assertEqual(response.context["gst_rate_labels"], ["12%"])

    def test_invoice_template_hides_city_label_and_shows_payment_reference(self):

        response = self.client.get(reverse("orders:order_invoice", args=[self.order.id]))

        self.assertContains(response, "TAX-INV-")

        self.assertContains(response, "pay_invoice_test_123")

        self.assertContains(response, "GST total (12%)")

        self.assertNotContains(response, "City")

    def test_invoice_number_is_distinct_from_order_id(self):

        response = self.client.get(reverse("orders:order_invoice", args=[self.order.id]))

        self.assertNotEqual(response.context["invoice_number"], self.order.display_order_id)

    @patch("weasyprint.HTML")
    def test_invoice_pdf_download_returns_attachment_response(self, html_class):

        html_instance = html_class.return_value
        html_instance.write_pdf.return_value = b"%PDF-test"

        response = self.client.get(reverse("orders:order_invoice_pdf", args=[self.order.id]))

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response["Content-Type"], "application/pdf")
        self.assertIn("attachment;", response["Content-Disposition"])
        self.assertIn("TAX-INV-", response["Content-Disposition"])
        html_class.assert_called_once()

    def test_invoice_pdf_download_falls_back_to_html_when_weasyprint_is_missing(self):

        import builtins

        real_import = builtins.__import__

        def fake_import(name, globals=None, locals=None, fromlist=(), level=0):
            if name == "weasyprint":
                raise ModuleNotFoundError("No module named 'weasyprint'")
            return real_import(name, globals, locals, fromlist, level)

        with patch("builtins.__import__", side_effect=fake_import):
            response = self.client.get(reverse("orders:order_invoice_pdf", args=[self.order.id]))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "print-safe invoice view")


class RazorpayPaymentCallbackTests(TestCase):

    def setUp(self):

        self.client = Client()

        self.user = get_user_model().objects.create_user(

            username="razorpaybuyer",

            email="razorpaybuyer@example.com",

            password="testpass123",

        )

        self.client.force_login(self.user)



    def _prime_payment_session(self):

        session = self.client.session

        session["razorpay_order_id"] = "order_test_123"

        session["razorpay_amount_paise"] = 7000

        session["razorpay_amount"] = "70.00"

        session.save()



    @patch("orders.views._get_razorpay_client")

    def test_payment_success_verifies_signature_and_sets_checkout_session(self, get_client):

        self._prime_payment_session()

        verify_signature = get_client.return_value.utility.verify_payment_signature



        response = self.client.post(

            reverse("orders:payment_success"),

            data=json.dumps(

                {

                    "status": "success",

                    "razorpay_payment_id": "pay_test_123",

                    "razorpay_order_id": "order_test_123",

                    "razorpay_signature": "sig_test_123",

                    "amount": "7000",

                }

            ),

            content_type="application/json",

        )



        self.assertEqual(response.status_code, 200)

        verify_signature.assert_called_once_with(

            {

                "razorpay_payment_id": "pay_test_123",

                "razorpay_order_id": "order_test_123",

                "razorpay_signature": "sig_test_123",

            }

        )

        txn = PaymentTransaction.objects.get(gateway_payment_id="pay_test_123")

        self.assertEqual(txn.status, PaymentTransaction.STATUS_SUCCESS)

        self.assertEqual(txn.amount, Decimal("70.00"))

        session = self.client.session

        self.assertTrue(session["online_payment_confirmed"])

        self.assertEqual(session["razorpay_transaction_id"], txn.id)



    @patch("orders.views._get_razorpay_client")

    def test_payment_success_with_bad_signature_records_failed_attempt(self, get_client):

        self._prime_payment_session()

        get_client.return_value.utility.verify_payment_signature.side_effect = razorpay.errors.SignatureVerificationError("invalid")



        response = self.client.post(

            reverse("orders:payment_success"),

            data=json.dumps(

                {

                    "status": "success",

                    "razorpay_payment_id": "pay_test_bad",

                    "razorpay_order_id": "order_test_123",

                    "razorpay_signature": "sig_bad",

                    "amount": "7000",

                }

            ),

            content_type="application/json",

        )



        self.assertEqual(response.status_code, 400)

        get_client.return_value.utility.verify_payment_signature.assert_called_once()

        txn = PaymentTransaction.objects.get(gateway_payment_id="pay_test_bad")

        self.assertEqual(txn.status, PaymentTransaction.STATUS_FAILED)

        self.assertIn("Signature verification failed", txn.failure_reason)

        self.assertFalse(self.client.session.get("online_payment_confirmed", False))



    def test_payment_failure_callback_records_failed_attempt(self):

        self._prime_payment_session()



        response = self.client.post(

            reverse("orders:payment_success"),

            data=json.dumps(

                {

                    "status": "failed",

                    "razorpay_order_id": "order_test_123",

                    "failure_reason": "UPI collect request timed out.",

                    "error_description": "The collect request expired before approval.",

                    "error_step": "payment_authentication",

                }

            ),

            content_type="application/json",

        )



        self.assertEqual(response.status_code, 200)

        txn = PaymentTransaction.objects.latest("id")

        self.assertEqual(txn.status, PaymentTransaction.STATUS_FAILED)

        self.assertEqual(txn.gateway_order_id, "order_test_123")

        self.assertEqual(txn.amount, Decimal("70.00"))

        self.assertIn("UPI collect request timed out", txn.failure_reason)

        self.assertFalse(self.client.session.get("online_payment_confirmed", False))



    @patch("orders.views._get_razorpay_client")

    def test_payment_status_marks_success_from_provider_poll(self, get_client):

        self._prime_payment_session()

        get_client.return_value.order.payments.return_value = {

            "items": [

                {

                    "id": "pay_polled_123",

                    "amount": 7000,

                    "status": "captured",

                    "method": "upi",

                }

            ]

        }



        response = self.client.get(

            reverse("orders:payment_status"),

            HTTP_X_REQUESTED_WITH="XMLHttpRequest",

        )



        self.assertEqual(response.status_code, 200)

        self.assertJSONEqual(response.content, {"status": "success"})

        txn = PaymentTransaction.objects.get(gateway_payment_id="pay_polled_123")

        self.assertEqual(txn.status, PaymentTransaction.STATUS_SUCCESS)

        self.assertEqual(txn.amount, Decimal("70.00"))

        self.assertTrue(self.client.session["online_payment_confirmed"])



    @patch("orders.views._get_razorpay_client")

    def test_payment_status_returns_pending_when_provider_has_no_terminal_state(self, get_client):

        self._prime_payment_session()

        get_client.return_value.order.payments.return_value = {

            "items": [

                {

                    "id": "pay_pending_123",

                    "amount": 7000,

                    "status": "created",

                    "method": "upi",

                }

            ]

        }



        response = self.client.get(

            reverse("orders:payment_status"),

            HTTP_X_REQUESTED_WITH="XMLHttpRequest",

        )



        self.assertEqual(response.status_code, 200)

        self.assertJSONEqual(response.content, {"status": "pending"})



    def test_payment_success_rejects_order_id_mismatch(self):

        self._prime_payment_session()



        response = self.client.post(

            reverse("orders:payment_success"),

            data=json.dumps(

                {

                    "status": "success",

                    "razorpay_payment_id": "pay_test_bad_order",

                    "razorpay_order_id": "order_other_456",

                    "razorpay_signature": "sig_bad_order",

                    "amount": 7000,

                }

            ),

            content_type="application/json",

        )



        self.assertEqual(response.status_code, 400)

        self.assertJSONEqual(response.content, {"status": "error", "message": "Order ID mismatch."})





class RazorpayApiIntegrationTests(TestCase):

    def setUp(self):

        self.client = Client()

        self.user = get_user_model().objects.create_user(

            username="api-buyer",

            email="api-buyer@example.com",

            password="testpass123",

        )

        self.client.force_login(self.user)

        self.category = Category.objects.create(name="API Category", slug="api-category")

        self.product = Product.objects.create(

            category=self.category,

            name="API Product",

            slug="api-product",

            price=Decimal("499.00"),

            stock=10,

            available=True,

            status=Product.STATUS_APPROVED,

        )



    def _prepare_cart(self, *, quantity=1):

        cart = Cart.objects.create()

        CartItem.objects.create(cart=cart, product=self.product, quantity=quantity)

        session = self.client.session

        session["cart_id"] = cart.id

        session["checkout_payment_method"] = Order.PAYMENT_ONLINE

        session["checkout_use_wallet"] = False

        session.save()

        return cart



    @patch("orders.payment_views._create_remote_order")

    def test_create_order_returns_razorpay_order_id(self, create_remote_order):

        self._prepare_cart()

        create_remote_order.return_value = {"id": "order_test_abc123"}



        response = self.client.post(

            reverse("create_order"),

            data=json.dumps({"source": "checkout"}),

            content_type="application/json",

        )



        self.assertEqual(response.status_code, 201)

        payload = response.json()

        self.assertTrue(payload["success"])

        self.assertEqual(payload["order_id"], "order_test_abc123")

        self.assertEqual(payload["amount"], 49900)

        self.assertEqual(payload["currency"], settings.RAZORPAY_CURRENCY)

        self.assertEqual(payload["key"], settings.RAZORPAY_KEY_ID)



        txn = PaymentTransaction.objects.latest("id")

        self.assertEqual(payload["transaction_id"], txn.id)

        self.assertEqual(txn.status, PaymentTransaction.STATUS_INITIATED)

        self.assertEqual(txn.amount, Decimal("499.00"))

        self.assertEqual(txn.gateway_order_id, "order_test_abc123")



    def test_create_order_uses_total_for_multiple_products(self):

        self._prepare_cart(quantity=3)



        with patch("orders.payment_views._create_remote_order", return_value={"id": "order_multi_total"}) as create_remote_order:

            response = self.client.post(

                reverse("create_order"),

                data=json.dumps({"source": "checkout"}),

                content_type="application/json",

            )



        self.assertEqual(response.status_code, 201)

        payload = response.json()

        self.assertEqual(payload["amount"], 149700)

        create_remote_order.assert_called_once()

        self.assertEqual(PaymentTransaction.objects.latest("id").amount, Decimal("1497.00"))



    def test_create_order_uses_remaining_amount_when_wallet_is_low(self):

        self._prepare_cart()

        Wallet.objects.create(user=self.user, balance=Decimal("200.00"))

        session = self.client.session

        session["checkout_use_wallet"] = True

        session["checkout_payment_method"] = Order.PAYMENT_ONLINE

        session.save()



        with patch("orders.payment_views._create_remote_order", return_value={"id": "order_wallet_split"}) as create_remote_order:

            response = self.client.post(

                reverse("create_order"),

                data=json.dumps({"source": "checkout"}),

                content_type="application/json",

            )



        self.assertEqual(response.status_code, 201)

        payload = response.json()

        self.assertEqual(payload["amount"], 29900)

        create_remote_order.assert_called_once()

        self.assertEqual(PaymentTransaction.objects.latest("id").amount, Decimal("299.00"))



    def test_create_order_rejects_when_cart_is_empty(self):

        response = self.client.post(

            reverse("create_order"),

            data=json.dumps({"source": "checkout"}),

            content_type="application/json",

        )



        self.assertEqual(response.status_code, 400)

        self.assertJSONEqual(response.content, {"success": False, "message": "Your cart is empty."})



    def test_verify_payment_marks_transaction_success(self):

        txn = PaymentTransaction.objects.create(

            order=None,

            user=self.user,

            payment_method=Order.PAYMENT_ONLINE,

            gateway=PaymentTransaction.GATEWAY_RAZORPAY,

            status=PaymentTransaction.STATUS_INITIATED,

            amount=Decimal("499.00"),

            currency="INR",

            gateway_order_id="order_test_verify",

        )

        session = self.client.session

        session["razorpay_transaction_id"] = txn.id

        session.save()



        generated_signature = hmac.new(

            settings.RAZORPAY_KEY_SECRET.encode("utf-8"),

            b"order_test_verify|pay_test_verify",

            hashlib.sha256,

        ).hexdigest()



        response = self.client.post(

            reverse("verify_payment"),

            data=json.dumps(

                {

                    "razorpay_order_id": "order_test_verify",

                    "razorpay_payment_id": "pay_test_verify",

                    "razorpay_signature": generated_signature,

                }

            ),

            content_type="application/json",

        )



        self.assertEqual(response.status_code, 200)

        self.assertJSONEqual(

            response.content,

            {

                "success": True,

                "message": "Payment verified successfully.",

                "transaction_id": txn.id,

                "redirect_url": reverse("orders:order_create"),

            },

        )

        txn.refresh_from_db()

        self.assertEqual(txn.status, PaymentTransaction.STATUS_SUCCESS)

        self.assertEqual(txn.gateway_payment_id, "pay_test_verify")



    def test_verify_payment_rejects_bad_signature(self):

        txn = PaymentTransaction.objects.create(

            order=None,

            user=self.user,

            payment_method=Order.PAYMENT_ONLINE,

            gateway=PaymentTransaction.GATEWAY_RAZORPAY,

            status=PaymentTransaction.STATUS_INITIATED,

            amount=Decimal("499.00"),

            currency="INR",

            gateway_order_id="order_test_bad_sig",

        )

        session = self.client.session

        session["razorpay_transaction_id"] = txn.id

        session.save()



        response = self.client.post(

            reverse("verify_payment"),

            data=json.dumps(

                {

                    "razorpay_order_id": "order_test_bad_sig",

                    "razorpay_payment_id": "pay_test_bad_sig",

                    "razorpay_signature": "bad_signature",

                }

            ),

            content_type="application/json",

        )



        self.assertEqual(response.status_code, 400)

        self.assertJSONEqual(response.content, {"success": False, "message": "Signature verification failed."})

        txn.refresh_from_db()

        self.assertEqual(txn.status, PaymentTransaction.STATUS_FAILED)
