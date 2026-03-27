from decimal import Decimal
from datetime import timedelta
from unittest.mock import Mock

from django.contrib.auth import get_user_model
from rest_framework.test import APITestCase, APIClient, APIRequestFactory
from rest_framework.views import APIView

from borrowings.models import Borrowing
from payments.models import Payment
from payments.permissions import IsOwnerOrStaffForPayments
from books.models import Book
from core.utils.timezone_utils import kyiv_now

User = get_user_model()


class IsOwnerOrStaffForPaymentsTestCase(APITestCase):
    """Test suite for IsOwnerOrStaffForPayments permission"""

    def setUp(self):
        """Set up test data"""
        self.client = APIClient()
        self.factory = APIRequestFactory()
        self.permission = IsOwnerOrStaffForPayments()

        # Create test users
        self.regular_user = User.objects.create_user(
            email="user@example.com", password="testpass123"
        )

        self.other_user = User.objects.create_user(
            email="other@example.com", password="testpass123"
        )

        self.staff_user = User.objects.create_user(
            email="staff@example.com", password="testpass123", is_staff=True
        )

        # Create test book
        self.book = Book.objects.create(
            title="Test Book",
            author="Test Author",
            cover="hard",
            inventory=5,
            daily_fee=Decimal("1.50"),
        )

        # Create borrowing for regular user
        self.borrowing = Borrowing.objects.create(
            user=self.regular_user,
            book=self.book,
            borrow_date=kyiv_now().date(),
            expected_return_date=(kyiv_now() + timedelta(days=7)).date(),
        )

        # Create borrowing for other user
        self.other_borrowing = Borrowing.objects.create(
            user=self.other_user,
            book=self.book,
            borrow_date=kyiv_now().date(),
            expected_return_date=(kyiv_now() + timedelta(days=7)).date(),
        )

        # Create payment for regular user's borrowing
        self.payment = Payment.objects.create(
            borrowing=self.borrowing,
            type="payment",
            status="pending",
            money_to_pay=Decimal("10.50"),
        )

        # Create payment for other user's borrowing
        self.other_payment = Payment.objects.create(
            borrowing=self.other_borrowing,
            type="payment",
            status="pending",
            money_to_pay=Decimal("15.00"),
        )

        # Create mock view
        self.view = Mock(spec=APIView)

    def test_has_permission_authenticated_user(self):
        """Test that authenticated users have permission"""
        request = self.factory.get("/payments/")
        request.user = self.regular_user

        has_perm = self.permission.has_permission(request, self.view)

        self.assertTrue(has_perm)

    def test_has_permission_unauthenticated_user(self):
        """Test that unauthenticated users don't have permission"""
        request = self.factory.get("/payments/")
        request.user = None

        has_perm = self.permission.has_permission(request, self.view)

        self.assertFalse(has_perm)

    def test_has_permission_anonymous_user(self):
        """Test that anonymous users don't have permission"""
        from django.contrib.auth.models import AnonymousUser

        request = self.factory.get("/payments/")
        request.user = AnonymousUser()

        has_perm = self.permission.has_permission(request, self.view)

        self.assertFalse(has_perm)

    def test_has_permission_staff_user(self):
        """Test that staff users have permission at class level"""
        request = self.factory.get("/payments/")
        request.user = self.staff_user

        has_perm = self.permission.has_permission(request, self.view)

        self.assertTrue(has_perm)

    def test_has_object_permission_owner(self):
        """Test that payment owner has object permission"""
        request = self.factory.get(f"/payments/{self.payment.id}/")
        request.user = self.regular_user

        has_perm = self.permission.has_object_permission(
            request, self.view, self.payment
        )

        self.assertTrue(has_perm)

    def test_has_object_permission_not_owner(self):
        """Test that non-owner doesn't have object permission"""
        request = self.factory.get(f"/payments/{self.other_payment.id}/")
        request.user = self.regular_user

        has_perm = self.permission.has_object_permission(
            request, self.view, self.other_payment
        )

        self.assertFalse(has_perm)

    def test_has_object_permission_staff_any_payment(self):
        """Test that staff can access any payment"""
        request = self.factory.get(f"/payments/{self.other_payment.id}/")
        request.user = self.staff_user

        has_perm = self.permission.has_object_permission(
            request, self.view, self.other_payment
        )

        self.assertTrue(has_perm)

    def test_has_object_permission_staff_own_payment(self):
        """Test that staff can access their own payment"""
        # Create borrowing and payment for staff user
        staff_borrowing = Borrowing.objects.create(
            user=self.staff_user,
            book=self.book,
            borrow_date=kyiv_now().date(),
            expected_return_date=(kyiv_now() + timedelta(days=7)).date(),
        )

        staff_payment = Payment.objects.create(
            borrowing=staff_borrowing,
            type="payment",
            status="pending",
            money_to_pay=Decimal("12.00"),
        )

        request = self.factory.get(f"/payments/{staff_payment.id}/")
        request.user = self.staff_user

        has_perm = self.permission.has_object_permission(
            request, self.view, staff_payment
        )

        self.assertTrue(has_perm)

    def test_has_object_permission_get_request_owner(self):
        """Test GET request permission for owner"""
        request = self.factory.get(f"/payments/{self.payment.id}/")
        request.user = self.regular_user

        has_perm = self.permission.has_object_permission(
            request, self.view, self.payment
        )

        self.assertTrue(has_perm)

    def test_has_object_permission_post_request_owner(self):
        """Test POST request permission for owner"""
        request = self.factory.post("/payments/")
        request.user = self.regular_user

        has_perm = self.permission.has_object_permission(
            request, self.view, self.payment
        )

        self.assertTrue(has_perm)

    def test_has_object_permission_put_request_owner(self):
        """Test PUT request permission for owner"""
        request = self.factory.put(f"/payments/{self.payment.id}/")
        request.user = self.regular_user

        has_perm = self.permission.has_object_permission(
            request, self.view, self.payment
        )

        self.assertTrue(has_perm)

    def test_has_object_permission_patch_request_owner(self):
        """Test PATCH request permission for owner"""
        request = self.factory.patch(f"/payments/{self.payment.id}/")
        request.user = self.regular_user

        has_perm = self.permission.has_object_permission(
            request, self.view, self.payment
        )

        self.assertTrue(has_perm)

    def test_has_object_permission_delete_request_owner(self):
        """Test DELETE request permission for owner"""
        request = self.factory.delete(f"/payments/{self.payment.id}/")
        request.user = self.regular_user

        has_perm = self.permission.has_object_permission(
            request, self.view, self.payment
        )

        self.assertTrue(has_perm)

    def test_has_object_permission_get_request_not_owner(self):
        """Test GET request permission for non-owner"""
        request = self.factory.get(f"/payments/{self.other_payment.id}/")
        request.user = self.regular_user

        has_perm = self.permission.has_object_permission(
            request, self.view, self.other_payment
        )

        self.assertFalse(has_perm)

    def test_has_object_permission_post_request_not_owner(self):
        """Test POST request permission for non-owner"""
        request = self.factory.post("/payments/")
        request.user = self.regular_user

        has_perm = self.permission.has_object_permission(
            request, self.view, self.other_payment
        )

        self.assertFalse(has_perm)

    def test_has_object_permission_put_request_staff(self):
        """Test PUT request permission for staff on any payment"""
        request = self.factory.put(f"/payments/{self.payment.id}/")
        request.user = self.staff_user

        has_perm = self.permission.has_object_permission(
            request, self.view, self.payment
        )

        self.assertTrue(has_perm)

    def test_has_object_permission_delete_request_staff(self):
        """Test DELETE request permission for staff on any payment"""
        request = self.factory.delete(f"/payments/{self.payment.id}/")
        request.user = self.staff_user

        has_perm = self.permission.has_object_permission(
            request, self.view, self.payment
        )

        self.assertTrue(has_perm)

    def test_payment_through_borrowing_relationship(self):
        """Test that permission correctly accesses user through borrowing"""
        # Verify the relationship chain: Payment -> Borrowing -> User
        self.assertEqual(self.payment.borrowing.user, self.regular_user)
        self.assertEqual(self.other_payment.borrowing.user, self.other_user)

        # Test permission using this relationship
        request = self.factory.get(f"/payments/{self.payment.id}/")
        request.user = self.regular_user

        has_perm = self.permission.has_object_permission(
            request, self.view, self.payment
        )

        self.assertTrue(has_perm)

    def test_multiple_users_different_payments(self):
        """Test that users can only access their own payments"""
        request_user1 = self.factory.get(f"/payments/{self.payment.id}/")
        request_user1.user = self.regular_user

        request_user2 = self.factory.get(f"/payments/{self.other_payment.id}/")
        request_user2.user = self.other_user

        # User 1 can access their payment
        has_perm_user1 = self.permission.has_object_permission(
            request_user1, self.view, self.payment
        )
        self.assertTrue(has_perm_user1)

        # User 2 can access their payment
        has_perm_user2 = self.permission.has_object_permission(
            request_user2, self.view, self.other_payment
        )
        self.assertTrue(has_perm_user2)

        # User 1 cannot access user 2's payment
        request_user1_other = self.factory.get(f"/payments/{self.other_payment.id}/")
        request_user1_other.user = self.regular_user
        has_perm_cross = self.permission.has_object_permission(
            request_user1_other, self.view, self.other_payment
        )
        self.assertFalse(has_perm_cross)

    def test_permission_with_fine_type_payment(self):
        """Test permission works correctly for fine type payments"""
        fine_payment = Payment.objects.create(
            borrowing=self.borrowing,
            type="fine",
            status="pending",
            money_to_pay=Decimal("5.00"),
        )

        request = self.factory.get(f"/payments/{fine_payment.id}/")
        request.user = self.regular_user

        has_perm = self.permission.has_object_permission(
            request, self.view, fine_payment
        )

        self.assertTrue(has_perm)

    def test_permission_with_paid_payment(self):
        """Test permission works correctly for paid payments"""
        paid_payment = Payment.objects.create(
            borrowing=self.borrowing,
            type="payment",
            status="paid",
            money_to_pay=Decimal("10.00"),
            session_id="sess_paid",
            session_url="https://stripe.com/session",
        )

        request = self.factory.get(f"/payments/{paid_payment.id}/")
        request.user = self.regular_user

        has_perm = self.permission.has_object_permission(
            request, self.view, paid_payment
        )

        self.assertTrue(has_perm)

    def test_permission_with_expired_payment(self):
        """Test permission works correctly for expired payments"""
        expired_payment = Payment.objects.create(
            borrowing=self.borrowing,
            type="payment",
            status="expired",
            money_to_pay=Decimal("10.00"),
        )

        request = self.factory.get(f"/payments/{expired_payment.id}/")
        request.user = self.regular_user

        has_perm = self.permission.has_object_permission(
            request, self.view, expired_payment
        )

        self.assertTrue(has_perm)

    def test_permission_checks_both_conditions(self):
        """Test that permission checks both owner and staff conditions"""
        # Create a non-staff, non-owner user
        third_user = User.objects.create_user(
            email="third@example.com", password="testpass123", is_staff=False
        )

        request = self.factory.get(f"/payments/{self.payment.id}/")
        request.user = third_user

        # Neither owner nor staff - should be False
        has_perm = self.permission.has_object_permission(
            request, self.view, self.payment
        )

        self.assertFalse(has_perm)

        # Make user staff
        third_user.is_staff = True
        third_user.save()

        # Now should have permission as staff
        has_perm = self.permission.has_object_permission(
            request, self.view, self.payment
        )

        self.assertTrue(has_perm)

    def tearDown(self):
        """Clean up test data"""
        Payment.objects.all().delete()
        Borrowing.objects.all().delete()
        Book.objects.all().delete()
        User.objects.all().delete()
