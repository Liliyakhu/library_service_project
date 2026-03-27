"""
Payment Views Test Suite

This module contains comprehensive tests for the Payment API endpoints.

Test Coverage:
- List/Filter payments
- Create payments with Stripe integration
- Retrieve payment details
- Update/Delete operations
- Custom actions (check_session, mark_paid, renew_session)
- Session status checking
- Bulk operations (staff only)
- Payment completion flows (success/cancel)
- Stripe synchronization
- Fine payments
- Permissions and authorization
- Edge cases and error handling
- Integration workflows

Notes:
- Uses separate books for different borrowings to avoid unique constraint violations
- Stripe API calls are mocked to prevent actual API requests
- Tests use Django REST Framework's APITestCase and APIClient
"""

from decimal import Decimal
from unittest.mock import patch, MagicMock
from django.urls import reverse
from django.utils import timezone
from rest_framework import status
from rest_framework.test import APITestCase, APIClient

from payments.models import Payment
from borrowings.models import Borrowing
from books.models import Book
from users.models import User
from core.utils.timezone_utils import kyiv_today, kyiv_now


class PaymentTestBase(APITestCase):
    """Base test class with common setup"""

    def setUp(self):
        """Set up test data"""
        self.client = APIClient()

        # Create users
        self.regular_user = User.objects.create_user(
            email="user@test.com",
            password="testpass123",
            first_name="Test",
            last_name="User",
        )

        self.staff_user = User.objects.create_user(
            email="staff@test.com",
            password="testpass123",
            first_name="Staff",
            last_name="User",
            is_staff=True,
        )

        # Create book
        self.book = Book.objects.create(
            title="Test Book",
            author="Test Author",
            cover="HARD",
            inventory=5,
            daily_fee=Decimal("1.50"),
        )

        # Create borrowing
        self.borrowing = Borrowing.objects.create(
            user=self.regular_user,
            book=self.book,
            borrow_date=kyiv_today(),
            expected_return_date=kyiv_today() + timezone.timedelta(days=7),
        )

        # Create payments
        self.payment = Payment.objects.create(
            borrowing=self.borrowing,
            type="payment",
            status="pending",
            money_to_pay=Decimal("10.50"),
            session_id="cs_test_123",
            session_url="https://checkout.stripe.com/test",
            session_expires_at=kyiv_now() + timezone.timedelta(hours=24),
        )

        self.expired_payment = Payment.objects.create(
            borrowing=self.borrowing,
            type="payment",
            status="expired",
            money_to_pay=Decimal("10.50"),
            session_id="cs_test_expired",
            session_url="https://checkout.stripe.com/expired",
            session_expires_at=kyiv_now() - timezone.timedelta(hours=1),
        )

        self.paid_payment = Payment.objects.create(
            borrowing=self.borrowing,
            type="payment",
            status="paid",
            money_to_pay=Decimal("10.50"),
            session_id="cs_test_paid",
            session_url="https://checkout.stripe.com/paid",
        )


# ==================== LIST TESTS ====================


class PaymentListTests(PaymentTestBase):
    """Test payment list endpoint"""

    def test_list_payments_unauthenticated(self):
        """Test that unauthenticated users cannot list payments"""
        url = reverse("payments:payments-list")
        response = self.client.get(url)

        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_list_payments_regular_user_sees_only_own(self):
        """Test that regular users see only their own payments"""
        self.client.force_authenticate(user=self.regular_user)
        url = reverse("payments:payments-list")

        response = self.client.get(url)

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.data["results"]), 3)  # 3 payments for this user

    def test_list_payments_staff_sees_all(self):
        """Test that staff users see all payments"""
        # Create another user's payment with a different book
        other_user = User.objects.create_user(
            email="other@test.com", password="pass123"
        )
        other_book = Book.objects.create(
            title="Other User Book",
            author="Other Author",
            cover="HARD",
            inventory=5,
            daily_fee=Decimal("1.50"),
        )
        other_borrowing = Borrowing.objects.create(
            user=other_user,
            book=other_book,
            borrow_date=kyiv_today(),
            expected_return_date=kyiv_today() + timezone.timedelta(days=7),
        )
        Payment.objects.create(
            borrowing=other_borrowing,
            type="payment",
            status="pending",
            money_to_pay=Decimal("5.00"),
        )

        self.client.force_authenticate(user=self.staff_user)
        url = reverse("payments:payments-list")

        response = self.client.get(url)

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertGreaterEqual(len(response.data["results"]), 4)  # At least 4 payments

    def test_list_payments_filter_by_status_pending(self):
        """Test filtering payments by pending status"""
        self.client.force_authenticate(user=self.regular_user)
        url = reverse("payments:payments-list")

        response = self.client.get(url, {"status": "pending"})

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.data["results"]), 1)
        self.assertEqual(response.data["results"][0]["status"], "pending")

    def test_list_payments_filter_by_status_paid(self):
        """Test filtering payments by paid status"""
        self.client.force_authenticate(user=self.regular_user)
        url = reverse("payments:payments-list")

        response = self.client.get(url, {"status": "paid"})

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.data["results"]), 1)
        self.assertEqual(response.data["results"][0]["status"], "paid")


# ==================== CREATE TESTS ====================


class PaymentCreateTests(PaymentTestBase):
    """Test payment creation endpoint"""

    def setUp(self):
        super().setUp()
        # Create a different book for new borrowing to avoid constraint violation
        self.new_book = Book.objects.create(
            title="New Test Book",
            author="New Author",
            cover="SOFT",
            inventory=10,
            daily_fee=Decimal("1.00"),
        )
        # Create a new borrowing without payments for creation tests
        self.new_borrowing = Borrowing.objects.create(
            user=self.regular_user,
            book=self.new_book,
            borrow_date=kyiv_today(),
            expected_return_date=kyiv_today() + timezone.timedelta(days=7),
        )

    @patch("payments.stripe_service.StripeService.create_checkout_session")
    def test_create_payment_success(self, mock_stripe):
        """Test successful payment creation"""
        mock_stripe.return_value = {
            "success": True,
            "session_id": "cs_test_new",
            "session_url": "https://checkout.stripe.com/new",
        }

        self.client.force_authenticate(user=self.regular_user)
        url = reverse("payments:payments-list")

        data = {"borrowing": self.new_borrowing.id, "type": "payment"}

        response = self.client.post(url, data)

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(response.data["session_id"], "cs_test_new")
        self.assertEqual(response.data["status"], "pending")
        self.assertTrue(Payment.objects.filter(session_id="cs_test_new").exists())

    @patch("payments.stripe_service.StripeService.create_checkout_session")
    def test_create_payment_stripe_failure(self, mock_stripe):
        """Test payment creation when Stripe fails"""
        mock_stripe.return_value = {"success": False, "error": "Stripe API error"}

        self.client.force_authenticate(user=self.regular_user)
        url = reverse("payments:payments-list")

        data = {"borrowing": self.new_borrowing.id, "type": "payment"}

        response = self.client.post(url, data)

        self.assertEqual(response.status_code, status.HTTP_500_INTERNAL_SERVER_ERROR)
        self.assertIn("error", response.data)
        # Payment should be deleted on failure
        self.assertFalse(
            Payment.objects.filter(
                borrowing=self.new_borrowing, type="payment"
            ).exists()
        )

    def test_create_payment_other_users_borrowing(self):
        """Test that users cannot create payments for other users' borrowings"""
        other_user = User.objects.create_user(
            email="other@test.com", password="pass123"
        )

        self.client.force_authenticate(user=other_user)
        url = reverse("payments:payments-list")

        data = {"borrowing": self.new_borrowing.id, "type": "payment"}

        response = self.client.post(url, data)

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_create_payment_with_existing_active_session(self):
        """Test that users cannot create new payment when active session exists"""
        self.client.force_authenticate(user=self.regular_user)
        url = reverse("payments:payments-list")

        data = {"borrowing": self.payment.borrowing.id, "type": "payment"}

        response = self.client.post(url, data)

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("active payment session", str(response.data).lower())

    @patch("payments.stripe_service.StripeService.create_checkout_session")
    def test_staff_can_create_payment_for_any_borrowing(self, mock_stripe):
        """Test that staff can create payments for any borrowing"""
        mock_stripe.return_value = {
            "success": True,
            "session_id": "cs_test_staff",
            "session_url": "https://checkout.stripe.com/staff",
        }

        self.client.force_authenticate(user=self.staff_user)
        url = reverse("payments:payments-list")

        data = {"borrowing": self.new_borrowing.id, "type": "payment"}

        response = self.client.post(url, data)

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)


# ==================== RETRIEVE TESTS ====================


class PaymentRetrieveTests(PaymentTestBase):
    """Test payment detail endpoint"""

    def test_retrieve_own_payment(self):
        """Test retrieving own payment"""
        self.client.force_authenticate(user=self.regular_user)
        url = reverse("payments:payments-detail", kwargs={"pk": self.payment.id})

        response = self.client.get(url)

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["id"], self.payment.id)
        self.assertIn("borrowing_details", response.data)

    def test_retrieve_other_users_payment(self):
        """Test that users cannot retrieve other users' payments"""
        other_user = User.objects.create_user(
            email="other@test.com", password="pass123"
        )

        self.client.force_authenticate(user=other_user)
        url = reverse("payments:payments-detail", kwargs={"pk": self.payment.id})

        response = self.client.get(url)

        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

    def test_staff_can_retrieve_any_payment(self):
        """Test that staff can retrieve any payment"""
        self.client.force_authenticate(user=self.staff_user)
        url = reverse("payments:payments-detail", kwargs={"pk": self.payment.id})

        response = self.client.get(url)

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["id"], self.payment.id)


# ==================== UPDATE/DELETE TESTS ====================


class PaymentUpdateDeleteTests(PaymentTestBase):
    """Test payment update and delete endpoints"""

    def test_update_payment_not_allowed(self):
        """Test that direct payment updates are not allowed"""
        self.client.force_authenticate(user=self.regular_user)
        url = reverse("payments:payments-detail", kwargs={"pk": self.payment.id})

        data = {"status": "paid"}
        response = self.client.patch(url, data)

        self.assertEqual(response.status_code, status.HTTP_405_METHOD_NOT_ALLOWED)

    def test_delete_pending_payment(self):
        """Test deleting pending payment"""
        self.client.force_authenticate(user=self.regular_user)
        url = reverse("payments:payments-detail", kwargs={"pk": self.payment.id})

        response = self.client.delete(url)

        self.assertEqual(response.status_code, status.HTTP_204_NO_CONTENT)
        self.assertFalse(Payment.objects.filter(id=self.payment.id).exists())

    def test_delete_paid_payment_not_allowed(self):
        """Test that paid payments cannot be deleted"""
        self.client.force_authenticate(user=self.regular_user)
        url = reverse("payments:payments-detail", kwargs={"pk": self.paid_payment.id})

        response = self.client.delete(url)

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertTrue(Payment.objects.filter(id=self.paid_payment.id).exists())


# ==================== CUSTOM ACTION TESTS ====================


class PaymentCustomActionsTests(PaymentTestBase):
    """Test custom payment actions"""

    @patch("payments.stripe_service.StripeService.retrieve_checkout_session")
    def test_check_session(self, mock_retrieve):
        """Test check_session action"""
        mock_session = MagicMock()
        mock_session.payment_status = "paid"
        mock_retrieve.return_value = mock_session

        # ensure payment is not already paid (avoid unique constraint)
        # avoid unique constraint by using different type
        self.payment.type = "fine"
        self.payment.status = "pending"
        self.payment.save()

        self.client.force_authenticate(user=self.regular_user)
        url = reverse("payments:payments-check-session", kwargs={"pk": self.payment.id})

        response = self.client.post(url)

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["stripe_session_status"], "paid")

        # Check that payment status was updated
        self.payment.refresh_from_db()
        self.assertEqual(self.payment.status, "paid")

    def test_check_session_no_session_id(self):
        """Test check_session when payment has no session_id"""
        payment_no_session = Payment.objects.create(
            borrowing=self.borrowing,
            type="fine",
            status="pending",
            money_to_pay=Decimal("10.00"),
        )

        self.client.force_authenticate(user=self.regular_user)
        url = reverse(
            "payments:payments-check-session", kwargs={"pk": payment_no_session.id}
        )

        response = self.client.post(url)

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_mark_paid_staff_only(self):
        """Test that only staff can mark payments as paid"""
        self.client.force_authenticate(user=self.regular_user)
        url = reverse("payments:payments-mark-paid", kwargs={"pk": self.payment.id})

        response = self.client.post(url)

        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_mark_paid_by_staff(self):
        """Test staff marking payment as paid"""
        self.payment.type = "fine"  # Avoid unique constraint with other paid payments
        self.payment.status = "pending"
        self.payment.save()

        self.client.force_authenticate(user=self.staff_user)
        url = reverse("payments:payments-mark-paid", kwargs={"pk": self.payment.id})

        response = self.client.post(url)

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.payment.refresh_from_db()
        self.assertEqual(self.payment.status, "paid")

    def test_mark_paid_already_paid(self):
        """Test marking already paid payment"""
        self.client.force_authenticate(user=self.staff_user)
        url = reverse(
            "payments:payments-mark-paid", kwargs={"pk": self.paid_payment.id}
        )

        response = self.client.post(url)

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)


# ==================== RENEW SESSION TESTS ====================


class PaymentRenewSessionTests(PaymentTestBase):
    """Test payment session renewal"""

    @patch("payments.stripe_service.StripeService.renew_checkout_session")
    def test_renew_expired_payment(self, mock_renew):
        """Test renewing expired payment"""
        mock_renew.return_value = {
            "success": True,
            "session_id": "cs_test_renewed",
            "session_url": "https://checkout.stripe.com/renewed",
            "payment_id": self.expired_payment.id,
            "message": "Payment session renewed successfully",
        }

        self.client.force_authenticate(user=self.regular_user)
        url = reverse(
            "payments:payments-renew-session", kwargs={"pk": self.expired_payment.id}
        )

        response = self.client.post(url)

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertIn("renewed successfully", response.data["message"].lower())

    def test_renew_paid_payment_not_allowed(self):
        """Test that paid payments cannot be renewed"""
        self.client.force_authenticate(user=self.regular_user)
        url = reverse(
            "payments:payments-renew-session", kwargs={"pk": self.paid_payment.id}
        )

        response = self.client.post(url)

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("already paid", str(response.data).lower())

    def test_renew_active_payment_not_allowed(self):
        """Test that active payments cannot be renewed"""
        self.client.force_authenticate(user=self.regular_user)
        url = reverse("payments:payments-renew-session", kwargs={"pk": self.payment.id})

        response = self.client.post(url)

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    @patch("payments.stripe_service.StripeService.renew_checkout_session")
    def test_renew_session_stripe_failure(self, mock_renew):
        """Test renewal when Stripe fails"""
        mock_renew.return_value = {"success": False, "error": "Stripe renewal failed"}

        self.client.force_authenticate(user=self.regular_user)
        url = reverse(
            "payments:payments-renew-session", kwargs={"pk": self.expired_payment.id}
        )

        response = self.client.post(url)

        self.assertEqual(response.status_code, status.HTTP_500_INTERNAL_SERVER_ERROR)


# ==================== SESSION STATUS TESTS ====================


class SessionStatusTests(PaymentTestBase):
    """Test session status endpoint"""

    @patch("payments.stripe_service.StripeService.get_session_status")
    def test_get_session_status(self, mock_get_status):
        """Test getting session status"""
        mock_get_status.return_value = {
            "id": self.payment.session_id,
            "status": "open",
            "payment_status": "unpaid",
            "expires_at": int((kyiv_now() + timezone.timedelta(hours=23)).timestamp()),
            "created": int(kyiv_now().timestamp()),
            "url": self.payment.session_url,
            "amount_total": 1050,
            "currency": "usd",
        }

        self.client.force_authenticate(user=self.regular_user)
        url = reverse(
            "payments:payments-session-status", kwargs={"pk": self.payment.id}
        )

        response = self.client.get(url)

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertIn("stripe_session", response.data)
        self.assertEqual(response.data["stripe_session"]["status"], "open")

    @patch("payments.stripe_service.StripeService.get_session_status")
    def test_session_status_updates_payment_when_paid(self, mock_get_status):
        """Test that session status updates payment when Stripe shows paid"""
        # Avoid conflict with any other paid payment for same borrowing
        self.payment.type = "fine"
        self.payment.status = "pending"
        self.payment.save()

        mock_get_status.return_value = {
            "id": self.payment.session_id,
            "status": "complete",
            "payment_status": "paid",
            "expires_at": int((kyiv_now() + timezone.timedelta(hours=23)).timestamp()),
            "created": int(kyiv_now().timestamp()),
            "url": self.payment.session_url,
            "amount_total": 1050,
            "currency": "usd",
        }

        self.client.force_authenticate(user=self.regular_user)
        url = reverse(
            "payments:payments-session-status", kwargs={"pk": self.payment.id}
        )

        response = self.client.get(url)

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.payment.refresh_from_db()
        self.assertEqual(self.payment.status, "paid")


# ==================== MY PAYMENTS TESTS ====================


class MyPaymentsTests(PaymentTestBase):
    """Test my_payments endpoint"""

    def test_my_payments(self):
        """Test getting current user's payments"""
        self.client.force_authenticate(user=self.regular_user)
        url = reverse("payments:payments-my-payments")

        response = self.client.get(url)

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.data["results"]), 3)

    def test_my_payments_includes_all_statuses(self):
        """Test that my_payments includes all payment statuses"""
        self.client.force_authenticate(user=self.regular_user)
        url = reverse("payments:payments-my-payments")

        response = self.client.get(url)

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        statuses = {payment["status"] for payment in response.data["results"]}
        self.assertIn("pending", statuses)
        self.assertIn("paid", statuses)
        self.assertIn("expired", statuses)


# ==================== EXPIRED/RENEWABLE PAYMENTS TESTS ====================


class ExpiredRenewablePaymentsTests(PaymentTestBase):
    """Test expired and renewable payment endpoints"""

    def test_expired_payments(self):
        """Test getting expired payments"""
        self.client.force_authenticate(user=self.regular_user)
        url = reverse("payments:payments-expired-payments")

        response = self.client.get(url)

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["count"], 1)
        self.assertEqual(response.data["payments"][0]["status"], "expired")

    def test_renewable_payments(self):
        """Test getting renewable payments"""
        self.client.force_authenticate(user=self.regular_user)
        url = reverse("payments:payments-renewable-payments")

        response = self.client.get(url)

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertGreaterEqual(response.data["count"], 1)

    def test_staff_sees_all_expired_payments(self):
        """Test that staff see all expired payments"""
        # Create another user's expired payment with a different book
        other_user = User.objects.create_user(
            email="other@test.com", password="pass123"
        )
        other_book = Book.objects.create(
            title="Other Expired Book",
            author="Other Author",
            cover="SOFT",
            inventory=3,
            daily_fee=Decimal("1.00"),
        )
        other_borrowing = Borrowing.objects.create(
            user=other_user,
            book=other_book,
            borrow_date=kyiv_today(),
            expected_return_date=kyiv_today() + timezone.timedelta(days=7),
        )
        Payment.objects.create(
            borrowing=other_borrowing,
            type="payment",
            status="expired",
            money_to_pay=Decimal("5.00"),
        )

        self.client.force_authenticate(user=self.staff_user)
        url = reverse("payments:payments-expired-payments")

        response = self.client.get(url)

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertGreaterEqual(response.data["count"], 2)


# ==================== BULK OPERATIONS TESTS ====================


class BulkOperationsTests(PaymentTestBase):
    """Test bulk operations (staff only)"""

    @patch("payments.stripe_service.StripeService.get_session_status")
    def test_bulk_check_sessions_staff(self, mock_get_status):
        """Test bulk session checking by staff"""
        mock_get_status.return_value = {
            "id": self.payment.session_id,
            "status": "open",
            "payment_status": "paid",
            "expires_at": int((kyiv_now() + timezone.timedelta(hours=23)).timestamp()),
            "created": int(kyiv_now().timestamp()),
            "url": self.payment.session_url,
            "amount_total": 1050,
            "currency": "usd",
        }

        self.client.force_authenticate(user=self.staff_user)
        url = reverse("payments:payments-bulk-check-sessions")

        data = {"payment_ids": [self.payment.id]}
        response = self.client.post(url, data, format="json")

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["total_checked"], 1)
        self.assertGreaterEqual(response.data["updated_count"], 0)

    def test_bulk_check_sessions_regular_user_forbidden(self):
        """Test that regular users cannot perform bulk checks"""
        self.client.force_authenticate(user=self.regular_user)
        url = reverse("payments:payments-bulk-check-sessions")

        data = {"payment_ids": [self.payment.id]}
        response = self.client.post(url, data, format="json")

        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_force_expire_session_staff(self):
        """Test force expiring session by staff"""
        self.client.force_authenticate(user=self.staff_user)
        url = reverse("payments:payments-force-expire-session")

        data = {"payment_id": self.payment.id}
        response = self.client.post(url, data)

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.payment.refresh_from_db()
        self.assertEqual(self.payment.status, "expired")

    def test_force_expire_session_regular_user_forbidden(self):
        """Test that regular users cannot force expire sessions"""
        self.client.force_authenticate(user=self.regular_user)
        url = reverse("payments:payments-force-expire-session")

        data = {"payment_id": self.payment.id}
        response = self.client.post(url, data)

        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_force_expire_paid_payment_not_allowed(self):
        """Test that paid payments cannot be force expired"""
        self.client.force_authenticate(user=self.staff_user)
        url = reverse("payments:payments-force-expire-session")

        data = {"payment_id": self.paid_payment.id}
        response = self.client.post(url, data)

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)


# ==================== SUCCESS/CANCEL ENDPOINTS TESTS ====================


class PaymentCompletionEndpointsTests(PaymentTestBase):
    """Test payment success and cancel endpoints"""

    @patch("payments.stripe_service.StripeService.retrieve_checkout_session")
    def test_payment_success(self, mock_retrieve):
        """Test payment success endpoint"""
        mock_session = MagicMock()
        mock_session.payment_status = "paid"
        mock_retrieve.return_value = mock_session

        self.client.force_authenticate(user=self.regular_user)

        Payment.objects.all().update(status="pending")

        url = reverse("payments:payment_success")
        response = self.client.get(url, {"session_id": self.payment.session_id})

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertIn("successful", response.data["message"].lower())

        self.payment.refresh_from_db()
        self.assertEqual(self.payment.status, "paid")

    def test_payment_success_no_session_id(self):
        """Test payment success without session_id"""
        self.client.force_authenticate(user=self.regular_user)
        url = reverse("payments:payment_success")
        response = self.client.get(url)

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("error", response.data)

    @patch("payments.stripe_service.StripeService.retrieve_checkout_session")
    def test_payment_success_session_not_found(self, mock_retrieve):
        """Test payment success with invalid session"""
        mock_retrieve.return_value = None
        self.client.force_authenticate(user=self.regular_user)

        url = reverse("payments:payment_success")
        response = self.client.get(url, {"session_id": "invalid_session"})

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    @patch("payments.stripe_service.StripeService.retrieve_checkout_session")
    def test_payment_success_payment_not_completed(self, mock_retrieve):
        """Test payment success when payment is not yet completed"""
        mock_session = MagicMock()
        mock_session.payment_status = "unpaid"
        mock_retrieve.return_value = mock_session

        self.client.force_authenticate(user=self.regular_user)

        url = reverse("payments:payment_success")
        response = self.client.get(url, {"session_id": self.payment.session_id})

        self.assertEqual(response.status_code, status.HTTP_202_ACCEPTED)

    def test_payment_cancel(self):
        """Test payment cancel endpoint"""
        self.client.force_authenticate(user=self.regular_user)

        url = reverse("payments:payment_cancel")
        response = self.client.get(url, {"session_id": self.payment.session_id})

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        print(response.data)
        self.assertIn("canceled", response.data["message"].lower())
        self.assertIn("24 hours", response.data["note"])
        self.assertIn("payment_id", response.data)

    def test_payment_cancel_without_session(self):
        """Test payment cancel without session_id"""
        self.client.force_authenticate(user=self.regular_user)

        url = reverse("payments:payment_cancel")
        response = self.client.get(url)

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertIn("canceled", response.data["message"].lower())


# ==================== SYNC WITH STRIPE TEST ====================


class SyncWithStripeTests(PaymentTestBase):
    """Test sync_with_stripe endpoint"""

    @patch("payments.stripe_service.StripeService.retrieve_checkout_session")
    def test_sync_with_stripe_staff(self, mock_retrieve):
        """Test syncing payments with Stripe by staff"""
        mock_session = MagicMock()
        mock_session.payment_status = "paid"
        mock_retrieve.return_value = mock_session

        self.client.force_authenticate(user=self.staff_user)
        url = reverse("payments:payments-sync-with-stripe")

        response = self.client.post(url)

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertIn("updated_count", response.data)
        self.assertIn("total_checked", response.data)

    def test_sync_with_stripe_regular_user_forbidden(self):
        """Test that regular users cannot sync with Stripe"""
        self.client.force_authenticate(user=self.regular_user)
        url = reverse("payments:payments-sync-with-stripe")

        response = self.client.post(url)

        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    # !!!
    @patch("payments.views.StripeService.retrieve_checkout_session")
    def test_sync_with_stripe_updates_pending_to_paid(self, mock_retrieve):
        """Test that sync correctly updates pending payments to paid"""
        # Clean up to avoid unique constraint conflicts
        self.payment.borrowing.payments.exclude(id=self.payment.id).delete()

        # Verify initial state
        self.assertEqual(self.payment.status, "pending")
        self.assertIsNotNone(self.payment.session_id)

        # Create a proper mock session
        mock_session = MagicMock()
        mock_session.payment_status = "paid"
        mock_retrieve.return_value = mock_session

        self.client.force_authenticate(user=self.staff_user)
        url = reverse("payments:payments-sync-with-stripe")

        response = self.client.post(url)

        # Check response
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertIn("updated_count", response.data)
        self.assertIn("errors", response.data)

        # If there are errors, fail with details
        if response.data["errors"]:
            self.fail(f"Sync had errors: {response.data['errors']}")

        # Verify at least one payment was updated
        self.assertGreaterEqual(response.data["updated_count"], 1)

        # Verify the payment was updated
        self.payment.refresh_from_db()
        self.assertEqual(self.payment.status, "paid")

        # Verify the mock was called
        self.assertTrue(mock_retrieve.called)


# ==================== MY FINES TESTS ====================


class MyFinesTests(PaymentTestBase):
    """Test my_fines endpoint"""

    def setUp(self):
        super().setUp()
        # Create a fine payment
        self.fine_payment = Payment.objects.create(
            borrowing=self.borrowing,
            type="fine",
            status="pending",
            money_to_pay=Decimal("5.00"),
            session_id="cs_test_fine",
            session_url="https://checkout.stripe.com/fine",
        )

    def test_my_fines(self):
        """Test getting current user's fine payments"""
        self.client.force_authenticate(user=self.regular_user)
        url = reverse("payments:payments-my-fines")

        response = self.client.get(url)

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.data), 1)
        self.assertEqual(response.data[0]["type"], "fine")

    def test_my_fines_empty_for_user_without_fines(self):
        """Test that users without fines get empty list"""
        other_user = User.objects.create_user(
            email="nofines@test.com", password="pass123"
        )

        self.client.force_authenticate(user=other_user)
        url = reverse("payments:payments-my-fines")

        response = self.client.get(url)

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.data), 0)


# ==================== CREATE FINE TESTS ====================


class CreateFineForBorrowingTests(PaymentTestBase):
    """Test create_fine_for_borrowing endpoint"""

    def setUp(self):
        super().setUp()
        # Create a different book for overdue borrowing to avoid constraint violation
        self.overdue_book = Book.objects.create(
            title="Overdue Test Book",
            author="Test Author 2",
            cover="SOFT",
            inventory=3,
            daily_fee=Decimal("2.00"),
        )
        # Create an overdue borrowing (not yet returned, past due date)
        # This makes is_overdue = True (view checks this first)
        # AND enables was_returned_late after return (service needs this)
        self.overdue_borrowing = Borrowing.objects.create(
            user=self.regular_user,
            book=self.overdue_book,
            borrow_date=kyiv_today() - timezone.timedelta(days=14),
            expected_return_date=kyiv_today() - timezone.timedelta(days=7),
            actual_return_date=kyiv_today(),
        )

    @patch("payments.stripe_service.StripeService.create_checkout_session")
    def test_create_fine_for_borrowing_staff(self, mock_stripe):
        """Test creating fine payment for late-returned borrowing"""
        mock_stripe.return_value = {
            "success": True,
            "session_id": "cs_test_fine_new",
            "session_url": "https://checkout.stripe.com/fine_new",
        }

        self.client.force_authenticate(user=self.staff_user)
        url = reverse("payments:payments-create-fine-for-borrowing")
        data = {"borrowing_id": self.overdue_borrowing.id}

        response = self.client.post(url, data)

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(response.data["type"], "fine")
        self.assertGreater(Decimal(response.data["money_to_pay"]), 0)

    def test_create_fine_regular_user_forbidden(self):
        """Test that regular users cannot create fine payments"""
        self.client.force_authenticate(user=self.regular_user)
        url = reverse("payments:payments-create-fine-for-borrowing")

        data = {"borrowing_id": self.overdue_borrowing.id}
        response = self.client.post(url, data)

        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_create_fine_for_non_overdue_borrowing(self):
        """Test creating fine for non-overdue borrowing fails"""
        self.client.force_authenticate(user=self.staff_user)
        url = reverse("payments:payments-create-fine-for-borrowing")

        data = {"borrowing_id": self.borrowing.id}  # Not overdue
        response = self.client.post(url, data)

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_create_fine_missing_borrowing_id(self):
        """Test creating fine without borrowing_id"""
        self.client.force_authenticate(user=self.staff_user)
        url = reverse("payments:payments-create-fine-for-borrowing")

        response = self.client.post(url, {})

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_create_fine_invalid_borrowing_id(self):
        """Test creating fine with invalid borrowing_id"""
        self.client.force_authenticate(user=self.staff_user)
        url = reverse("payments:payments-create-fine-for-borrowing")

        data = {"borrowing_id": 99999}
        response = self.client.post(url, data)

        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)


# ==================== TEST SESSIONS TESTS ====================


class CreateTestSessionsTests(PaymentTestBase):
    """Test create_test_sessions endpoint"""

    @patch("payments.stripe_service.StripeService.create_test_sessions")
    def test_create_test_sessions_staff(self, mock_create_test):
        """Test creating test sessions by staff"""
        mock_create_test.return_value = [
            {
                "session_id": "cs_test_1",
                "session_url": "https://checkout.stripe.com/test1",
                "amount": 10.00,
                "description": "Test payment #1",
            }
        ]

        self.client.force_authenticate(user=self.staff_user)
        url = reverse("payments:payments-create-test-sessions")

        response = self.client.post(url)

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertIn("sessions", response.data)

    def test_create_test_sessions_regular_user_forbidden(self):
        """Test that regular users cannot create test sessions"""
        self.client.force_authenticate(user=self.regular_user)
        url = reverse("payments:payments-create-test-sessions")

        response = self.client.post(url)

        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    @patch("payments.stripe_service.StripeService.create_test_sessions")
    def test_create_test_sessions_failure(self, mock_create_test):
        """Test handling of test session creation failure"""
        mock_create_test.return_value = []

        self.client.force_authenticate(user=self.staff_user)
        url = reverse("payments:payments-create-test-sessions")

        response = self.client.post(url)

        self.assertEqual(response.status_code, status.HTTP_500_INTERNAL_SERVER_ERROR)


# ==================== WEBHOOK EVENTS TESTS ====================


class WebhookEventsTests(PaymentTestBase):
    """Test webhook_events endpoint"""

    @patch("payments.stripe_service.StripeService.get_webhook_events")
    def test_webhook_events_staff(self, mock_get_events):
        """Test getting webhook events by staff"""
        mock_event = MagicMock()
        mock_event.id = "evt_test"
        mock_event.type = "checkout.session.completed"
        mock_event.created = int(kyiv_now().timestamp())
        mock_event.data = {}

        mock_get_events.return_value = [mock_event]

        self.client.force_authenticate(user=self.staff_user)
        url = reverse("payments:payments-webhook-events")

        response = self.client.get(url)

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertIn("events", response.data)
        self.assertEqual(len(response.data["events"]), 1)

    def test_webhook_events_regular_user_forbidden(self):
        """Test that regular users cannot view webhook events"""
        self.client.force_authenticate(user=self.regular_user)
        url = reverse("payments:payments-webhook-events")

        response = self.client.get(url)

        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)


# ==================== EDGE CASES AND ERROR HANDLING ====================


class PaymentEdgeCasesTests(PaymentTestBase):
    """Test edge cases and error handling"""

    def test_retrieve_nonexistent_payment(self):
        """Test retrieving non-existent payment"""
        self.client.force_authenticate(user=self.regular_user)
        url = reverse("payments:payments-detail", kwargs={"pk": 99999})

        response = self.client.get(url)

        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

    def test_renew_session_nonexistent_payment(self):
        """Test renewing session for non-existent payment"""
        self.client.force_authenticate(user=self.regular_user)
        url = reverse("payments:payments-renew-session", kwargs={"pk": 99999})

        response = self.client.post(url)

        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

    @patch("payments.stripe_service.StripeService.get_session_status")
    def test_session_status_stripe_error(self, mock_get_status):
        """Test session status when Stripe returns error"""
        mock_get_status.return_value = None

        self.client.force_authenticate(user=self.regular_user)
        url = reverse(
            "payments:payments-session-status", kwargs={"pk": self.payment.id}
        )

        response = self.client.get(url)

        self.assertEqual(response.status_code, status.HTTP_500_INTERNAL_SERVER_ERROR)

    def test_bulk_check_empty_payment_ids(self):
        """Test bulk check with empty payment_ids"""
        self.client.force_authenticate(user=self.staff_user)
        url = reverse("payments:payments-bulk-check-sessions")

        data = {"payment_ids": []}
        response = self.client.post(url, data, format="json")

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    @patch("payments.stripe_service.StripeService.get_session_status")
    def test_bulk_check_with_invalid_payment_ids(self, mock_get_status):
        """Test bulk check with some invalid payment IDs"""
        self.client.force_authenticate(user=self.staff_user)
        url = reverse("payments:payments-bulk-check-sessions")

        # Simulate Stripe returning a successful session check
        mock_get_status.return_value = {"status": "complete"}

        data = {"payment_ids": [self.payment.id, 99999]}
        response = self.client.post(url, data, format="json")

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertIn("results", response.data)

    def test_force_expire_nonexistent_payment(self):
        """Test force expiring non-existent payment"""
        self.client.force_authenticate(user=self.staff_user)
        url = reverse("payments:payments-force-expire-session")

        data = {"payment_id": 99999}
        response = self.client.post(url, data)

        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)


# ==================== PERMISSION TESTS ====================


class PaymentPermissionTests(PaymentTestBase):
    """Test permission handling across different endpoints"""

    def test_unauthenticated_access_denied(self):
        """Test that unauthenticated users are denied access"""
        endpoints = [
            ("payments:payments-list", "get", {}),
            ("payments:payments-detail", "get", {"pk": self.payment.id}),
            ("payments:payments-my-payments", "get", {}),
            ("payments:payments-expired-payments", "get", {}),
        ]

        for endpoint_name, method, kwargs in endpoints:
            url = reverse(endpoint_name, kwargs=kwargs)
            response = getattr(self.client, method)(url)
            self.assertEqual(
                response.status_code,
                status.HTTP_401_UNAUTHORIZED,
                f"Failed for endpoint: {endpoint_name}",
            )

    def test_regular_user_cannot_access_other_users_payment(self):
        """Test that regular users cannot access other users' payments"""
        other_user = User.objects.create_user(
            email="other@test.com", password="pass123"
        )

        self.client.force_authenticate(user=other_user)

        # Try to access regular_user's payment
        url = reverse("payments:payments-detail", kwargs={"pk": self.payment.id})
        response = self.client.get(url)

        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

    def test_staff_only_endpoints_deny_regular_users(self):
        """Test that staff-only endpoints deny regular users"""
        self.client.force_authenticate(user=self.regular_user)

        staff_endpoints = [
            ("payments:payments-mark-paid", "post", {"pk": self.payment.id}),
            ("payments:payments-sync-with-stripe", "post", {}),
            ("payments:payments-bulk-check-sessions", "post", {}),
            ("payments:payments-force-expire-session", "post", {}),
            ("payments:payments-create-test-sessions", "post", {}),
            ("payments:payments-webhook-events", "get", {}),
            ("payments:payments-create-fine-for-borrowing", "post", {}),
        ]

        for endpoint_name, method, kwargs in staff_endpoints:
            url = reverse(endpoint_name, kwargs=kwargs)
            data = {"payment_ids": [self.payment.id]} if "bulk" in endpoint_name else {}
            response = getattr(self.client, method)(url, data, format="json")
            self.assertEqual(
                response.status_code,
                status.HTTP_403_FORBIDDEN,
                f"Failed for endpoint: {endpoint_name}",
            )


# ==================== INTEGRATION TESTS ====================


class PaymentIntegrationTests(PaymentTestBase):
    """Integration tests for complete payment workflows"""

    @patch("payments.stripe_service.StripeService.create_checkout_session")
    @patch("payments.stripe_service.StripeService.retrieve_checkout_session")
    def test_complete_payment_workflow(self, mock_retrieve, mock_create):
        """Test complete payment workflow: create -> check -> success"""
        # Create new book to avoid constraint violation
        workflow_book = Book.objects.create(
            title="Workflow Test Book",
            author="Workflow Author",
            cover="HARD",
            inventory=10,
            daily_fee=Decimal("1.00"),
        )

        # Create new borrowing
        new_borrowing = Borrowing.objects.create(
            user=self.regular_user,
            book=workflow_book,
            borrow_date=kyiv_today(),
            expected_return_date=kyiv_today() + timezone.timedelta(days=7),
        )

        # Step 1: Create payment
        mock_create.return_value = {
            "success": True,
            "session_id": "cs_workflow_test",
            "session_url": "https://checkout.stripe.com/workflow",
        }

        self.client.force_authenticate(user=self.regular_user)
        url = reverse("payments:payments-list")
        data = {"borrowing": new_borrowing.id, "type": "payment"}
        response = self.client.post(url, data)

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        payment_id = response.data["id"]

        # Step 2: Check session (unpaid)
        mock_session = MagicMock()
        mock_session.payment_status = "unpaid"
        mock_retrieve.return_value = mock_session

        url = reverse("payments:payments-check-session", kwargs={"pk": payment_id})
        response = self.client.post(url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        # Step 3: Simulate payment success
        mock_session.payment_status = "paid"
        url = reverse("payments:payment_success")
        response = self.client.get(url, {"session_id": "cs_workflow_test"})

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        payment = Payment.objects.get(id=payment_id)
        self.assertEqual(payment.status, "paid")

    @patch("payments.stripe_service.StripeService.renew_checkout_session")
    def test_expired_payment_renewal_workflow(self, mock_renew):
        """Test expired payment renewal workflow"""
        mock_renew.return_value = {
            "success": True,
            "session_id": "cs_renewed_workflow",
            "session_url": "https://checkout.stripe.com/renewed",
            "payment_id": self.expired_payment.id,
            "message": "Payment session renewed successfully",
        }

        self.client.force_authenticate(user=self.regular_user)

        # Step 1: Check expired payments
        url = reverse("payments:payments-expired-payments")
        response = self.client.get(url)
        self.assertGreaterEqual(response.data["count"], 1)

        # Step 2: Renew expired payment
        url = reverse(
            "payments:payments-renew-session", kwargs={"pk": self.expired_payment.id}
        )
        response = self.client.post(url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        # Verify payment is now pending with new session
        self.expired_payment.refresh_from_db()
        self.assertEqual(self.expired_payment.status, "pending")
        self.assertEqual(self.expired_payment.session_id, "cs_renewed_workflow")
