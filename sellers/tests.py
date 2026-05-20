from decimal import Decimal

import os

import shutil

import tempfile



from django.conf import settings

from django.contrib.auth import get_user_model

from django.core import mail

from django.core.exceptions import ValidationError

from django.core.files.uploadedfile import SimpleUploadedFile

from django.test import TestCase, override_settings

from django.urls import reverse

from django.utils import timezone



from orders.models import Coupon, Order, OrderItem, ReturnRequest

from orders.utils.seller_emails import send_seller_email

from products.models import Category, Product, ProductImage



from .forms import SellerCouponForm, SellerProductEntryForm, SellerProductSharedSettingsForm, SellerProfileRegistrationForm

# from .models import Payout, SellerLedger, SellerOrderPayout, SellerProfile, SellerProduct
from .models import Payout, SellerLedger, SellerNotification, SellerOrderPayout, SellerPayout, SellerProfile, SellerProduct


from .services import LedgerService, MockRazorpayPayoutClient, PayoutCalculator, PayoutService, WalletService





User = get_user_model()





class FailedPayoutClient:

    def create_payout(self, *, seller, amount, payout):

        raise ValidationError("Gateway unavailable")









@override_settings(EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend")

class SellerEmailNotificationTests(TestCase):

    @classmethod

    def setUpTestData(cls):

        cls.category = Category.objects.create(name="Seller Email Category", slug="seller-email-category")

        cls.user = User.objects.create_user(

            username="selleremail",

            email="selleruser@example.com",

            password="testpass123",

        )

        cls.buyer = User.objects.create_user(

            username="buyeremail",

            email="buyeremail@example.com",

            password="testpass123",

        )



    def setUp(self):

        mail.outbox = []

        self.expected_seller_from = (

            settings.EMAIL_HOST_USER

            if settings.EMAIL_HOST_USER and settings.EMAIL_HOST_USER.lower() != "business@mykartstore.com"

            else "business@mykartstore.com"

        )



    def create_seller(self, **overrides):

        data = {

            "user": self.user,

            "business_name": "Acme Seller",

            "phone": "9999999999",

            "pan_card_number": "ABCDE1234F",

            "pan_card_photo": "seller_documents/pan.jpg",

            "supplier_details": "Supplier details",

            "registered_office_address": "Chennai",

            "contact_person_name": "Seller User",

            "contact_email": "seller@example.com",

            "payout_account_name": "Acme Seller",

            "payout_account_number": "1234567890",

            "payout_ifsc": "ABCD0123456",

            "terms_accepted": True,

        }

        data.update(overrides)

        return SellerProfile.objects.create(**data)



    def test_send_seller_email_uses_business_sender_and_support_reply_to(self):

        send_seller_email("Subject", "Body", "seller@example.com")



        self.assertEqual(len(mail.outbox), 1)

        self.assertEqual(mail.outbox[0].from_email, self.expected_seller_from)

        self.assertEqual(mail.outbox[0].reply_to, ["support@mykartstore.com"])

        self.assertEqual(mail.outbox[0].to, ["seller@example.com"])



    def test_seller_creation_sends_registration_notifications(self):

        with self.captureOnCommitCallbacks(execute=True):

            seller = self.create_seller(approval_status=SellerProfile.STATUS_PENDING)



        self.assertEqual(len(mail.outbox), 3)

        self.assertEqual(mail.outbox[0].subject, "New Seller Registration")

        self.assertIn(seller.business_name, mail.outbox[0].body)

        self.assertEqual(mail.outbox[1].subject, "Seller Registration Submitted")

        self.assertIn(seller.registration_id, mail.outbox[1].body)

        self.assertEqual(mail.outbox[1].to, ["seller@example.com"])

        self.assertEqual(mail.outbox[2].subject, "Seller Registration ID Generated")

        self.assertIn(seller.registration_id, mail.outbox[2].body)

        self.assertTrue(all(message.from_email == self.expected_seller_from for message in mail.outbox))



    def test_application_status_change_sends_business_notification(self):

        with self.captureOnCommitCallbacks(execute=True):

            seller = self.create_seller(approval_status=SellerProfile.STATUS_PENDING)

        mail.outbox = []



        with self.captureOnCommitCallbacks(execute=True):

            seller.approval_status = SellerProfile.STATUS_APPROVED

            seller.save(update_fields=["approval_status", "seller_id", "approved_at", "updated_at"])



        self.assertEqual(len(mail.outbox), 2)

        business_email = next(message for message in mail.outbox if message.to == ["business@mykartstore.com"])

        seller_email = next(message for message in mail.outbox if message.to == ["seller@example.com"])

        self.assertEqual(business_email.subject, "Seller Application Approved")

        self.assertIn("has been Approved", business_email.body)

        self.assertEqual(seller_email.subject, "Seller Application Approved")

        self.assertIn("your seller application has been Approved", seller_email.body)



    def test_new_order_alert_goes_to_seller_email(self):

        seller = self.create_seller(approval_status=SellerProfile.STATUS_APPROVED)

        product = Product.objects.create(

            category=self.category,

            name="Seller Watch",

            slug="seller-watch",

            description="Test product",

            price=Decimal("999.00"),

            stock=5,

            available=True,

            status=Product.STATUS_APPROVED,

        )

        SellerProduct.objects.create(

            seller=seller,

            product=product,

            delivery_mode=SellerProduct.HUB_DELIVERY,

            delivery_type=SellerProduct.DELIVERY_TYPE_PLATFORM,

            estimated_delivery_charge=Decimal("50.00"),

            hub_name="Main Hub",

            hub_address="Hub address",

        )

        order = Order.objects.create(

            user=self.buyer,

            full_name="Buyer",

            email="buyer@example.com",

            address="Bengaluru",

            paid=True,

            payment_method=Order.PAYMENT_ONLINE,

            delivery_charge=Decimal("50.00"),

        )

        mail.outbox = []



        with self.captureOnCommitCallbacks(execute=True):

            OrderItem.objects.create(order=order, product=product, price=Decimal("999.00"), quantity=1)



        self.assertTrue(any(message.subject == "New Order Received" for message in mail.outbox))

        seller_email = next(message for message in mail.outbox if message.subject == "New Order Received")

        self.assertEqual(seller_email.to, ["seller@example.com"])

        self.assertIn(str(order.id), seller_email.body)



    def test_pending_to_approved_product_sends_decision_email(self):

        seller = self.create_seller(approval_status=SellerProfile.STATUS_APPROVED)

        product = Product.objects.create(

            category=self.category,

            name="Approval Shoe",

            slug="approval-shoe",

            description="Test product",

            price=Decimal("999.00"),

            stock=5,

            available=False,

            status=Product.STATUS_PENDING,

        )

        SellerProduct.objects.create(

            seller=seller,

            product=product,

            delivery_mode=SellerProduct.OWN_DELIVERY,

            delivery_type=SellerProduct.DELIVERY_TYPE_OWN,

            shipping_details="Ships directly",

        )



        mail.outbox = []

        product.approve(save=True)



        self.assertEqual(len(mail.outbox), 1)

        self.assertEqual(mail.outbox[0].subject, "Product Approved")

        self.assertIn("Product name: Approval Shoe", mail.outbox[0].body)

        self.assertIn("Final status: Approved", mail.outbox[0].body)

        self.assertEqual(mail.outbox[0].to, ["seller@example.com"])



    def test_pending_to_rejected_product_sends_rejection_email_with_reason(self):

        seller = self.create_seller(approval_status=SellerProfile.STATUS_APPROVED)

        product = Product.objects.create(

            category=self.category,

            name="Rejected Shoe",

            slug="rejected-shoe",

            description="Test product",

            price=Decimal("999.00"),

            stock=5,

            available=False,

            status=Product.STATUS_PENDING,

        )

        SellerProduct.objects.create(

            seller=seller,

            product=product,

            delivery_mode=SellerProduct.OWN_DELIVERY,

            delivery_type=SellerProduct.DELIVERY_TYPE_OWN,

            shipping_details="Ships directly",

        )



        mail.outbox = []

        product.reject(reason="Missing compliance details", save=True)



        self.assertEqual(len(mail.outbox), 1)

        self.assertEqual(mail.outbox[0].subject, "Product Rejected")

        self.assertIn("Final status: Rejected", mail.outbox[0].body)

        self.assertIn("Rejection reason: Missing compliance details", mail.outbox[0].body)



    def test_non_decision_status_change_does_not_send_product_email(self):

        seller = self.create_seller(approval_status=SellerProfile.STATUS_APPROVED)

        product = Product.objects.create(

            category=self.category,

            name="No Email Shoe",

            slug="no-email-shoe",

            description="Test product",

            price=Decimal("999.00"),

            stock=5,

            available=False,

            status=Product.STATUS_PENDING,

        )

        SellerProduct.objects.create(

            seller=seller,

            product=product,

            delivery_mode=SellerProduct.OWN_DELIVERY,

            delivery_type=SellerProduct.DELIVERY_TYPE_OWN,

            shipping_details="Ships directly",

        )



        mail.outbox = []

        product.name = "No Email Shoe Updated"

        product.save(update_fields=["name", "updated"])



        self.assertEqual(mail.outbox, [])



class SellerPayoutFlowTests(TestCase):

    @classmethod

    def setUpTestData(cls):

        cls.user = User.objects.create_user(username="buyer", password="testpass123")

        cls.seller_user = User.objects.create_user(username="seller", password="testpass123")

        cls.category = Category.objects.create(name="Fashion", slug="fashion")

        cls.product = Product.objects.create(

            category=cls.category,

            name="Shirt",

            slug="shirt",

            description="Test product",

            price=Decimal("1000.00"),

            stock=10,

            available=True,

        )

        cls.seller = SellerProfile.objects.create(

            user=cls.seller_user,

            business_name="Acme Seller",

            phone="9999999999",

            pan_card_number="ABCDE1234F",

            pan_card_photo="seller_documents/pan.jpg",

            supplier_details="Supplier details",

            registered_office_address="Chennai",

            contact_person_name="Seller User",

            contact_email="seller@example.com",

            payout_account_name="Acme Seller",

            payout_account_number="1234567890",

            payout_ifsc="ABCD0123456",

            terms_accepted=True,

            approval_status=SellerProfile.STATUS_APPROVED,

        )

        cls.seller_product = SellerProduct.objects.create(

            seller=cls.seller,

            product=cls.product,

            delivery_mode=SellerProduct.HUB_DELIVERY,

            delivery_type=SellerProduct.DELIVERY_TYPE_PLATFORM,

            estimated_delivery_charge=Decimal("75.00"),

            hub_name="Main Hub",

            hub_address="Hub address",

        )



    def create_order(self, **overrides):

        data = {

            "user": self.user,

            "full_name": "Buyer",

            "email": "buyer@example.com",

            "address": "Bengaluru",

            "paid": True,

            "payment_method": Order.PAYMENT_ONLINE,

            "delivery_charge": Decimal("100.00"),

            "delivery_type": Order.DELIVERY_TYPE_PLATFORM,

        }

        data.update(overrides)

        return Order.objects.create(**data)



    def create_order_item(self, order, **overrides):

        data = {

            "order": order,

            "product": self.product,

            "price": Decimal("1000.00"),

            "quantity": 1,

        }

        data.update(overrides)

        return OrderItem.objects.create(**data)



    def test_platform_delivery_payout_restores_all_deductions(self):

        order = self.create_order(delivery_charge=Decimal("50.00"))

        order_item = self.create_order_item(order)



        breakdown = PayoutCalculator().calculate_for_order_item(order_item)



        self.assertEqual(breakdown.product_price, Decimal("1000.00"))

        self.assertEqual(breakdown.taxable_product_price, Decimal("1000.00"))

        self.assertEqual(breakdown.delivery_charge, Decimal("50.00"))

        self.assertEqual(breakdown.platform_commission, Decimal("100.00"))

        self.assertEqual(breakdown.payment_gateway_fee, Decimal("20.00"))

        self.assertEqual(breakdown.gst, Decimal("180.00"))

        self.assertEqual(breakdown.tds, Decimal("10.00"))

        self.assertEqual(breakdown.payout_amount, Decimal("640.00"))



    def test_discount_is_applied_per_product_before_gst(self):

        self.product.discount_percent = Decimal("20.00")

        self.product.discount_amount = Decimal("0.00")

        self.product.save(update_fields=["discount_percent", "discount_amount", "updated"])



        order = self.create_order(delivery_charge=Decimal("50.00"))

        order_item = self.create_order_item(order, price=Decimal("800.00"))



        breakdown = PayoutCalculator().calculate_for_order_item(order_item)



        self.assertEqual(breakdown.product_price, Decimal("1000.00"))

        self.assertEqual(breakdown.seller_discount, Decimal("200.00"))

        self.assertEqual(breakdown.taxable_product_price, Decimal("800.00"))

        self.assertEqual(breakdown.platform_commission, Decimal("80.00"))

        self.assertEqual(breakdown.payment_gateway_fee, Decimal("16.00"))

        self.assertEqual(breakdown.gst, Decimal("144.00"))

        self.assertEqual(breakdown.tds, Decimal("8.00"))

        self.assertEqual(breakdown.payout_amount, Decimal("502.00"))



    def test_coupon_discount_is_added_per_item_before_tax(self):

        order = self.create_order(delivery_charge=Decimal("100.00"), discount_amount=Decimal("100.00"))

        order_item = self.create_order_item(order, price=Decimal("800.00"))



        breakdown = PayoutCalculator().calculate_for_order_item(order_item)



        self.assertEqual(breakdown.product_discount, Decimal("200.00"))

        self.assertEqual(breakdown.coupon_discount, Decimal("100.00"))

        self.assertEqual(breakdown.seller_discount, Decimal("300.00"))

        self.assertEqual(breakdown.taxable_product_price, Decimal("700.00"))

        self.assertEqual(breakdown.platform_commission, Decimal("70.00"))

        self.assertEqual(breakdown.payment_gateway_fee, Decimal("14.00"))

        self.assertEqual(breakdown.gst, Decimal("126.00"))

        self.assertEqual(breakdown.tds, Decimal("7.00"))

        self.assertEqual(breakdown.delivery_charge, Decimal("50.00"))

        self.assertEqual(breakdown.payout_amount, Decimal("433.00"))



    def test_own_delivery_keeps_full_product_price(self):

        self.seller_product.delivery_mode = SellerProduct.OWN_DELIVERY

        self.seller_product.delivery_type = SellerProduct.DELIVERY_TYPE_OWN

        self.seller_product.estimated_delivery_charge = Decimal("0.00")

        self.seller_product.shipping_details = "Ships directly"

        self.seller_product.save()



        order = self.create_order(delivery_type=Order.DELIVERY_TYPE_OWN, delivery_charge=Decimal("0.00"))

        order_item = self.create_order_item(order)



        breakdown = PayoutCalculator().calculate_for_order_item(order_item)

        self.assertEqual(breakdown.delivery_charge, Decimal("0.00"))

        self.assertEqual(breakdown.payout_amount, Decimal("690.00"))



    def test_wallet_snapshot_uses_ledger_as_single_source_of_truth(self):

        order = self.create_order(delivery_charge=Decimal("50.00"))

        self.create_order_item(order)



        snapshot = WalletService.get_financial_snapshot(self.seller)



        self.assertEqual(snapshot["pending_payout"], Decimal("640.00"))

        self.assertEqual(snapshot["paid_payout"], Decimal("0.00"))

        self.assertEqual(snapshot["wallet_balance"], Decimal("640.00"))



    def test_cancelled_order_creates_reversal_and_zeroes_unsettled_balance(self):

        order = self.create_order(delivery_charge=Decimal("50.00"))

        self.create_order_item(order)



        order.status = Order.STATUS_CANCELLED

        order.order_status = Order.ORDER_STATUS_CANCELLED

        order.save()
        snapshot = WalletService.get_financial_snapshot(self.seller)



        self.assertEqual(snapshot["pending_payout"], Decimal("0.00"))

        self.assertTrue(SellerLedger.objects.filter(reference_id=f"cancel-order:{order.id}").exists())

    def test_update_own_delivery_status_redirects_back_to_active_payouts_panel(self):
        self.client.login(username="seller", password="testpass123")
        self.seller_product.delivery_mode = SellerProduct.OWN_DELIVERY
        self.seller_product.delivery_type = SellerProduct.DELIVERY_TYPE_OWN
        self.seller_product.estimated_delivery_charge = Decimal("0.00")
        self.seller_product.shipping_details = "Ships directly"
        self.seller_product.save()

        order = self.create_order(delivery_type=Order.DELIVERY_TYPE_OWN, delivery_charge=Decimal("0.00"))
        order_item = self.create_order_item(order)
        payout = SellerPayout.objects.get(order_item=order_item)

        response = self.client.post(
            reverse("sellers:update_own_delivery_status", args=[payout.id]),
            {
                "delivery_status": SellerPayout.DELIVERY_SHIPPED,
                "courier_number": "SHIP123",
            },
        )

        self.assertRedirects(response, reverse("sellers:dashboard") + "?panel=active-payouts")

    def test_marking_own_delivery_delivered_requires_proof_and_keeps_active_payouts_panel(self):
        self.client.login(username="seller", password="testpass123")
        self.seller_product.delivery_mode = SellerProduct.OWN_DELIVERY
        self.seller_product.delivery_type = SellerProduct.DELIVERY_TYPE_OWN
        self.seller_product.estimated_delivery_charge = Decimal("0.00")
        self.seller_product.shipping_details = "Ships directly"
        self.seller_product.save()

        order = self.create_order(delivery_type=Order.DELIVERY_TYPE_OWN, delivery_charge=Decimal("0.00"))
        order_item = self.create_order_item(order)
        payout = SellerPayout.objects.get(order_item=order_item)

        response = self.client.post(
            reverse("sellers:update_own_delivery_status", args=[payout.id]),
            {
                "delivery_status": SellerPayout.DELIVERY_DELIVERED,
            },
        )

        self.assertRedirects(response, reverse("sellers:dashboard") + "?panel=active-payouts")

    def test_update_own_delivery_status_redirects_back_to_completed_orders_panel_when_requested(self):
        self.client.login(username="seller", password="testpass123")
        self.seller_product.delivery_mode = SellerProduct.OWN_DELIVERY
        self.seller_product.delivery_type = SellerProduct.DELIVERY_TYPE_OWN
        self.seller_product.estimated_delivery_charge = Decimal("0.00")
        self.seller_product.shipping_details = "Ships directly"
        self.seller_product.save()

        order = self.create_order(delivery_type=Order.DELIVERY_TYPE_OWN, delivery_charge=Decimal("0.00"))
        order_item = self.create_order_item(order)
        payout = SellerPayout.objects.get(order_item=order_item)
        payout.delivery_status = SellerPayout.DELIVERY_DELIVERED
        payout.courier_number = "OLD123"
        payout.courier_slip = SimpleUploadedFile("slip.jpg", b"filecontent", content_type="image/jpeg")
        payout.save()

        response = self.client.post(
            reverse("sellers:update_own_delivery_status", args=[payout.id]),
            {
                "delivery_status": SellerPayout.DELIVERY_DELIVERED,
                "courier_number": "NEW123",
                "panel_context": "completed-orders",
            },
        )

        self.assertRedirects(response, reverse("sellers:dashboard") + "?panel=completed-orders")



        



    def test_return_deducts_double_delivery_charge_only(self):

        order = self.create_order(delivery_charge=Decimal("50.00"))

        self.create_order_item(order)

        request = ReturnRequest.objects.create(

            order=order,

            user=self.user,

            product=self.product,

            reason=ReturnRequest.REASON_OTHER,

            status=ReturnRequest.STATUS_APPROVED,

            refund_amount=Decimal("1000.00"),

        )



        snapshot = WalletService.get_financial_snapshot(self.seller)



        self.assertEqual(snapshot["pending_payout"], Decimal("-50.00"))

        self.assertTrue(SellerLedger.objects.filter(reference_id=f"return:{request.id}", amount=Decimal("50.00"), component=SellerLedger.COMPONENT_RETURN_SHIPPING).exists())



    def test_successful_payout_marks_available_entries_paid(self):

        order = self.create_order(delivery_charge=Decimal("50.00"))

        self.create_order_item(order)

        SellerLedger.objects.filter(seller=self.seller, order=order).update(status=SellerLedger.STATUS_AVAILABLE)

        SellerOrderPayout.objects.filter(seller=self.seller, order=order).update(status=SellerOrderPayout.STATUS_AVAILABLE)



        payout = PayoutService(gateway_client=MockRazorpayPayoutClient()).release_available_balance(seller=self.seller)

        snapshot = WalletService.get_financial_snapshot(self.seller)



        self.assertEqual(payout.status, Payout.STATUS_COMPLETED)

        self.assertEqual(snapshot["pending_payout"], Decimal("0.00"))

        self.assertEqual(snapshot["paid_payout"], Decimal("640.00"))



    def test_failed_payout_is_logged_and_left_unsettled(self):

        order = self.create_order(delivery_charge=Decimal("50.00"))

        self.create_order_item(order)

        SellerLedger.objects.filter(seller=self.seller, order=order).update(status=SellerLedger.STATUS_AVAILABLE)

        SellerOrderPayout.objects.filter(seller=self.seller, order=order).update(status=SellerOrderPayout.STATUS_AVAILABLE)



        payout = PayoutService(gateway_client=FailedPayoutClient()).release_available_balance(seller=self.seller)



        snapshot = WalletService.get_financial_snapshot(self.seller)

        self.assertEqual(payout.status, Payout.STATUS_FAILED)

        self.assertEqual(snapshot["pending_payout"], Decimal("640.00"))

        self.assertEqual(Payout.objects.filter(status=Payout.STATUS_FAILED).count(), 1)





class SellerProfileRegistrationFormTests(TestCase):

    @classmethod

    def setUpTestData(cls):

        cls.category = Category.objects.create(name="Electronics", slug="electronics")



    def get_form_data(self, **overrides):

        data = {

            "business_name": "Acme Seller",

            "brand_name": "Acme",

            "phone": "9999999999",

            "website": "https://example.com",

            "pan_card_number": "ABCDE1234F",

            "business_pan_card_number": "",

            "aadhar_number": "123412341234",

            "gst_number": "22ABCDE1234F1Z5",

            "payout_upi_id": "seller@okaxis",

            "payout_phonepay_gpay_number": "",

            "supplier_details": "Supplier details",

            "registered_office_address": "Chennai",

            "contact_person_name": "Seller User",

            "contact_email": "seller@example.com",

            "alternate_phone": "",

            "product_categories": [self.category.pk],

            "payout_account_name": "Acme Seller",

            "payout_account_number": "1234567890",

            "payout_ifsc": "ABCD0123456",

            "terms_accepted": True,

        }

        data.update(overrides)

        return data



    def get_form_files(self):

        return {

            "seller_signature": SimpleUploadedFile(

                "signature.gif",

                (

                    b"GIF89a\x01\x00\x01\x00\x80\x00\x00\x00\x00\x00"

                    b"\xff\xff\xff!\xf9\x04\x01\x00\x00\x00\x00,\x00"

                    b"\x00\x00\x00\x01\x00\x01\x00\x00\x02\x02D\x01\x00;"

                ),

                content_type="image/gif",

            )

        }



    def test_phonepay_gpay_number_is_optional(self):

        form = SellerProfileRegistrationForm(

            data=self.get_form_data(),

            files=self.get_form_files(),

        )



        self.assertTrue(form.is_valid(), form.errors)



    def test_phonepay_gpay_number_is_normalized(self):

        form = SellerProfileRegistrationForm(

            data=self.get_form_data(payout_phonepay_gpay_number="+91 98765 43210"),

            files=self.get_form_files(),

        )



        self.assertTrue(form.is_valid(), form.errors)

        self.assertEqual(form.cleaned_data["payout_phonepay_gpay_number"], "9876543210")



    def test_website_is_normalized_to_https_for_common_formats(self):

        cases = {

            "example.com": "https://example.com",

            "www.example.com": "https://www.example.com",

            "http://example.com": "https://example.com",

        }

        for website, expected in cases.items():

            form = SellerProfileRegistrationForm(

                data=self.get_form_data(website=website),

                files=self.get_form_files(),

            )



            self.assertTrue(form.is_valid(), f"{website}: {form.errors}")

            self.assertEqual(form.cleaned_data["website"], expected)



    def test_website_rejects_invalid_text_without_domain_structure(self):

        form = SellerProfileRegistrationForm(

            data=self.get_form_data(website="just some random text"),

            files=self.get_form_files(),

        )



        self.assertFalse(form.is_valid())

        self.assertIn("website", form.errors)



    def test_website_field_renders_as_text_input(self):

        form = SellerProfileRegistrationForm()



        self.assertEqual(form.fields["website"].widget.input_type, "text")



    def test_business_pan_card_number_is_optional(self):

        form = SellerProfileRegistrationForm(

            data=self.get_form_data(business_pan_card_number=""),

            files=self.get_form_files(),

        )



        self.assertTrue(form.is_valid(), form.errors)

        self.assertFalse(form.fields["business_pan_card_number"].required)



    def test_brand_name_is_optional_and_trimmed(self):

        form = SellerProfileRegistrationForm(

            data=self.get_form_data(brand_name="  Acme Premium  "),

            files=self.get_form_files(),

        )



        self.assertTrue(form.is_valid(), form.errors)

        self.assertEqual(form.cleaned_data["brand_name"], "Acme Premium")





@override_settings(EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend")

class SellerRegistrationReviewFlowTests(TestCase):

    @classmethod

    def setUpTestData(cls):

        cls.user = User.objects.create_user(

            username="reviewuser",

            email="review@example.com",

            password="testpass123",

        )

        cls.category = Category.objects.create(name="Home", slug="home")



    def get_form_data(self, **overrides):

        data = {

            "business_name": "Review Seller",

            "brand_name": "Review Brand",

            "phone": "9999999999",

            "website": "https://example.com",

            "pan_card_number": "ABCDE1234F",

            "business_pan_card_number": "",

            "aadhar_number": "123412341234",

            "gst_number": "22ABCDE1234F1Z5",

            "payout_upi_id": "seller@okaxis",

            "payout_phonepay_gpay_number": "",

            "supplier_details": "Supplier details",

            "registered_office_address": "Chennai",

            "contact_person_name": "Seller User",

            "contact_email": "seller@example.com",

            "alternate_phone": "",

            "product_categories": [self.category.pk],

            "payout_account_name": "Review Seller",

            "payout_account_number": "1234567890",

            "payout_ifsc": "ABCD0123456",

            "terms_accepted": True,

        }

        data.update(overrides)

        return data



    def get_form_files(self):

        return {

            "seller_signature": SimpleUploadedFile(

                "signature.gif",

                (

                    b"GIF89a\x01\x00\x01\x00\x80\x00\x00\x00\x00\x00"

                    b"\xff\xff\xff!\xf9\x04\x01\x00\x00\x00\x00,\x00"

                    b"\x00\x00\x00\x01\x00\x01\x00\x00\x02\x02D\x01\x00;"

                ),

                content_type="image/gif",

            )

        }



    def test_registration_post_redirects_to_review_without_creating_profile(self):

        self.client.login(username="reviewuser", password="testpass123")



        response = self.client.post(

            reverse("sellers:create_profile"),

            data={**self.get_form_data(), **self.get_form_files()},

        )



        self.assertRedirects(response, reverse("sellers:review_profile"))

        self.assertFalse(SellerProfile.objects.filter(user=self.user).exists())

        draft = self.client.session.get("seller_registration_draft")

        self.assertEqual(draft["form_data"]["brand_name"], "Review Brand")



    def test_review_page_prefills_edit_form_and_confirm_creates_profile(self):

        self.client.login(username="reviewuser", password="testpass123")

        self.client.post(

            reverse("sellers:create_profile"),

            data={**self.get_form_data(), **self.get_form_files()},

        )



        review_response = self.client.get(reverse("sellers:review_profile"))

        self.assertContains(review_response, "Review Brand")

        self.assertContains(review_response, "Confirm &amp; Submit")



        edit_response = self.client.post(

            reverse("sellers:review_profile"),

            {"action": "edit"},

        )

        self.assertRedirects(edit_response, reverse("sellers:create_profile"))



        form_response = self.client.get(reverse("sellers:create_profile"))

        self.assertContains(form_response, 'value="Review Brand"', html=False)

        self.assertContains(form_response, "Saved for review")



        confirm_response = self.client.post(

            reverse("sellers:review_profile"),

            {"action": "confirm"},

        )

        profile = SellerProfile.objects.get(user=self.user)

        self.assertRedirects(

            confirm_response,

            f"{reverse('sellers:registration_status')}?registration_id={profile.registration_id}",

        )

        self.assertEqual(profile.brand_name, "Review Brand")

        self.assertRegex(

            profile.registration_id,

            rf"^MYKART/{timezone.now().year}/\d{{6}}$",

        )

        self.assertNotIn("seller_registration_draft", self.client.session)









class SellerRegistrationStatusViewTests(TestCase):

    @classmethod

    def setUpTestData(cls):

        cls.user = User.objects.create_user(

            username="statusseller",

            email="statusseller@example.com",

            password="testpass123",

        )

        cls.other_user = User.objects.create_user(

            username="otherseller",

            email="otherseller@example.com",

            password="testpass123",

        )



    def create_profile(self, *, user=None, status=SellerProfile.STATUS_PENDING):

        return SellerProfile.objects.create(

            user=user or self.user,

            business_name="Kids Toys",

            phone="9999999999",

            pan_card_number="ABCDE1234F",

            pan_card_photo="seller_documents/pan.jpg",

            supplier_details="Supplier details",

            registered_office_address="Chennai",

            contact_person_name="Seller User",

            contact_email="seller@example.com",

            payout_account_name="Acme Seller",

            payout_account_number="1234567890",

            payout_ifsc="ABCD0123456",

            terms_accepted=True,

            approval_status=status,

        )



    def test_initial_get_does_not_show_status_result(self):

        profile = self.create_profile()

        self.client.login(username="statusseller", password="testpass123")



        response = self.client.get(reverse("sellers:registration_status"))



        self.assertEqual(response.status_code, 200)

        self.assertEqual(response.context["tracked_profile"], None)

        self.assertFalse(response.context["has_searched"])

        self.assertNotContains(response, profile.business_name)

        self.assertNotContains(response, "Withdraw Registration")



    def test_pending_owner_sees_withdraw_button_after_post_search(self):

        profile = self.create_profile()

        self.client.login(username="statusseller", password="testpass123")



        response = self.client.post(

            reverse("sellers:registration_status"),

            {"registration_id": profile.registration_id},

        )



        self.assertContains(response, "Withdraw Registration")

        self.assertEqual(response.context["tracked_profile"], profile)

        self.assertTrue(response.context["has_searched"])



    def test_invalid_registration_id_shows_not_found_message(self):

        self.client.login(username="statusseller", password="testpass123")



        response = self.client.post(

            reverse("sellers:registration_status"),

            {"registration_id": "999999"},

        )



        self.assertEqual(response.status_code, 200)

        self.assertTrue(response.context["has_searched"])

        self.assertEqual(response.context["tracked_profile"], None)

        self.assertContains(response, "No registration found for that ID.")



    def test_multiple_searches_refresh_results(self):

        first_profile = self.create_profile()

        second_profile = self.create_profile(user=self.other_user)

        self.client.login(username="statusseller", password="testpass123")



        first_response = self.client.post(

            reverse("sellers:registration_status"),

            {"registration_id": first_profile.registration_id},

        )

        second_response = self.client.post(

            reverse("sellers:registration_status"),

            {"registration_id": second_profile.registration_id},

        )



        self.assertContains(first_response, first_profile.business_name)

        self.assertNotContains(first_response, second_profile.registration_id)

        self.assertContains(second_response, second_profile.business_name)

        self.assertNotContains(second_response, first_profile.registration_id)



    def test_withdraw_registration_deletes_pending_profile(self):

        profile = self.create_profile()

        self.client.login(username="statusseller", password="testpass123")



        response = self.client.post(

            reverse("sellers:withdraw_registration"),

            {"registration_id": profile.registration_id},

        )



        self.assertRedirects(response, reverse("sellers:create_profile"))

        self.assertFalse(SellerProfile.objects.filter(id=profile.id).exists())



    def test_withdraw_registration_does_not_delete_other_users_profile(self):

        profile = self.create_profile(user=self.other_user)

        self.client.login(username="statusseller", password="testpass123")



        response = self.client.post(

            reverse("sellers:withdraw_registration"),

            {"registration_id": profile.registration_id},

        )



        self.assertRedirects(response, reverse("sellers:registration_status"))

        self.assertTrue(SellerProfile.objects.filter(id=profile.id).exists())



    def test_withdraw_registration_blocks_non_pending_profiles(self):

        profile = self.create_profile(status=SellerProfile.STATUS_APPROVED)

        self.client.login(username="statusseller", password="testpass123")



        response = self.client.post(

            reverse("sellers:withdraw_registration"),

            {"registration_id": profile.registration_id},

        )



        self.assertRedirects(

            response,

            f"{reverse('sellers:registration_status')}?registration_id={profile.registration_id}",

        )

        self.assertTrue(SellerProfile.objects.filter(id=profile.id).exists())



class SellerProductPublishFormTests(TestCase):

    @classmethod

    def setUpTestData(cls):

        cls.category = Category.objects.create(name="Electronics", slug="electronics")



    def make_image(self, name="item.png"):

        return SimpleUploadedFile(name, b"fake-image-bytes", content_type="image/png")



    def test_product_entry_form_calculates_discounted_amount(self):

        form = SellerProductEntryForm(

            data={

                "category": self.category.pk,

                "new_category_name": "",

                "name": "Galaxy Watch",

                "slug": "",

                "description": "Smart watch",

                "price": "1000.00",

                "stock": "5",

                "offer_discount": "yes",

                "discount_percent": "20",

                "discounted_amount": "",

            },

            files={"images": [self.make_image()]},

        )



        self.assertTrue(form.is_valid(), form.errors)

        self.assertEqual(form.cleaned_data["slug"], "galaxy-watch")

        self.assertEqual(form.cleaned_data["discounted_amount"], Decimal("800.00"))



    def test_product_entry_form_rejects_more_than_six_images(self):

        images = [self.make_image(f"item-{index}.png") for index in range(7)]

        form = SellerProductEntryForm(

            data={

                "category": self.category.pk,

                "name": "Camera",

                "slug": "camera",

                "description": "",

                "price": "500.00",

                "stock": "2",

                "offer_discount": "no",

                "discount_percent": "",

                "discounted_amount": "",

            },

            files={"images": images},

        )


        self.assertFalse(form.is_valid())

        self.assertIn("images", form.errors)



    def test_shared_settings_form_requires_only_active_publish_fields(self):

        form = SellerProductSharedSettingsForm(
            data={
                "shipping_details": "Ships directly from seller within 2 business days.",
                "payout_rate_own_delivery": "90.00",
                "payout_rate_hub_delivery": "82.00",
            }
        )

        self.assertTrue(form.is_valid(), form.errors)
        self.assertEqual(form.cleaned_data["delivery_mode"], SellerProduct.OWN_DELIVERY)
        self.assertEqual(form.cleaned_data["delivery_type"], SellerProduct.DELIVERY_TYPE_OWN)
        self.assertEqual(form.cleaned_data["estimated_delivery_charge"], Decimal("0.00"))
        self.assertEqual(form.cleaned_data["hub_name"], "")
        self.assertEqual(form.cleaned_data["hub_address"], "")



    def test_seller_coupon_form_validates_coupon_window_and_uniqueness(self):

        Coupon.objects.create(code="MYKART-NIKE-AB12C", discount_percent=10)

        form = SellerCouponForm(

            data={

                "coupon_code": "MYKART-NIKE-AB12C",

                "coupon_discount_percent": "15",

                "coupon_active": "on",

                "coupon_valid_from": "2026-04-07T10:00",

                "coupon_valid_to": "2026-04-07T09:00",

            },

            files={"images": [self.make_image()]},

        )



        self.assertFalse(form.is_valid())

        self.assertIn("coupon_code", form.errors)

        self.assertIn("coupon_valid_to", form.errors)





@override_settings(EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend")

class SellerProductPublishViewTests(TestCase):

    @classmethod

    def setUpClass(cls):

        super().setUpClass()

        cls._temp_media_dir = os.path.join(settings.BASE_DIR, "test_media_seller_publish")

        shutil.rmtree(cls._temp_media_dir, ignore_errors=True)

        os.makedirs(cls._temp_media_dir, exist_ok=True)

        cls._media_override = override_settings(MEDIA_ROOT=cls._temp_media_dir)

        cls._media_override.enable()



    @classmethod

    def tearDownClass(cls):

        cls._media_override.disable()

        shutil.rmtree(cls._temp_media_dir, ignore_errors=True)

        super().tearDownClass()



    def setUp(self):

        self.expected_seller_from = (

            settings.EMAIL_HOST_USER

            if settings.EMAIL_HOST_USER and settings.EMAIL_HOST_USER.lower() != "business@mykartstore.com"

            else "business@mykartstore.com"

        )



    @classmethod

    def setUpTestData(cls):

        cls.user = User.objects.create_user(username="sellerpub", password="testpass123")

        cls.category = Category.objects.create(name="Wearables", slug="wearables")

        cls.seller = SellerProfile.objects.create(

            user=cls.user,

            business_name="Acme Seller",

            brand_name="Nike",

            phone="9999999999",

            pan_card_number="ABCDE1234F",

            pan_card_photo="seller_documents/pan.jpg",

            supplier_details="Supplier details",

            registered_office_address="Chennai",

            contact_person_name="Seller User",

            contact_email="seller@example.com",

            payout_account_name="Acme Seller",

            payout_account_number="1234567890",

            payout_ifsc="ABCD0123456",

            terms_accepted=True,

            approval_status=SellerProfile.STATUS_APPROVED,

        )



    def make_image(self, name):

        return SimpleUploadedFile(name, b"fake-image-bytes", content_type="image/png")



    def test_publish_view_creates_multiple_products_and_images(self):

        self.client.login(username="sellerpub", password="testpass123")

        mail.outbox = []



        session = self.client.session

        session["seller_publish_submission_key"] = "publish-key-1"

        session.save()



        payload = {

            "submission_key": "publish-key-1",

            "products-TOTAL_FORMS": "2",

            "products-INITIAL_FORMS": "0",

            "products-MIN_NUM_FORMS": "0",

            "products-MAX_NUM_FORMS": "1000",

            "products-0-category": str(self.category.pk),

            "products-0-new_category_name": "",

            "products-0-name": "Runner One",

            "products-0-slug": "",

            "products-0-description": "Lightweight",

            "products-0-price": "1200.00",

            "products-0-stock": "5",

            "products-0-offer_discount": "yes",

            "products-0-discount_percent": "10",

            "products-0-discounted_amount": "1080.00",

            "products-0-images": [self.make_image("one.png"), self.make_image("two.png")],

            "products-1-category": str(self.category.pk),

            "products-1-new_category_name": "",

            "products-1-name": "Runner Two",

            "products-1-slug": "runner-two",

            "products-1-description": "Daily trainer",

            "products-1-price": "1500.00",

            "products-1-stock": "3",

            "products-1-offer_discount": "no",

            "products-1-discount_percent": "",

            "products-1-discounted_amount": "1500.00",

            "products-1-images": [self.make_image("three.png")],

            "settings-delivery_mode": SellerProduct.OWN_DELIVERY,

            "settings-delivery_type": SellerProduct.DELIVERY_TYPE_OWN,

            "settings-estimated_delivery_charge": "0.00",

            "settings-shipping_details": "Ships directly from seller",

            "settings-hub_name": "",

            "settings-hub_address": "",

            "settings-handover_instructions": "",

            "settings-payout_rate_own_delivery": "90.00",

            "settings-payout_rate_hub_delivery": "82.00",

            "coupon-coupon_code": "MYKART-NIKE-X7A2K",

            "coupon-coupon_discount_percent": "15",

            "coupon-coupon_active": "on",

            "coupon-coupon_valid_from": "2026-04-07T10:00",

            "coupon-coupon_valid_to": "2026-04-10T10:00",

        }

        response = self.client.post(reverse("sellers:publish_product"), data=payload)



        self.assertEqual(response.status_code, 302)

        self.assertEqual(Product.objects.count(), 2)

        first = Product.objects.get(name="Runner One")

        second = Product.objects.get(name="Runner Two")

        self.assertEqual(first.status, Product.STATUS_PENDING)

        self.assertFalse(first.available)

        self.assertEqual(second.status, Product.STATUS_PENDING)

        self.assertFalse(second.available)

        self.assertEqual(first.brand, "")

        self.assertEqual(first.slug, "runner-one")

        self.assertEqual(first.discount_percent, Decimal("10"))

        self.assertEqual(first.discount_amount, Decimal("120.00"))

        self.assertEqual(first.images.count(), 2)

        self.assertEqual(second.images.count(), 1)

        self.assertEqual(ProductImage.objects.filter(product=first).first().sort_order, 0)

        coupon = Coupon.objects.get(seller=self.seller, code="MYKART-NIKE-X7A2K")

        self.assertEqual(coupon.code, "MYKART-NIKE-X7A2K")

        self.assertEqual(coupon.discount_percent, 15)

        self.assertIsNone(coupon.product)



    def test_publish_view_ignores_deleted_blank_product_blocks(self):
        self.client.login(username="sellerpub", password="testpass123")
        session = self.client.session
        session["seller_publish_submission_key"] = "publish-key-2"
        session.save()



        payload = {

            "submission_key": "publish-key-2",

            "products-TOTAL_FORMS": "2",

            "products-INITIAL_FORMS": "0",

            "products-MIN_NUM_FORMS": "0",

            "products-MAX_NUM_FORMS": "1000",

            "products-0-category": str(self.category.pk),

            "products-0-new_category_name": "",

            "products-0-name": "Runner Three",

            "products-0-slug": "",

            "products-0-description": "Stable trainer",

            "products-0-price": "999.00",

            "products-0-stock": "5",

            "products-0-offer_discount": "no",

            "products-1-DELETE": "on",

            "settings-delivery_mode": SellerProduct.OWN_DELIVERY,

            "settings-delivery_type": SellerProduct.DELIVERY_TYPE_OWN,

            "settings-estimated_delivery_charge": "0.00",

            "settings-shipping_details": "Ships directly from seller",

            "settings-payout_rate_own_delivery": "90.00",

            "settings-payout_rate_hub_delivery": "82.00",

        }



        with self.captureOnCommitCallbacks(execute=True):

            response = self.client.post(reverse("sellers:publish_product"), data=payload)



        self.assertEqual(response.status_code, 302)

       

        product = Product.objects.get(name="Runner Three")
        self.assertEqual(product.status, Product.STATUS_PENDING)
        self.assertFalse(product.available)

    def test_publish_view_accepts_single_filled_product_with_blank_extra_block(self):
        self.client.login(username="sellerpub", password="testpass123")
        session = self.client.session
        session["seller_publish_submission_key"] = "publish-key-blank-extra"
        session.save()

        payload = {
            "submission_key": "publish-key-blank-extra",
            "products-TOTAL_FORMS": "2",
            "products-INITIAL_FORMS": "0",
            "products-MIN_NUM_FORMS": "0",
            "products-MAX_NUM_FORMS": "1000",
            "products-0-category": str(self.category.pk),
            "products-0-new_category_name": "",
            "products-0-name": "Runner Three Blank Extra",
            "products-0-slug": "",
            "products-0-description": "Stable trainer",
            "products-0-price": "999.00",
            "products-0-stock": "5",
            "products-0-offer_discount": "no",
            "products-1-category": "",
            "products-1-new_category_name": "",
            "products-1-name": "",
            "products-1-slug": "",
            "products-1-description": "",
            "products-1-price": "",
            "products-1-stock": "",
            "products-1-offer_discount": "no",
            "settings-delivery_mode": SellerProduct.OWN_DELIVERY,
            "settings-delivery_type": SellerProduct.DELIVERY_TYPE_OWN,
            "settings-estimated_delivery_charge": "0.00",
            "settings-shipping_details": "Ships directly from seller",
            "settings-payout_rate_own_delivery": "90.00",
            "settings-payout_rate_hub_delivery": "82.00",
        }

        with self.captureOnCommitCallbacks(execute=True):
            response = self.client.post(reverse("sellers:publish_product"), data=payload)

        self.assertEqual(response.status_code, 302)
        self.assertTrue(Product.objects.filter(name="Runner Three Blank Extra").exists())
        self.assertEqual(Product.objects.filter(name="Runner Three Blank Extra").count(), 1)


    def test_publish_view_does_not_require_removed_delivery_fields(self):
        self.client.login(username="sellerpub", password="testpass123")
        session = self.client.session
        session["seller_publish_submission_key"] = "publish-key-active-settings"
        session.save()

        payload = {
            "submission_key": "publish-key-active-settings",
            "products-TOTAL_FORMS": "1",
            "products-INITIAL_FORMS": "0",
            "products-MIN_NUM_FORMS": "0",
            "products-MAX_NUM_FORMS": "1000",
            "products-0-category": str(self.category.pk),
            "products-0-new_category_name": "",
            "products-0-name": "Runner Active Settings",
            "products-0-slug": "",
            "products-0-description": "Streamlined publish form",
            "products-0-price": "899.00",
            "products-0-stock": "6",
            "products-0-offer_discount": "no",
            "settings-shipping_details": "Ships directly from seller",
            "settings-payout_rate_own_delivery": "90.00",
            "settings-payout_rate_hub_delivery": "82.00",
        }

        with self.captureOnCommitCallbacks(execute=True):
            response = self.client.post(reverse("sellers:publish_product"), data=payload)

        self.assertEqual(response.status_code, 302)
        seller_product = SellerProduct.objects.get(product__name="Runner Active Settings")
        self.assertEqual(seller_product.delivery_mode, SellerProduct.OWN_DELIVERY)
        self.assertEqual(seller_product.delivery_type, SellerProduct.DELIVERY_TYPE_OWN)
        self.assertEqual(seller_product.estimated_delivery_charge, Decimal("0.00"))
        self.assertEqual(seller_product.shipping_details, "Ships directly from seller")




    def test_publish_view_is_idempotent_for_duplicate_submission_key(self):

        self.client.login(username="sellerpub", password="testpass123")

        session = self.client.session

        session["seller_publish_submission_key"] = "publish-key-3"

        session.save()



        payload = {

            "submission_key": "publish-key-3",

            "products-TOTAL_FORMS": "1",

            "products-INITIAL_FORMS": "0",

            "products-MIN_NUM_FORMS": "0",

            "products-MAX_NUM_FORMS": "1000",

            "products-0-category": str(self.category.pk),

            "products-0-new_category_name": "",

            "products-0-name": "Runner Four",

            "products-0-slug": "",

            "products-0-description": "Tempo trainer",

            "products-0-price": "1100.00",

            "products-0-stock": "4",

            "products-0-offer_discount": "no",

            "settings-delivery_mode": SellerProduct.OWN_DELIVERY,

            "settings-delivery_type": SellerProduct.DELIVERY_TYPE_OWN,

            "settings-estimated_delivery_charge": "0.00",

            "settings-shipping_details": "Ships directly from seller",

            "settings-payout_rate_own_delivery": "90.00",

            "settings-payout_rate_hub_delivery": "82.00",

        }



        first_response = self.client.post(reverse("sellers:publish_product"), data=payload)

        second_response = self.client.post(reverse("sellers:publish_product"), data=payload)



        self.assertEqual(first_response.status_code, 302)

        self.assertEqual(second_response.status_code, 302)

        self.assertEqual(Product.objects.filter(name="Runner Four").count(), 1)



    def test_publish_view_does_not_send_creation_email(self):

        self.client.login(username="sellerpub", password="testpass123")

        mail.outbox = []



        session = self.client.session

        session["seller_publish_submission_key"] = "publish-key-4"

        session.save()



        payload = {

            "submission_key": "publish-key-4",

            "products-TOTAL_FORMS": "1",

            "products-INITIAL_FORMS": "0",

            "products-MIN_NUM_FORMS": "0",

            "products-MAX_NUM_FORMS": "1000",

            "products-0-category": str(self.category.pk),

            "products-0-new_category_name": "",

            "products-0-name": "Runner Five",

            "products-0-slug": "",

            "products-0-description": "Tempo trainer",

            "products-0-price": "1100.00",

            "products-0-stock": "4",

            "products-0-offer_discount": "no",

            "settings-delivery_mode": SellerProduct.OWN_DELIVERY,

            "settings-delivery_type": SellerProduct.DELIVERY_TYPE_OWN,

            "settings-estimated_delivery_charge": "0.00",

            "settings-shipping_details": "Ships directly from seller",

            "settings-payout_rate_own_delivery": "90.00",

            "settings-payout_rate_hub_delivery": "82.00",

        }



        with self.captureOnCommitCallbacks(execute=True):

            response = self.client.post(reverse("sellers:publish_product"), data=payload)



        self.assertEqual(response.status_code, 302)

        self.assertEqual(mail.outbox, [])



    def test_publish_page_shows_delivery_charges_guide_toggle(self):

        self.client.login(username="sellerpub", password="testpass123")



        response = self.client.get(reverse("sellers:publish_product"))



        self.assertContains(response, "View Delivery Charges Guide")

        self.assertContains(response, "Same city")

        self.assertContains(response, "Remote zones")


class SellerNotificationDashboardTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.seller_user = User.objects.create_user(username="notify-seller", password="testpass123")
        cls.buyer = User.objects.create_user(username="notify-buyer", password="testpass123")
        cls.category = Category.objects.create(name="Notify Category", slug="notify-category")
        cls.product = Product.objects.create(
            category=cls.category,
            name="Handmade Jewelry",
            slug="notify-jewelry",
            description="Test product",
            price=Decimal("1200.00"),
            stock=10,
            available=True,
        )
        cls.seller = SellerProfile.objects.create(
            user=cls.seller_user,
            business_name="Notify Seller",
            phone="9999999999",
            pan_card_number="ABCDE1234F",
            pan_card_photo="seller_documents/pan.jpg",
            supplier_details="Supplier details",
            registered_office_address="Chennai",
            contact_person_name="Seller User",
            contact_email="seller@example.com",
            payout_account_name="Notify Seller",
            payout_account_number="1234567890",
            payout_ifsc="ABCD0123456",
            terms_accepted=True,
            approval_status=SellerProfile.STATUS_APPROVED,
        )
        SellerProduct.objects.create(
            seller=cls.seller,
            product=cls.product,
            delivery_mode=SellerProduct.OWN_DELIVERY,
            delivery_type=SellerProduct.DELIVERY_TYPE_OWN,
            shipping_details="Ships directly",
        )

    def setUp(self):
        self.client.login(username="notify-seller", password="testpass123")

    def _create_notification(self, *, hours_offset=0, is_read=False):
        order = Order.objects.create(
            user=self.buyer,
            full_name="Buyer Name",
            email="buyer@example.com",
            phone_number="9876543210",
            address="Chennai",
            paid=True,
            payment_method=Order.PAYMENT_ONLINE,
            delivery_type=Order.DELIVERY_TYPE_OWN,
        )
        order_item = OrderItem.objects.create(
            order=order,
            product=self.product,
            price=Decimal("1200.00"),
            quantity=1,
        )
        notification = SellerNotification.objects.filter(
            recipient=self.seller_user,
            order_item=order_item,
            notification_type=SellerNotification.TYPE_SELLER_ORDER,
        ).get()
        if is_read:
            notification.is_read = True
            notification.save(update_fields=["is_read"])
        if hours_offset:
            notification.created_at = timezone.now() + timezone.timedelta(hours=hours_offset)
            notification.save(update_fields=["created_at"])
        return notification

    def test_dashboard_shows_all_notifications_newest_first_with_formatted_message(self):
        oldest = self._create_notification(hours_offset=-2)
        newest = self._create_notification(hours_offset=2)

        response = self.client.get(reverse("sellers:dashboard") + "?panel=notifications")

        notifications = list(response.context["notifications"])
        self.assertEqual(len(notifications), 2)
        self.assertEqual(notifications[0].id, newest.id)
        self.assertEqual(notifications[1].id, oldest.id)
        self.assertEqual(response.context["unread_notification_count"], 2)
        self.assertContains(response, "Handmade Jewelry")
        self.assertContains(response, newest.order_item.order.display_order_id)
        self.assertNotContains(response, "New own-delivery order for")

    def test_mark_notification_as_read_updates_unread_count(self):
        notification = self._create_notification()

        response = self.client.post(reverse("sellers:mark_notification_as_read", args=[notification.id]))

        self.assertRedirects(response, reverse("sellers:dashboard") + "?panel=notifications")
        notification.refresh_from_db()
        self.assertTrue(notification.is_read)

        dashboard_response = self.client.get(reverse("sellers:dashboard") + "?panel=notifications")
        self.assertEqual(dashboard_response.context["unread_notification_count"], 0)














