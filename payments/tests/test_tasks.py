from decimal import Decimal
from datetime import timedelta
from unittest.mock import patch, Mock, MagicMock

from django.contrib.auth import get_user_model
from django.utils import timezone
from rest_framework.test import APITestCase

from borrowings.models import Borrowing
from payments.models import Payment
from payments.tasks import (
    check_expired_stripe_sessions,
    expire_payment_session,
    cleanup_old_expired_payments,
)
from books.models import Book
from core.utils.timezone_utils import kyiv_now, KYIV_TZ

User = get_user_model()


class CheckExpiredStripeSessionsTestCase(APITestCase):
    """Test suite for check_expired_stripe_sessions task"""

    def setUp(self):
        """Set up test data"""
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

    @patch("payments.tasks.StripeService.retrieve_checkout_session")
    def test_check_expired_sessions_no_payments(self, mock_retrieve):
        """Test task when no payments exist"""
        # mock_task = Mock()
        # mock_task.request.id = "test_task_id"

        result = check_expired_stripe_sessions()

        self.assertEqual(result["status"], "completed")
        self.assertEqual(result["total_checked"], 0)
        self.assertEqual(result["expired_count"], 0)

    @patch("payments.tasks.StripeService.retrieve_checkout_session")
    def test_check_expired_sessions_expired_by_time(self, mock_retrieve):
        """Test task marks payment expired when session_expires_at passed"""
        # Create payment with expired session
        payment = Payment.objects.create(
            borrowing=self.borrowing,
            type="payment",
            status="pending",
            money_to_pay=Decimal("10.00"),
            session_id="sess_expired",
            session_url="https://stripe.com/session",
            session_expires_at=kyiv_now() - timedelta(hours=1),
        )

        mock_session = Mock()
        mock_session.status = "expired"
        mock_session.payment_status = "unpaid"
        mock_retrieve.return_value = mock_session

        # mock_task = Mock()
        # mock_task.request.id = "test_task_id"

        result = check_expired_stripe_sessions()

        self.assertEqual(result["expired_count"], 1)
        payment.refresh_from_db()
        self.assertEqual(payment.status, "expired")

    @patch("payments.tasks.StripeService.retrieve_checkout_session")
    def test_check_expired_sessions_cannot_retrieve_from_stripe(self, mock_retrieve):
        """Test marks payment expired when Stripe session cannot be retrieved"""
        payment = Payment.objects.create(
            borrowing=self.borrowing,
            type="payment",
            status="pending",
            money_to_pay=Decimal("10.00"),
            session_id="sess_unretrievable",
            session_url="https://stripe.com/session",
            session_expires_at=kyiv_now() - timedelta(hours=1),
        )

        mock_retrieve.return_value = None

        result = check_expired_stripe_sessions()

        self.assertEqual(result["expired_count"], 1)
        payment.refresh_from_db()
        self.assertEqual(payment.status, "expired")

    @patch("payments.tasks.StripeService.retrieve_checkout_session")
    def test_check_expired_sessions_stripe_confirms_expired(self, mock_retrieve):
        """Test marks payment expired when Stripe confirms expiration"""
        payment = Payment.objects.create(
            borrowing=self.borrowing,
            type="payment",
            status="pending",
            money_to_pay=Decimal("10.00"),
            session_id="sess_expired",
            session_url="https://stripe.com/session",
            session_expires_at=kyiv_now() - timedelta(hours=1),
        )

        mock_session = Mock()
        mock_session.status = "expired"
        mock_session.payment_status = "unpaid"
        mock_retrieve.return_value = mock_session

        # mock_task = Mock()
        # mock_task.request.id = "test_task_id"

        result = check_expired_stripe_sessions()

        self.assertEqual(result["expired_count"], 1)
        payment.refresh_from_db()
        self.assertEqual(payment.status, "expired")

    @patch("payments.tasks.StripeService.retrieve_checkout_session")
    def test_check_expired_sessions_paid_in_stripe(self, mock_retrieve):
        """Test updates payment to paid when Stripe shows it's paid"""
        payment = Payment.objects.create(
            borrowing=self.borrowing,
            type="payment",
            status="pending",
            money_to_pay=Decimal("10.00"),
            session_id="sess_paid",
            session_url="https://stripe.com/session",
            session_expires_at=kyiv_now() - timedelta(hours=1),
        )

        mock_session = Mock()
        mock_session.status = "complete"
        mock_session.payment_status = "paid"
        mock_retrieve.return_value = mock_session

        # mock_task = Mock()
        # mock_task.request.id = "test_task_id"

        result = check_expired_stripe_sessions()

        self.assertEqual(result["still_valid_count"], 1)
        payment.refresh_from_db()
        self.assertEqual(payment.status, "paid")

    @patch("payments.tasks.StripeService.retrieve_checkout_session")
    def test_check_expired_sessions_still_open(self, mock_retrieve):
        """Test extends expiration when session still open"""
        payment = Payment.objects.create(
            borrowing=self.borrowing,
            type="payment",
            status="pending",
            money_to_pay=Decimal("10.00"),
            session_id="sess_open",
            session_url="https://stripe.com/session",
            session_expires_at=kyiv_now() - timedelta(minutes=5),
        )

        original_expiry = payment.session_expires_at

        mock_session = Mock()
        mock_session.status = "open"
        mock_session.payment_status = "unpaid"
        mock_retrieve.return_value = mock_session

        # mock_task = Mock()
        # mock_task.request.id = "test_task_id"

        result = check_expired_stripe_sessions()

        self.assertEqual(result["still_valid_count"], 1)
        payment.refresh_from_db()
        self.assertEqual(payment.status, "pending")
        self.assertGreater(payment.session_expires_at, original_expiry)

    @patch("payments.tasks.StripeService.retrieve_checkout_session")
    def test_check_expired_sessions_unknown_status(self, mock_retrieve):
        """Test marks expired when Stripe status is unknown"""
        payment = Payment.objects.create(
            borrowing=self.borrowing,
            type="payment",
            status="pending",
            money_to_pay=Decimal("10.00"),
            session_id="sess_unknown",
            session_url="https://stripe.com/session",
            session_expires_at=kyiv_now() - timedelta(hours=1),
        )

        mock_session = Mock()
        mock_session.status = "unknown_status"
        mock_session.payment_status = "unpaid"
        mock_retrieve.return_value = mock_session

        # mock_task = Mock()
        # mock_task.request.id = "test_task_id"

        result = check_expired_stripe_sessions()

        self.assertEqual(result["expired_count"], 1)
        payment.refresh_from_db()
        self.assertEqual(payment.status, "expired")

    @patch("payments.tasks.StripeService.retrieve_checkout_session")
    def test_check_expired_sessions_multiple_payments(self, mock_retrieve):
        """Test processes multiple payments correctly"""
        # Create expired payment
        payment1 = Payment.objects.create(
            borrowing=self.borrowing,
            type="payment",
            status="pending",
            money_to_pay=Decimal("10.00"),
            session_id="sess_expired",
            session_url="https://stripe.com/session1",
            session_expires_at=kyiv_now() - timedelta(hours=1),
        )

        # Create another borrowing for second payment
        book2 = Book.objects.create(
            title="Test Book 2",
            author="Test Author",
            cover="soft",
            inventory=3,
            daily_fee=Decimal("1.50"),
        )

        borrowing2 = Borrowing.objects.create(
            user=self.user,
            book=book2,
            borrow_date=kyiv_now().date(),
            expected_return_date=(kyiv_now() + timedelta(days=5)).date(),
        )

        payment2 = Payment.objects.create(
            borrowing=borrowing2,
            type="payment",
            status="pending",
            money_to_pay=Decimal("7.50"),
            session_id="sess_paid",
            session_url="https://stripe.com/session2",
            session_expires_at=kyiv_now() - timedelta(hours=1),
        )

        def mock_retrieve_side_effect(session_id):
            if session_id == "sess_expired":
                session = Mock()
                session.status = "expired"
                session.payment_status = "unpaid"
                return session
            elif session_id == "sess_paid":
                session = Mock()
                session.status = "complete"
                session.payment_status = "paid"
                return session

        mock_retrieve.side_effect = mock_retrieve_side_effect

        # mock_task = Mock()
        # mock_task.request.id = "test_task_id"

        result = check_expired_stripe_sessions()

        self.assertEqual(result["expired_count"], 1)
        self.assertEqual(result["still_valid_count"], 1)

        payment1.refresh_from_db()
        payment2.refresh_from_db()
        self.assertEqual(payment1.status, "expired")
        self.assertEqual(payment2.status, "paid")

    @patch("payments.tasks.StripeService.retrieve_checkout_session")
    def test_check_expired_sessions_handles_errors(self, mock_retrieve):
        """Test handles errors gracefully for individual payments"""
        payment = Payment.objects.create(
            borrowing=self.borrowing,
            type="payment",
            status="pending",
            money_to_pay=Decimal("10.00"),
            session_id="sess_error",
            session_url="https://stripe.com/session",
            session_expires_at=kyiv_now() - timedelta(hours=1),
        )

        mock_retrieve.side_effect = Exception("Stripe API error")

        # mock_task = Mock()
        # mock_task.request.id = "test_task_id"

        result = check_expired_stripe_sessions()

        self.assertEqual(result["error_count"], 1)
        self.assertEqual(len(result["errors"]), 1)
        self.assertIn("Stripe API error", result["errors"][0])

    @patch("payments.tasks.StripeService.retrieve_checkout_session")
    def test_check_expired_sessions_ignores_non_pending(self, mock_retrieve):
        """Test only processes pending payments"""
        # Create paid payment with expired time
        Payment.objects.create(
            borrowing=self.borrowing,
            type="payment",
            status="paid",
            money_to_pay=Decimal("10.00"),
            session_id="sess_paid",
            session_url="https://stripe.com/session",
            session_expires_at=kyiv_now() - timedelta(hours=1),
        )

        # Create already expired payment
        Payment.objects.create(
            borrowing=self.borrowing,
            type="fine",
            status="expired",
            money_to_pay=Decimal("5.00"),
            session_id="sess_expired",
            session_url="https://stripe.com/session2",
            session_expires_at=kyiv_now() - timedelta(hours=2),
        )

        # mock_task = Mock()
        # mock_task.request.id = "test_task_id"

        result = check_expired_stripe_sessions()

        # Should not process any payments
        self.assertEqual(result["total_checked"], 0)
        mock_retrieve.assert_not_called()

    @patch("payments.tasks.StripeService.retrieve_checkout_session")
    def test_check_expired_sessions_ignores_future_expiry(self, mock_retrieve):
        """Test ignores payments with future expiry time"""
        Payment.objects.create(
            borrowing=self.borrowing,
            type="payment",
            status="pending",
            money_to_pay=Decimal("10.00"),
            session_id="sess_future",
            session_url="https://stripe.com/session",
            session_expires_at=kyiv_now() + timedelta(hours=23),
        )

        # mock_task = Mock()
        # mock_task.request.id = "test_task_id"

        result = check_expired_stripe_sessions()

        # Should not process this payment
        self.assertEqual(result["total_checked"], 0)
        mock_retrieve.assert_not_called()

    @patch("payments.tasks.check_expired_stripe_sessions.retry")
    @patch("payments.tasks.Payment.objects.filter")
    def test_check_expired_sessions_task_retry_on_error(self, mock_filter, mock_retry):
        """Test task retries on unexpected errors"""
        # Make the queryset fail to trigger task-level exception
        mock_filter.side_effect = Exception("Database error")
        mock_retry.side_effect = Exception("Retry called")

        with self.assertRaises(Exception):
            check_expired_stripe_sessions()

        # Verify retry was attempted
        mock_retry.assert_called_once()


class ExpirePaymentSessionTestCase(APITestCase):
    """Test suite for expire_payment_session task"""

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

    def test_expire_payment_session_not_found(self):
        """Test task when payment doesn't exist"""
        result = expire_payment_session(99999)

        self.assertEqual(result["status"], "error")
        self.assertIn("not found", result["message"])

    @patch("payments.tasks.StripeService.retrieve_checkout_session")
    def test_expire_payment_session_success(self, mock_retrieve):
        """Test successfully expires payment session"""
        payment = Payment.objects.create(
            borrowing=self.borrowing,
            type="payment",
            status="pending",
            money_to_pay=Decimal("10.00"),
            session_id="sess_test",
            session_url="https://stripe.com/session",
        )

        mock_session = Mock()
        mock_session.payment_status = "unpaid"
        mock_retrieve.return_value = mock_session

        result = expire_payment_session(payment.id)

        self.assertEqual(result["status"], "expired")
        payment.refresh_from_db()
        self.assertEqual(payment.status, "expired")

    def test_expire_payment_session_already_paid(self):
        """Test skips already paid payment"""
        payment = Payment.objects.create(
            borrowing=self.borrowing,
            type="payment",
            status="paid",
            money_to_pay=Decimal("10.00"),
            session_id="sess_paid",
            session_url="https://stripe.com/session",
        )

        result = expire_payment_session(payment.id)

        self.assertEqual(result["status"], "skipped")
        self.assertIn("already completed", result["reason"])

    def test_expire_payment_session_already_expired(self):
        """Test skips already expired payment"""
        payment = Payment.objects.create(
            borrowing=self.borrowing,
            type="payment",
            status="expired",
            money_to_pay=Decimal("10.00"),
        )

        result = expire_payment_session(payment.id)

        self.assertEqual(result["status"], "skipped")
        self.assertIn("already expired", result["reason"])

    @patch("payments.tasks.StripeService.retrieve_checkout_session")
    def test_expire_payment_session_actually_paid_in_stripe(self, mock_retrieve):
        """Test updates to paid when Stripe shows payment is paid"""
        payment = Payment.objects.create(
            borrowing=self.borrowing,
            type="payment",
            status="pending",
            money_to_pay=Decimal("10.00"),
            session_id="sess_paid",
            session_url="https://stripe.com/session",
        )

        mock_session = Mock()
        mock_session.payment_status = "paid"
        mock_retrieve.return_value = mock_session

        result = expire_payment_session(payment.id)

        self.assertEqual(result["status"], "updated_to_paid")
        payment.refresh_from_db()
        self.assertEqual(payment.status, "paid")

    @patch("payments.tasks.StripeService.retrieve_checkout_session")
    def test_expire_payment_session_no_session_id(self, mock_retrieve):
        """Test expires payment without session_id"""
        payment = Payment.objects.create(
            borrowing=self.borrowing,
            type="payment",
            status="pending",
            money_to_pay=Decimal("10.00"),
        )

        result = expire_payment_session(payment.id)

        self.assertEqual(result["status"], "expired")
        payment.refresh_from_db()
        self.assertEqual(payment.status, "expired")
        mock_retrieve.assert_not_called()

    @patch("payments.tasks.StripeService.retrieve_checkout_session")
    def test_expire_payment_session_stripe_error(self, mock_retrieve):
        """Test handles Stripe retrieval errors"""
        payment = Payment.objects.create(
            borrowing=self.borrowing,
            type="payment",
            status="pending",
            money_to_pay=Decimal("10.00"),
            session_id="sess_error",
            session_url="https://stripe.com/session",
        )

        mock_retrieve.return_value = None

        result = expire_payment_session(payment.id)

        self.assertEqual(result["status"], "expired")
        payment.refresh_from_db()
        self.assertEqual(payment.status, "expired")


class CleanupOldExpiredPaymentsTestCase(APITestCase):
    """Test suite for cleanup_old_expired_payments task"""

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

    def test_cleanup_no_old_payments(self):
        """Test cleanup when no old expired payments exist"""
        result = cleanup_old_expired_payments()

        self.assertEqual(result["status"], "completed")
        self.assertEqual(result["deleted_count"], 0)

    def test_cleanup_old_expired_payments(self):
        """Test deletes old expired payments"""
        # Create old expired payment (35 days old)
        old_payment = Payment.objects.create(
            borrowing=self.borrowing,
            type="payment",
            status="expired",
            money_to_pay=Decimal("10.00"),
        )

        # Manually set created_at to 35 days ago
        old_date = kyiv_now() - timedelta(days=35)
        Payment.objects.filter(id=old_payment.id).update(created_at=old_date)

        result = cleanup_old_expired_payments()

        self.assertEqual(result["status"], "completed")
        self.assertEqual(result["deleted_count"], 1)
        self.assertFalse(Payment.objects.filter(id=old_payment.id).exists())

    def test_cleanup_keeps_recent_expired_payments(self):
        """Test doesn't delete recent expired payments"""
        # Create recent expired payment (20 days old)
        recent_payment = Payment.objects.create(
            borrowing=self.borrowing,
            type="payment",
            status="expired",
            money_to_pay=Decimal("10.00"),
        )

        recent_date = kyiv_now() - timedelta(days=20)
        Payment.objects.filter(id=recent_payment.id).update(created_at=recent_date)

        result = cleanup_old_expired_payments()

        self.assertEqual(result["deleted_count"], 0)
        self.assertTrue(Payment.objects.filter(id=recent_payment.id).exists())

    def test_cleanup_keeps_non_expired_payments(self):
        """Test doesn't delete non-expired payments even if old"""
        # Create old paid payment
        old_paid = Payment.objects.create(
            borrowing=self.borrowing,
            type="payment",
            status="paid",
            money_to_pay=Decimal("10.00"),
            session_id="sess_paid",
            session_url="https://stripe.com/session",
        )

        old_date = kyiv_now() - timedelta(days=35)
        Payment.objects.filter(id=old_paid.id).update(created_at=old_date)

        result = cleanup_old_expired_payments()

        self.assertEqual(result["deleted_count"], 0)
        self.assertTrue(Payment.objects.filter(id=old_paid.id).exists())

    def test_cleanup_multiple_old_expired_payments(self):
        """Test deletes multiple old expired payments"""
        # Create multiple old expired payments
        for i in range(3):
            payment = Payment.objects.create(
                borrowing=self.borrowing,
                type="payment" if i % 2 == 0 else "fine",
                status="expired",
                money_to_pay=Decimal("10.00"),
            )
            old_date = kyiv_now() - timedelta(days=35 + i)
            Payment.objects.filter(id=payment.id).update(created_at=old_date)

        result = cleanup_old_expired_payments()

        self.assertEqual(result["status"], "completed")
        self.assertEqual(result["deleted_count"], 3)

    @patch("payments.tasks.Payment.objects.filter")
    def test_cleanup_handles_errors(self, mock_filter):
        """Test cleanup handles errors gracefully"""
        mock_filter.side_effect = Exception("Database error")

        result = cleanup_old_expired_payments()

        self.assertEqual(result["status"], "error")
        self.assertIn("Database error", result["message"])

    def tearDown(self):
        """Clean up test data"""
        Payment.objects.all().delete()
        Borrowing.objects.all().delete()
        Book.objects.all().delete()
        User.objects.all().delete()
