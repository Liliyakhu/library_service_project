from decimal import Decimal
from datetime import timedelta
from unittest.mock import patch, Mock, MagicMock

from django.contrib.auth import get_user_model
from django.test import RequestFactory
from rest_framework.test import APITestCase, APIClient

from borrowings.models import Borrowing
from payments.models import Payment
from payments.services import (
    create_payment,
    create_payment_for_borrowing,
    create_fine_payment_for_borrowing,
    get_or_create_fine_payment,
    get_unpaid_payments_for_user,
    has_pending_payments,
    mark_payment_as_paid,
)
from books.models import Book
from core.utils.timezone_utils import kyiv_now

User = get_user_model()


class CreatePaymentTestCase(APITestCase):
    """Test suite for create_payment function"""

    def setUp(self):
        """Set up test data"""
        self.factory = RequestFactory()
        self.client = APIClient()

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

        # Create overdue borrowing
        self.overdue_borrowing = Borrowing.objects.create(
            user=self.user,
            book=self.book,
            borrow_date=(kyiv_now() - timedelta(days=10)).date(),
            expected_return_date=(kyiv_now() - timedelta(days=3)).date(),
            actual_return_date=kyiv_now().date(),
        )

    def test_create_payment_basic(self):
        """Test basic payment creation without Stripe session"""
        payment = create_payment(
            borrowing=self.borrowing, payment_type="payment", create_session=False
        )

        self.assertIsNotNone(payment)
        self.assertEqual(payment.borrowing, self.borrowing)
        self.assertEqual(payment.type, "payment")
        self.assertEqual(payment.status, "pending")
        self.assertEqual(payment.money_to_pay, self.borrowing.payment_fee)
        self.assertIsNone(payment.session_id)
        self.assertIsNone(payment.session_url)

    def test_create_payment_fine_type(self):
        """Test creating fine payment"""
        payment = create_payment(
            borrowing=self.overdue_borrowing, payment_type="fine", create_session=False
        )

        self.assertEqual(payment.type, "fine")
        self.assertEqual(payment.money_to_pay, self.overdue_borrowing.fine_fee)
        self.assertGreater(payment.money_to_pay, Decimal("0"))

    def test_create_payment_invalid_type(self):
        """Test creating payment with invalid type"""
        with self.assertRaises(ValueError) as context:
            create_payment(
                borrowing=self.borrowing,
                payment_type="invalid_type",
                create_session=False,
            )

        self.assertIn("Invalid payment type", str(context.exception))

    def test_create_payment_fine_for_non_overdue(self):
        """Test creating fine payment for non-overdue borrowing fails"""
        with self.assertRaises(ValueError) as context:
            create_payment(
                borrowing=self.borrowing, payment_type="fine", create_session=False
            )

        self.assertIn("non-overdue", str(context.exception))

    def test_create_payment_returns_existing_pending(self):
        """Test that existing pending payment is returned"""
        # Create first payment
        first_payment = create_payment(
            borrowing=self.borrowing, payment_type="payment", create_session=False
        )

        # Try to create another
        second_payment = create_payment(
            borrowing=self.borrowing, payment_type="payment", create_session=False
        )

        self.assertEqual(first_payment.id, second_payment.id)
        # Verify only one payment exists
        self.assertEqual(
            Payment.objects.filter(borrowing=self.borrowing, type="payment").count(), 1
        )

    def test_create_payment_fails_if_paid_exists(self):
        """Test that creating payment fails if paid payment exists"""
        # Create paid payment
        Payment.objects.create(
            borrowing=self.borrowing,
            type="payment",
            status="paid",
            money_to_pay=Decimal("10.00"),
            session_id="sess_paid",
            session_url="https://stripe.com/session",
        )

        with self.assertRaises(ValueError) as context:
            create_payment(
                borrowing=self.borrowing, payment_type="payment", create_session=False
            )

        self.assertIn("paid", str(context.exception).lower())

    @patch("payments.services.StripeService.create_checkout_session")
    def test_create_payment_with_stripe_session_success(self, mock_stripe):
        """Test creating payment with successful Stripe session"""
        mock_stripe.return_value = {
            "success": True,
            "session_id": "sess_test_123",
            "session_url": "https://stripe.com/checkout/test",
        }

        request = self.factory.post("/payments/")
        request.user = self.user

        payment = create_payment(
            borrowing=self.borrowing,
            payment_type="payment",
            request=request,
            create_session=True,
        )

        self.assertEqual(payment.session_id, "sess_test_123")
        self.assertEqual(payment.session_url, "https://stripe.com/checkout/test")
        mock_stripe.assert_called_once()

    @patch("payments.services.StripeService.create_checkout_session")
    def test_create_payment_with_stripe_session_failure(self, mock_stripe):
        """Test creating payment with Stripe session failure"""
        mock_stripe.return_value = {"success": False, "error": "Stripe API error"}

        request = self.factory.post("/payments/")
        request.user = self.user

        with self.assertRaises(Exception) as context:
            create_payment(
                borrowing=self.borrowing,
                payment_type="payment",
                request=request,
                create_session=True,
            )

        self.assertIn("Stripe session", str(context.exception))

        # Verify payment was cleaned up
        self.assertFalse(
            Payment.objects.filter(borrowing=self.borrowing, type="payment").exists()
        )

    @patch("payments.services.StripeService.create_checkout_session")
    def test_create_payment_stripe_exception_cleanup(self, mock_stripe):
        """Test that payment is cleaned up if Stripe raises exception"""
        mock_stripe.side_effect = Exception("Stripe connection error")

        request = self.factory.post("/payments/")
        request.user = self.user

        with self.assertRaises(Exception):
            create_payment(
                borrowing=self.borrowing,
                payment_type="payment",
                request=request,
                create_session=True,
            )

        # Verify payment was cleaned up
        self.assertFalse(
            Payment.objects.filter(borrowing=self.borrowing, type="payment").exists()
        )


class CreatePaymentWrappersTestCase(APITestCase):
    """Test suite for create_payment wrapper functions"""

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

        self.overdue_borrowing = Borrowing.objects.create(
            user=self.user,
            book=self.book,
            borrow_date=(kyiv_now() - timedelta(days=10)).date(),
            expected_return_date=(kyiv_now() - timedelta(days=3)).date(),
            actual_return_date=kyiv_now().date(),
        )

    @patch("payments.services.StripeService.create_checkout_session")
    def test_create_payment_for_borrowing(self, mock_stripe):
        """Test create_payment_for_borrowing wrapper"""
        mock_stripe.return_value = {
            "success": True,
            "session_id": "sess_123",
            "session_url": "https://stripe.com/checkout",
        }

        request = self.factory.post("/payments/")
        request.user = self.user

        payment = create_payment_for_borrowing(self.borrowing, request)

        self.assertEqual(payment.type, "payment")
        self.assertIsNotNone(payment.session_id)

    @patch("payments.services.StripeService.create_checkout_session")
    def test_create_fine_payment_for_borrowing(self, mock_stripe):
        """Test create_fine_payment_for_borrowing wrapper"""
        mock_stripe.return_value = {
            "success": True,
            "session_id": "sess_fine",
            "session_url": "https://stripe.com/checkout/fine",
        }

        request = self.factory.post("/payments/")
        request.user = self.user

        payment = create_fine_payment_for_borrowing(self.overdue_borrowing, request)

        self.assertEqual(payment.type, "fine")
        self.assertIsNotNone(payment.session_id)


class GetOrCreateFinePaymentTestCase(APITestCase):
    """Test suite for get_or_create_fine_payment function"""

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

        self.normal_borrowing = Borrowing.objects.create(
            user=self.user,
            book=self.book,
            borrow_date=kyiv_now().date(),
            expected_return_date=(kyiv_now() + timedelta(days=7)).date(),
        )

        self.overdue_borrowing = Borrowing.objects.create(
            user=self.user,
            book=self.book,
            borrow_date=(kyiv_now() - timedelta(days=10)).date(),
            expected_return_date=(kyiv_now() - timedelta(days=3)).date(),
            actual_return_date=kyiv_now().date(),
        )

    def test_get_or_create_fine_payment_non_overdue(self):
        """Test raises ValueError for non-overdue borrowing"""
        with self.assertRaisesMessage(ValueError, "Borrowing is not overdue"):
            get_or_create_fine_payment(self.normal_borrowing)

    @patch("payments.services.create_fine_payment_for_borrowing")
    def test_get_or_create_fine_payment_creates_new(self, mock_create):
        """Test creates new fine payment if none exists"""
        mock_payment = Mock(spec=Payment)
        mock_create.return_value = mock_payment

        request = self.factory.post("/payments/")
        result = get_or_create_fine_payment(self.overdue_borrowing, request)

        self.assertEqual(result, mock_payment)
        mock_create.assert_called_once_with(self.overdue_borrowing, request)

    def test_get_or_create_fine_payment_returns_existing(self):
        """Test returns existing fine payment"""
        existing_fine = Payment.objects.create(
            borrowing=self.overdue_borrowing,
            type="fine",
            status="pending",
            money_to_pay=Decimal("5.00"),
        )

        result = get_or_create_fine_payment(self.overdue_borrowing)

        self.assertEqual(result.id, existing_fine.id)

    def test_get_or_create_fine_payment_returns_paid_fine(self):
        """Test returns existing paid fine payment"""
        paid_fine = Payment.objects.create(
            borrowing=self.overdue_borrowing,
            type="fine",
            status="paid",
            money_to_pay=Decimal("5.00"),
            session_id="sess_paid",
            session_url="https://stripe.com/session",
        )

        result = get_or_create_fine_payment(self.overdue_borrowing)

        self.assertEqual(result.id, paid_fine.id)


class GetUnpaidPaymentsTestCase(APITestCase):
    """Test suite for get_unpaid_payments_for_user function"""

    def setUp(self):
        """Set up test data"""
        self.user1 = User.objects.create_user(
            email="user1@example.com", password="testpass123"
        )

        self.user2 = User.objects.create_user(
            email="user2@example.com", password="testpass123"
        )

        self.book1 = Book.objects.create(
            title="Test Book 1",
            author="Test Author",
            cover="hard",
            inventory=5,
            daily_fee=Decimal("2.00"),
        )

        self.book2 = Book.objects.create(
            title="Test Book 2",
            author="Test Author",
            cover="soft",
            inventory=5,
            daily_fee=Decimal("1.50"),
        )

        # Create borrowings for user1 with different books
        self.borrowing1 = Borrowing.objects.create(
            user=self.user1,
            book=self.book1,
            borrow_date=kyiv_now().date(),
            expected_return_date=(kyiv_now() + timedelta(days=7)).date(),
        )

        self.borrowing2 = Borrowing.objects.create(
            user=self.user1,
            book=self.book2,
            borrow_date=kyiv_now().date(),
            expected_return_date=(kyiv_now() + timedelta(days=7)).date(),
        )

        # Create borrowing for user2
        self.borrowing3 = Borrowing.objects.create(
            user=self.user2,
            book=self.book1,
            borrow_date=kyiv_now().date(),
            expected_return_date=(kyiv_now() + timedelta(days=7)).date(),
        )

    def test_get_unpaid_payments_empty(self):
        """Test returns empty queryset when no payments"""
        payments = get_unpaid_payments_for_user(self.user1)

        self.assertEqual(payments.count(), 0)

    def test_get_unpaid_payments_pending(self):
        """Test returns pending payments"""
        Payment.objects.create(
            borrowing=self.borrowing1,
            type="payment",
            status="pending",
            money_to_pay=Decimal("10.00"),
        )

        payments = get_unpaid_payments_for_user(self.user1)

        self.assertEqual(payments.count(), 1)
        self.assertEqual(payments.first().status, "pending")

    def test_get_unpaid_payments_expired(self):
        """Test returns expired payments"""
        Payment.objects.create(
            borrowing=self.borrowing1,
            type="payment",
            status="expired",
            money_to_pay=Decimal("10.00"),
        )

        payments = get_unpaid_payments_for_user(self.user1)

        self.assertEqual(payments.count(), 1)
        self.assertEqual(payments.first().status, "expired")

    def test_get_unpaid_payments_excludes_paid(self):
        """Test excludes paid payments"""
        Payment.objects.create(
            borrowing=self.borrowing1,
            type="payment",
            status="paid",
            money_to_pay=Decimal("10.00"),
            session_id="sess_paid",
            session_url="https://stripe.com/session",
        )

        payments = get_unpaid_payments_for_user(self.user1)

        self.assertEqual(payments.count(), 0)

    def test_get_unpaid_payments_multiple_statuses(self):
        """Test returns both pending and expired payments"""
        Payment.objects.create(
            borrowing=self.borrowing1,
            type="payment",
            status="pending",
            money_to_pay=Decimal("10.00"),
        )

        Payment.objects.create(
            borrowing=self.borrowing2,
            type="payment",
            status="expired",
            money_to_pay=Decimal("15.00"),
        )

        payments = get_unpaid_payments_for_user(self.user1)

        self.assertEqual(payments.count(), 2)

    def test_get_unpaid_payments_user_isolation(self):
        """Test only returns payments for specified user"""
        Payment.objects.create(
            borrowing=self.borrowing1,
            type="payment",
            status="pending",
            money_to_pay=Decimal("10.00"),
        )

        Payment.objects.create(
            borrowing=self.borrowing3,
            type="payment",
            status="pending",
            money_to_pay=Decimal("10.00"),
        )

        payments = get_unpaid_payments_for_user(self.user1)

        self.assertEqual(payments.count(), 1)
        self.assertEqual(payments.first().borrowing.user, self.user1)


class HasPendingPaymentsTestCase(APITestCase):
    """Test suite for has_pending_payments function"""

    def setUp(self):
        """Set up test data"""
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

    def test_has_pending_payments_false_no_payments(self):
        """Test returns False when no payments"""
        result = has_pending_payments(self.user)

        self.assertFalse(result)

    def test_has_pending_payments_true(self):
        """Test returns True when pending payment exists"""
        Payment.objects.create(
            borrowing=self.borrowing,
            type="payment",
            status="pending",
            money_to_pay=Decimal("10.00"),
        )

        result = has_pending_payments(self.user)

        self.assertTrue(result)

    def test_has_pending_payments_false_expired(self):
        """Test returns False for expired payments"""
        Payment.objects.create(
            borrowing=self.borrowing,
            type="payment",
            status="expired",
            money_to_pay=Decimal("10.00"),
        )

        result = has_pending_payments(self.user)

        self.assertFalse(result)

    def test_has_pending_payments_false_paid(self):
        """Test returns False for paid payments"""
        Payment.objects.create(
            borrowing=self.borrowing,
            type="payment",
            status="paid",
            money_to_pay=Decimal("10.00"),
            session_id="sess_paid",
            session_url="https://stripe.com/session",
        )

        result = has_pending_payments(self.user)

        self.assertFalse(result)


class MarkPaymentAsPaidTestCase(APITestCase):
    """Test suite for mark_payment_as_paid function"""

    def setUp(self):
        """Set up test data"""
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

    def test_mark_payment_as_paid_from_pending(self):
        """Test marking pending payment as paid"""
        payment = Payment.objects.create(
            borrowing=self.borrowing,
            type="payment",
            status="pending",
            money_to_pay=Decimal("10.00"),
            session_id="sess_123",
            session_url="https://stripe.com/session",
        )

        result = mark_payment_as_paid(payment)

        result.refresh_from_db()
        self.assertEqual(result.status, "paid")

    def test_mark_payment_as_paid_from_expired(self):
        """Test marking expired payment as paid"""
        payment = Payment.objects.create(
            borrowing=self.borrowing,
            type="payment",
            status="expired",
            money_to_pay=Decimal("10.00"),
            session_id="sess_expired",
            session_url="https://stripe.com/session",
        )

        result = mark_payment_as_paid(payment)

        result.refresh_from_db()
        self.assertEqual(result.status, "paid")

    def test_mark_payment_as_paid_already_paid(self):
        """Test marking already paid payment (idempotent)"""
        payment = Payment.objects.create(
            borrowing=self.borrowing,
            type="payment",
            status="paid",
            money_to_pay=Decimal("10.00"),
            session_id="sess_paid",
            session_url="https://stripe.com/session",
        )

        result = mark_payment_as_paid(payment)

        self.assertEqual(result.status, "paid")
        # Should not raise error, just return the payment

    def test_mark_payment_as_paid_returns_payment(self):
        """Test function returns the payment object"""
        payment = Payment.objects.create(
            borrowing=self.borrowing,
            type="payment",
            status="pending",
            money_to_pay=Decimal("10.00"),
            session_id="sess_123",
            session_url="https://stripe.com/session",
        )

        result = mark_payment_as_paid(payment)

        self.assertIsInstance(result, Payment)
        self.assertEqual(result.id, payment.id)

    def tearDown(self):
        """Clean up test data"""
        Payment.objects.all().delete()
        Borrowing.objects.all().delete()
        Book.objects.all().delete()
        User.objects.all().delete()
