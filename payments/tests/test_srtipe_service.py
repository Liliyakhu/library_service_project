from decimal import Decimal
from datetime import timedelta
from unittest.mock import patch, Mock, MagicMock
import stripe

from django.contrib.auth import get_user_model
from django.test import RequestFactory
from django.urls import reverse
from rest_framework.test import APITestCase, APIClient

from borrowings.models import Borrowing
from payments.models import Payment
from payments.stripe_service import StripeService
from books.models import Book
from core.utils.timezone_utils import kyiv_now

User = get_user_model()


class StripeServiceCreateCheckoutSessionTestCase(APITestCase):
    """Test suite for StripeService.create_checkout_session"""

    def setUp(self):
        """Set up test data"""
        self.factory = RequestFactory()

        # Create test user
        self.user = User.objects.create_user(
            email="test@example.com", password="testpass123"
        )

        # Create test book
        self.book = Book.objects.create(
            title="Test Book",
            author="Test Author",
            cover="hard",
            inventory=5,
            daily_fee=Decimal("2.00"),
        )

        # Create test borrowing
        self.borrowing = Borrowing.objects.create(
            user=self.user,
            book=self.book,
            borrow_date=kyiv_now().date(),
            expected_return_date=(kyiv_now() + timedelta(days=7)).date(),
        )

        # Create overdue borrowing for fine tests
        self.overdue_borrowing = Borrowing.objects.create(
            user=self.user,
            book=self.book,
            borrow_date=(kyiv_now() - timedelta(days=10)).date(),
            expected_return_date=(kyiv_now() - timedelta(days=3)).date(),
            actual_return_date=kyiv_now().date(),
        )

        # Create payment
        self.payment = Payment.objects.create(
            borrowing=self.borrowing,
            type="payment",
            status="pending",
            money_to_pay=Decimal("14.00"),
        )

        # Create fine payment
        self.fine_payment = Payment.objects.create(
            borrowing=self.overdue_borrowing,
            type="fine",
            status="pending",
            money_to_pay=Decimal("6.00"),
        )

    @patch("stripe.checkout.Session.create")
    def test_create_checkout_session_success(self, mock_stripe_create):
        """Test successful checkout session creation"""
        mock_session = Mock()
        mock_session.id = "sess_test_123"
        mock_session.url = "https://checkout.stripe.com/test"
        mock_stripe_create.return_value = mock_session

        request = self.factory.post("/payments/")
        request.user = self.user

        result = StripeService.create_checkout_session(self.payment, request)

        self.assertTrue(result["success"])
        self.assertEqual(result["session_id"], "sess_test_123")
        self.assertEqual(result["session_url"], "https://checkout.stripe.com/test")
        mock_stripe_create.assert_called_once()

    @patch("stripe.checkout.Session.create")
    def test_create_checkout_session_payment_type(self, mock_stripe_create):
        """Test checkout session for payment type"""
        mock_session = Mock()
        mock_session.id = "sess_payment"
        mock_session.url = "https://checkout.stripe.com/payment"
        mock_stripe_create.return_value = mock_session

        request = self.factory.post("/payments/")
        request.user = self.user

        result = StripeService.create_checkout_session(self.payment, request)

        # Verify the call was made with correct parameters
        call_args = mock_stripe_create.call_args
        self.assertIn("line_items", call_args.kwargs)

        # Check product name contains book title
        product_name = call_args.kwargs["line_items"][0]["price_data"]["product_data"][
            "name"
        ]
        self.assertIn(self.book.title, product_name)

    @patch("stripe.checkout.Session.create")
    def test_create_checkout_session_fine_type(self, mock_stripe_create):
        """Test checkout session for fine type"""
        mock_session = Mock()
        mock_session.id = "sess_fine"
        mock_session.url = "https://checkout.stripe.com/fine"
        mock_stripe_create.return_value = mock_session

        request = self.factory.post("/payments/")
        request.user = self.user

        result = StripeService.create_checkout_session(self.fine_payment, request)

        # Verify the call was made
        call_args = mock_stripe_create.call_args

        # Check product name mentions fine
        product_name = call_args.kwargs["line_items"][0]["price_data"]["product_data"][
            "name"
        ]
        self.assertIn("Fine", product_name)
        self.assertIn(self.book.title, product_name)

    @patch("stripe.checkout.Session.create")
    def test_create_checkout_session_amount_conversion(self, mock_stripe_create):
        """Test amount is converted to cents correctly"""
        mock_session = Mock()
        mock_session.id = "sess_test"
        mock_session.url = "https://checkout.stripe.com/test"
        mock_stripe_create.return_value = mock_session

        request = self.factory.post("/payments/")

        result = StripeService.create_checkout_session(self.payment, request)

        # Check amount was converted to cents (14.00 -> 1400)
        call_args = mock_stripe_create.call_args
        unit_amount = call_args.kwargs["line_items"][0]["price_data"]["unit_amount"]
        self.assertEqual(unit_amount, 1400)

    @patch("stripe.checkout.Session.create")
    def test_create_checkout_session_urls(self, mock_stripe_create):
        """Test success and cancel URLs are set correctly"""
        mock_session = Mock()
        mock_session.id = "sess_test"
        mock_session.url = "https://checkout.stripe.com/test"
        mock_stripe_create.return_value = mock_session

        request = self.factory.post("/payments/")

        result = StripeService.create_checkout_session(self.payment, request)

        call_args = mock_stripe_create.call_args
        success_url = call_args.kwargs["success_url"]
        cancel_url = call_args.kwargs["cancel_url"]

        self.assertIn("success", success_url)
        self.assertIn("cancel", cancel_url)
        self.assertIn("session_id={CHECKOUT_SESSION_ID}", success_url)
        self.assertIn("session_id={CHECKOUT_SESSION_ID}", cancel_url)

    @patch("stripe.checkout.Session.create")
    def test_create_checkout_session_metadata(self, mock_stripe_create):
        """Test metadata is included in session"""
        mock_session = Mock()
        mock_session.id = "sess_test"
        mock_session.url = "https://checkout.stripe.com/test"
        mock_stripe_create.return_value = mock_session

        request = self.factory.post("/payments/")

        result = StripeService.create_checkout_session(self.payment, request)

        call_args = mock_stripe_create.call_args
        metadata = call_args.kwargs["metadata"]

        self.assertEqual(metadata["payment_id"], self.payment.id)
        self.assertEqual(metadata["payment_type"], "payment")
        self.assertEqual(metadata["borrowing_id"], self.borrowing.id)

    @patch("stripe.checkout.Session.create")
    def test_create_checkout_session_expiration(self, mock_stripe_create):
        """Test session has expiration time set"""
        mock_session = Mock()
        mock_session.id = "sess_test"
        mock_session.url = "https://checkout.stripe.com/test"
        mock_stripe_create.return_value = mock_session

        request = self.factory.post("/payments/")

        result = StripeService.create_checkout_session(self.payment, request)

        call_args = mock_stripe_create.call_args
        expires_at = call_args.kwargs["expires_at"]

        self.assertIsNotNone(expires_at)
        self.assertIsInstance(expires_at, int)

    @patch("stripe.checkout.Session.create")
    def test_create_checkout_session_stripe_error(self, mock_stripe_create):
        """Test handling of Stripe API error"""
        mock_stripe_create.side_effect = stripe.error.StripeError("API Error")

        request = self.factory.post("/payments/")

        result = StripeService.create_checkout_session(self.payment, request)

        self.assertFalse(result["success"])
        self.assertIn("error", result)
        self.assertIn("API Error", result["error"])

    @patch("stripe.checkout.Session.create")
    def test_create_checkout_session_generic_exception(self, mock_stripe_create):
        """Test handling of generic exception"""
        mock_stripe_create.side_effect = Exception("Unexpected error")

        request = self.factory.post("/payments/")

        result = StripeService.create_checkout_session(self.payment, request)

        self.assertFalse(result["success"])
        self.assertIn("error", result)


class StripeServiceRenewCheckoutSessionTestCase(APITestCase):
    """Test suite for StripeService.renew_checkout_session"""

    def setUp(self):
        """Set up test data"""
        self.factory = RequestFactory()

        self.user = User.objects.create_user(
            email="test@example.com", password="testpass123"
        )

        self.book = Book.objects.create(
            title="Test Book",
            author="Test Author",
            cover="hard",
            inventory=5,
            daily_fee=Decimal("2.00"),
        )

        self.borrowing = Borrowing.objects.create(
            user=self.user,
            book=self.book,
            borrow_date=kyiv_now().date(),
            expected_return_date=(kyiv_now() + timedelta(days=7)).date(),
        )

        # Create expired payment (renewable)
        self.expired_payment = Payment.objects.create(
            borrowing=self.borrowing,
            type="payment",
            status="expired",
            money_to_pay=Decimal("14.00"),
        )

        # Create paid payment (not renewable)
        self.paid_payment = Payment.objects.create(
            borrowing=self.borrowing,
            type="fine",
            status="paid",
            money_to_pay=Decimal("5.00"),
            session_id="sess_paid",
            session_url="https://stripe.com/session",
        )

    @patch("payments.stripe_service.StripeService.create_checkout_session")
    def test_renew_checkout_session_success(self, mock_create_session):
        """Test successful session renewal"""
        mock_create_session.return_value = {
            "success": True,
            "session_id": "sess_renewed_123",
            "session_url": "https://checkout.stripe.com/renewed",
        }

        request = self.factory.post("/payments/renew/")

        result = StripeService.renew_checkout_session(self.expired_payment, request)

        self.assertTrue(result["success"])
        self.assertEqual(result["session_id"], "sess_renewed_123")
        self.assertEqual(result["payment_id"], self.expired_payment.id)
        self.assertIn("message", result)

    @patch("payments.stripe_service.StripeService.create_checkout_session")
    def test_renew_checkout_session_updates_payment(self, mock_create_session):
        """Test that renewal updates payment with new session data"""
        mock_create_session.return_value = {
            "success": True,
            "session_id": "sess_new",
            "session_url": "https://checkout.stripe.com/new",
        }

        request = self.factory.post("/payments/renew/")

        result = StripeService.renew_checkout_session(self.expired_payment, request)

        self.expired_payment.refresh_from_db()
        self.assertEqual(self.expired_payment.session_id, "sess_new")
        self.assertEqual(self.expired_payment.status, "pending")

    def test_renew_checkout_session_not_renewable(self):
        """Test renewal fails for non-renewable payment"""
        request = self.factory.post("/payments/renew/")

        result = StripeService.renew_checkout_session(self.paid_payment, request)

        self.assertFalse(result["success"])
        self.assertIn("cannot be renewed", result["error"])

    @patch("payments.stripe_service.StripeService.create_checkout_session")
    def test_renew_checkout_session_stripe_failure(self, mock_create_session):
        """Test renewal when Stripe session creation fails"""
        mock_create_session.return_value = {
            "success": False,
            "error": "Stripe API error",
        }

        request = self.factory.post("/payments/renew/")

        result = StripeService.renew_checkout_session(self.expired_payment, request)

        self.assertFalse(result["success"])
        self.assertIn("error", result)

    @patch("payments.stripe_service.StripeService.create_checkout_session")
    def test_renew_checkout_session_exception(self, mock_create_session):
        """Test renewal handles exceptions"""
        mock_create_session.side_effect = Exception("Unexpected error")

        request = self.factory.post("/payments/renew/")

        result = StripeService.renew_checkout_session(self.expired_payment, request)

        self.assertFalse(result["success"])
        self.assertIn("error", result)


class StripeServiceRetrieveSessionTestCase(APITestCase):
    """Test suite for StripeService session retrieval methods"""

    @patch("stripe.checkout.Session.retrieve")
    def test_retrieve_checkout_session_success(self, mock_retrieve):
        """Test successful session retrieval"""
        mock_session = Mock()
        mock_session.id = "sess_123"
        mock_session.status = "open"
        mock_retrieve.return_value = mock_session

        result = StripeService.retrieve_checkout_session("sess_123")

        self.assertIsNotNone(result)
        self.assertEqual(result.id, "sess_123")
        mock_retrieve.assert_called_once_with("sess_123")

    @patch("stripe.checkout.Session.retrieve")
    def test_retrieve_checkout_session_stripe_error(self, mock_retrieve):
        """Test session retrieval with Stripe error"""
        mock_retrieve.side_effect = stripe.error.StripeError("Session not found")

        result = StripeService.retrieve_checkout_session("sess_invalid")

        self.assertIsNone(result)

    @patch("stripe.checkout.Session.retrieve")
    def test_retrieve_checkout_session_generic_error(self, mock_retrieve):
        """Test session retrieval with generic error"""
        mock_retrieve.side_effect = Exception("Network error")

        result = StripeService.retrieve_checkout_session("sess_123")

        self.assertIsNone(result)

    @patch("stripe.checkout.Session.retrieve")
    def test_is_session_paid_true(self, mock_retrieve):
        """Test is_session_paid returns True for paid session"""
        mock_session = Mock()
        mock_session.payment_status = "paid"
        mock_retrieve.return_value = mock_session

        result = StripeService.is_session_paid("sess_paid")

        self.assertTrue(result)

    @patch("stripe.checkout.Session.retrieve")
    def test_is_session_paid_false(self, mock_retrieve):
        """Test is_session_paid returns False for unpaid session"""
        mock_session = Mock()
        mock_session.payment_status = "unpaid"
        mock_retrieve.return_value = mock_session

        result = StripeService.is_session_paid("sess_unpaid")

        self.assertFalse(result)

    @patch("stripe.checkout.Session.retrieve")
    def test_is_session_paid_error(self, mock_retrieve):
        """Test is_session_paid returns False on error"""
        mock_retrieve.return_value = None

        result = StripeService.is_session_paid("sess_error")

        self.assertFalse(result)

    @patch("stripe.checkout.Session.retrieve")
    def test_is_session_expired_true(self, mock_retrieve):
        """Test is_session_expired returns True for expired session"""
        mock_session = Mock()
        mock_session.status = "expired"
        mock_retrieve.return_value = mock_session

        result = StripeService.is_session_expired("sess_expired")

        self.assertTrue(result)

    @patch("stripe.checkout.Session.retrieve")
    def test_is_session_expired_false(self, mock_retrieve):
        """Test is_session_expired returns False for active session"""
        mock_session = Mock()
        mock_session.status = "open"
        mock_retrieve.return_value = mock_session

        result = StripeService.is_session_expired("sess_active")

        self.assertFalse(result)

    @patch("stripe.checkout.Session.retrieve")
    def test_is_session_expired_error(self, mock_retrieve):
        """Test is_session_expired returns None on error"""
        mock_retrieve.return_value = None

        result = StripeService.is_session_expired("sess_error")

        self.assertIsNone(result)

    @patch("stripe.checkout.Session.retrieve")
    def test_get_session_status_success(self, mock_retrieve):
        """Test get_session_status returns complete status info"""
        mock_session = Mock()
        mock_session.id = "sess_123"
        mock_session.status = "complete"
        mock_session.payment_status = "paid"
        mock_session.expires_at = 1234567890
        mock_session.created = 1234567800
        mock_session.url = "https://checkout.stripe.com/test"
        mock_session.amount_total = 1000
        mock_session.currency = "usd"
        mock_retrieve.return_value = mock_session

        result = StripeService.get_session_status("sess_123")

        self.assertIsNotNone(result)
        self.assertEqual(result["id"], "sess_123")
        self.assertEqual(result["status"], "complete")
        self.assertEqual(result["payment_status"], "paid")
        self.assertEqual(result["amount_total"], 1000)
        self.assertEqual(result["currency"], "usd")

    @patch("stripe.checkout.Session.retrieve")
    def test_get_session_status_error(self, mock_retrieve):
        """Test get_session_status returns None on error"""
        mock_retrieve.return_value = None

        result = StripeService.get_session_status("sess_error")

        self.assertIsNone(result)


class StripeServiceWebhookTestCase(APITestCase):
    """Test suite for StripeService webhook methods"""

    @patch("stripe.Webhook.construct_event")
    def test_verify_webhook_signature_success(self, mock_construct):
        """Test successful webhook signature verification"""
        mock_event = {"type": "checkout.session.completed", "data": {}}
        mock_construct.return_value = mock_event

        payload = b'{"test": "data"}'
        signature = "test_signature"
        secret = "whsec_test"

        result = StripeService.verify_webhook_signature(payload, signature, secret)

        self.assertIsNotNone(result)
        self.assertEqual(result["type"], "checkout.session.completed")
        mock_construct.assert_called_once_with(payload, signature, secret)

    @patch("stripe.Webhook.construct_event")
    def test_verify_webhook_signature_invalid(self, mock_construct):
        """Test webhook signature verification with invalid signature"""
        mock_construct.side_effect = stripe.error.SignatureVerificationError(
            "Invalid signature", "sig_header"
        )

        result = StripeService.verify_webhook_signature(
            b'{"test": "data"}', "invalid_signature", "whsec_test"
        )

        self.assertIsNone(result)

    @patch("stripe.Webhook.construct_event")
    def test_verify_webhook_signature_value_error(self, mock_construct):
        """Test webhook signature verification with value error"""
        mock_construct.side_effect = ValueError("Invalid payload")

        result = StripeService.verify_webhook_signature(
            b"invalid", "signature", "whsec_test"
        )

        self.assertIsNone(result)

    @patch("stripe.Event.list")
    def test_get_webhook_events_success(self, mock_list):
        """Test getting webhook events list"""
        mock_events = Mock()
        mock_events.data = [
            {"id": "evt_1", "type": "payment_intent.succeeded"},
            {"id": "evt_2", "type": "checkout.session.completed"},
        ]
        mock_list.return_value = mock_events

        result = StripeService.get_webhook_events()

        self.assertEqual(len(result), 2)
        self.assertEqual(result[0]["id"], "evt_1")
        mock_list.assert_called_once_with(limit=10)

    @patch("stripe.Event.list")
    def test_get_webhook_events_error(self, mock_list):
        """Test getting webhook events with Stripe error"""
        mock_list.side_effect = stripe.error.StripeError("API Error")

        result = StripeService.get_webhook_events()

        self.assertEqual(result, [])


class StripeServiceExpireSessionTestCase(APITestCase):
    """Test suite for StripeService.expire_session"""

    @patch("payments.stripe_service.StripeService.retrieve_checkout_session")
    def test_expire_session_not_found(self, mock_retrieve):
        """Test expire_session when session not found"""
        mock_retrieve.return_value = None

        result = StripeService.expire_session("sess_invalid")

        self.assertFalse(result["success"])
        self.assertIn("not found", result["error"])

    @patch("payments.stripe_service.StripeService.retrieve_checkout_session")
    def test_expire_session_already_expired(self, mock_retrieve):
        """Test expire_session when session already expired"""
        mock_session = Mock()
        mock_session.status = "expired"
        mock_retrieve.return_value = mock_session

        result = StripeService.expire_session("sess_expired")

        self.assertTrue(result["success"])
        self.assertIn("already expired", result["message"])

    @patch("payments.stripe_service.StripeService.retrieve_checkout_session")
    def test_expire_session_cannot_manually_expire(self, mock_retrieve):
        """Test expire_session returns message about manual expiration"""
        mock_session = Mock()
        mock_session.status = "open"
        mock_retrieve.return_value = mock_session

        result = StripeService.expire_session("sess_open")

        self.assertFalse(result["success"])
        self.assertIn("Cannot manually expire", result["error"])

    @patch("payments.stripe_service.StripeService.retrieve_checkout_session")
    def test_expire_session_exception(self, mock_retrieve):
        """Test expire_session handles exceptions"""
        mock_retrieve.side_effect = Exception("Unexpected error")

        result = StripeService.expire_session("sess_123")

        self.assertFalse(result["success"])
        self.assertIn("error", result)


class StripeServiceCreateTestSessionsTestCase(APITestCase):
    """Test suite for StripeService.create_test_sessions"""

    @patch("stripe.checkout.Session.create")
    def test_create_test_sessions_success(self, mock_create):
        """Test creating test sessions"""
        mock_session_1 = Mock()
        mock_session_1.id = "sess_test_1"
        mock_session_1.url = "https://checkout.stripe.com/test1"

        mock_session_2 = Mock()
        mock_session_2.id = "sess_test_2"
        mock_session_2.url = "https://checkout.stripe.com/test2"

        mock_session_3 = Mock()
        mock_session_3.id = "sess_test_3"
        mock_session_3.url = "https://checkout.stripe.com/test3"

        mock_create.side_effect = [mock_session_1, mock_session_2, mock_session_3]

        result = StripeService.create_test_sessions()

        self.assertEqual(len(result), 3)
        self.assertEqual(result[0]["session_id"], "sess_test_1")
        self.assertEqual(mock_create.call_count, 3)

    @patch("stripe.checkout.Session.create")
    def test_create_test_sessions_error(self, mock_create):
        """Test create_test_sessions handles errors"""
        mock_create.side_effect = stripe.error.StripeError("API Error")

        result = StripeService.create_test_sessions()

        self.assertEqual(result, [])

    def tearDown(self):
        """Clean up test data"""
        Payment.objects.all().delete()
        Borrowing.objects.all().delete()
        Book.objects.all().delete()
        User.objects.all().delete()
