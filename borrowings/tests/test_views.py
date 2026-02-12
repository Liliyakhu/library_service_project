from datetime import timedelta
from decimal import Decimal
from unittest.mock import patch, MagicMock

from django.contrib.auth import get_user_model
from django.urls import reverse
from django.test import override_settings
from rest_framework import status
from rest_framework.test import APITestCase, APIClient

from books.models import Book
from borrowings.models import Borrowing
from payments.models import Payment
from core.utils.timezone_utils import kyiv_today

User = get_user_model()


class BorrowingViewSetTestCase(APITestCase):
    """Test suite for BorrowingViewSet"""

    def setUp(self):
        """Set up test data"""
        self.client = APIClient()

        # Create users
        self.regular_user = User.objects.create_user(
            email="user@test.com",
            password="testpass123",
            first_name="John",
            last_name="Doe",
        )

        self.staff_user = User.objects.create_user(
            email="staff@test.com",
            password="staffpass123",
            first_name="Admin",
            last_name="User",
            is_staff=True,
        )

        self.other_user = User.objects.create_user(
            email="other@test.com",
            password="otherpass123",
            first_name="Jane",
            last_name="Smith",
        )

        # Create books
        self.available_book = Book.objects.create(
            title="Available Book",
            author="Test Author",
            cover="HARD",
            inventory=5,
            daily_fee=Decimal("1.50"),
        )

        self.unavailable_book = Book.objects.create(
            title="Unavailable Book",
            author="Test Author",
            cover="SOFT",
            inventory=0,
            daily_fee=Decimal("1.00"),
        )

        self.today = kyiv_today()
        self.list_url = reverse("borrowings:borrowings-list")

    def test_authentication_required(self):
        """Test that authentication is required for all endpoints"""
        response = self.client.get(self.list_url)
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_list_borrowings_regular_user(self):
        """Test that regular users only see their own borrowings"""
        self.client.force_authenticate(user=self.regular_user)

        # Create borrowings for different users
        borrowing1 = Borrowing.objects.create(
            user=self.regular_user,
            book=self.available_book,
            borrow_date=self.today,
            expected_return_date=self.today + timedelta(days=7),
        )

        borrowing2 = Borrowing.objects.create(
            user=self.other_user,
            book=self.available_book,
            borrow_date=self.today,
            expected_return_date=self.today + timedelta(days=7),
        )

        response = self.client.get(self.list_url)

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.data["results"]), 1)
        self.assertEqual(response.data["results"][0]["id"], borrowing1.id)

    def test_list_borrowings_staff_user(self):
        """Test that staff users see all borrowings"""
        self.client.force_authenticate(user=self.staff_user)

        borrowing1 = Borrowing.objects.create(
            user=self.regular_user,
            book=self.available_book,
            borrow_date=self.today,
            expected_return_date=self.today + timedelta(days=7),
        )

        borrowing2 = Borrowing.objects.create(
            user=self.other_user,
            book=self.available_book,
            borrow_date=self.today,
            expected_return_date=self.today + timedelta(days=7),
        )

        response = self.client.get(self.list_url)

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.data["results"]), 2)

    def test_filter_by_user_id_staff_only(self):
        """Test that staff can filter borrowings by user_id"""
        self.client.force_authenticate(user=self.staff_user)

        borrowing1 = Borrowing.objects.create(
            user=self.regular_user,
            book=self.available_book,
            borrow_date=self.today,
            expected_return_date=self.today + timedelta(days=7),
        )

        borrowing2 = Borrowing.objects.create(
            user=self.other_user,
            book=self.available_book,
            borrow_date=self.today,
            expected_return_date=self.today + timedelta(days=7),
        )

        url = f"{self.list_url}?user_id={self.regular_user.id}"
        response = self.client.get(url)

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.data["results"]), 1)
        self.assertEqual(response.data["results"][0]["id"], borrowing1.id)

    def test_filter_by_is_active(self):
        """Test filtering by is_active parameter"""
        self.client.force_authenticate(user=self.regular_user)

        # Active borrowing
        active = Borrowing.objects.create(
            user=self.regular_user,
            book=self.available_book,
            borrow_date=self.today,
            expected_return_date=self.today + timedelta(days=7),
        )

        # Returned borrowing
        returned = Borrowing.objects.create(
            user=self.regular_user,
            book=self.available_book,
            borrow_date=self.today - timedelta(days=14),
            expected_return_date=self.today - timedelta(days=7),
            actual_return_date=self.today - timedelta(days=5),
        )

        # Test active filter
        response = self.client.get(f"{self.list_url}?is_active=true")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.data["results"]), 1)
        self.assertEqual(response.data["results"][0]["id"], active.id)

        # Test inactive filter
        response = self.client.get(f"{self.list_url}?is_active=false")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.data["results"]), 1)
        self.assertEqual(response.data["results"][0]["id"], returned.id)

    @patch("borrowings.views.create_payment_for_borrowing")
    @patch("borrowings.views.send_telegram_message")
    def test_create_borrowing_success(self, mock_telegram, mock_payment):
        """Test successful borrowing creation"""
        self.client.force_authenticate(user=self.regular_user)

        # Mock payment creation
        mock_payment_obj = MagicMock()
        mock_payment_obj.id = 1
        mock_payment_obj.money_to_pay = Decimal("10.50")
        mock_payment_obj.get_type_display.return_value = "Payment"
        mock_payment_obj.session_url = "https://stripe.com/session"
        mock_payment.return_value = mock_payment_obj
        mock_telegram.return_value = True

        data = {
            "book": self.available_book.id,
            "expected_return_date": (self.today + timedelta(days=7)).isoformat(),
        }

        initial_inventory = self.available_book.inventory
        response = self.client.post(self.list_url, data)

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(response.data["book"]["id"], self.available_book.id)

        # Verify book inventory decreased
        self.available_book.refresh_from_db()
        self.assertEqual(self.available_book.inventory, initial_inventory - 1)

        # Verify payment was created
        mock_payment.assert_called_once()

        # Verify telegram notification sent
        mock_telegram.assert_called_once()

    def test_create_borrowing_unavailable_book(self):
        """Test creating borrowing with unavailable book"""
        self.client.force_authenticate(user=self.regular_user)

        data = {
            "book": self.unavailable_book.id,
            "expected_return_date": (self.today + timedelta(days=7)).isoformat(),
        }

        response = self.client.post(self.list_url, data)

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("not available", str(response.data).lower())

    def test_create_borrowing_with_pending_payments(self):
        """Test that users cannot borrow with pending payments"""
        self.client.force_authenticate(user=self.regular_user)

        # Create existing borrowing with pending payment
        existing_borrowing = Borrowing.objects.create(
            user=self.regular_user,
            book=self.available_book,
            borrow_date=self.today - timedelta(days=5),
            expected_return_date=self.today + timedelta(days=2),
        )

        Payment.objects.create(
            borrowing=existing_borrowing,
            status="pending",
            type="payment",
            session_url="https://stripe.com/session",
            session_id="test_session",
            money_to_pay=Decimal("10.50"),
        )

        data = {
            "book": self.available_book.id,
            "expected_return_date": (self.today + timedelta(days=7)).isoformat(),
        }

        response = self.client.post(self.list_url, data)

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("pending payment", str(response.data).lower())
        self.assertIn("pending_payments", response.data)

    @override_settings(MAX_BORROWING_DAYS=30)
    def test_create_borrowing_exceeds_max_days(self):
        """Test validation for maximum borrowing period"""
        self.client.force_authenticate(user=self.regular_user)

        data = {
            "book": self.available_book.id,
            "expected_return_date": (self.today + timedelta(days=31)).isoformat(),
        }

        response = self.client.post(self.list_url, data)

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("maximum", str(response.data).lower())

    def test_create_borrowing_past_return_date(self):
        """Test validation for past expected return date"""
        self.client.force_authenticate(user=self.regular_user)

        data = {
            "book": self.available_book.id,
            "expected_return_date": (self.today - timedelta(days=1)).isoformat(),
        }

        response = self.client.post(self.list_url, data)

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_retrieve_borrowing_detail(self):
        """Test retrieving borrowing detail"""
        self.client.force_authenticate(user=self.regular_user)

        borrowing = Borrowing.objects.create(
            user=self.regular_user,
            book=self.available_book,
            borrow_date=self.today,
            expected_return_date=self.today + timedelta(days=7),
        )

        url = reverse("borrowings:borrowings-detail", kwargs={"pk": borrowing.id})
        response = self.client.get(url)

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["id"], borrowing.id)
        self.assertIn("book", response.data)
        self.assertIn("payments", response.data)

    def test_regular_user_cannot_update_borrowing(self):
        """Test that regular users cannot update borrowings"""
        self.client.force_authenticate(user=self.regular_user)

        borrowing = Borrowing.objects.create(
            user=self.regular_user,
            book=self.available_book,
            borrow_date=self.today,
            expected_return_date=self.today + timedelta(days=7),
        )

        url = reverse("borrowings:borrowings-detail", kwargs={"pk": borrowing.id})
        data = {"expected_return_date": (self.today + timedelta(days=10)).isoformat()}

        response = self.client.patch(url, data)

        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_staff_can_update_borrowing(self):
        """Test that staff can update borrowings"""
        self.client.force_authenticate(user=self.staff_user)

        borrowing = Borrowing.objects.create(
            user=self.regular_user,
            book=self.available_book,
            borrow_date=self.today,
            expected_return_date=self.today + timedelta(days=7),
        )

        url = reverse("borrowings:borrowings-detail", kwargs={"pk": borrowing.id})
        new_date = self.today + timedelta(days=10)
        data = {"expected_return_date": new_date.isoformat()}

        response = self.client.patch(url, data)

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        borrowing.refresh_from_db()
        self.assertEqual(borrowing.expected_return_date, new_date)

    def test_cannot_update_returned_borrowing(self):
        """Test that returned borrowings cannot be updated"""
        self.client.force_authenticate(user=self.staff_user)

        borrowing = Borrowing.objects.create(
            user=self.regular_user,
            book=self.available_book,
            borrow_date=self.today - timedelta(days=14),
            expected_return_date=self.today - timedelta(days=7),
            actual_return_date=self.today - timedelta(days=5),
        )

        url = reverse("borrowings:borrowings-detail", kwargs={"pk": borrowing.id})
        data = {"expected_return_date": (self.today + timedelta(days=1)).isoformat()}

        response = self.client.patch(url, data)

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_regular_user_cannot_delete_borrowing(self):
        """Test that regular users cannot delete borrowings"""
        self.client.force_authenticate(user=self.regular_user)

        borrowing = Borrowing.objects.create(
            user=self.regular_user,
            book=self.available_book,
            borrow_date=self.today,
            expected_return_date=self.today + timedelta(days=7),
        )

        url = reverse("borrowings:borrowings-detail", kwargs={"pk": borrowing.id})
        response = self.client.delete(url)

        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_staff_can_delete_borrowing_without_payments(self):
        """Test that staff can delete borrowings without payments"""
        self.client.force_authenticate(user=self.staff_user)

        borrowing = Borrowing.objects.create(
            user=self.regular_user,
            book=self.available_book,
            borrow_date=self.today,
            expected_return_date=self.today + timedelta(days=7),
        )

        url = reverse("borrowings:borrowings-detail", kwargs={"pk": borrowing.id})
        response = self.client.delete(url)

        self.assertEqual(response.status_code, status.HTTP_204_NO_CONTENT)
        self.assertFalse(Borrowing.objects.filter(id=borrowing.id).exists())

    def test_cannot_delete_borrowing_with_payments(self):
        """Test that borrowings with payments cannot be deleted"""
        self.client.force_authenticate(user=self.staff_user)

        borrowing = Borrowing.objects.create(
            user=self.regular_user,
            book=self.available_book,
            borrow_date=self.today,
            expected_return_date=self.today + timedelta(days=7),
        )

        Payment.objects.create(
            borrowing=borrowing,
            status="paid",
            type="payment",
            session_url="https://stripe.com/session",
            session_id="test_session",
            money_to_pay=Decimal("10.50"),
        )

        url = reverse("borrowings:borrowings-detail", kwargs={"pk": borrowing.id})
        response = self.client.delete(url)

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertTrue(Borrowing.objects.filter(id=borrowing.id).exists())

    @patch("borrowings.views.send_telegram_message")
    def test_return_book_on_time(self, mock_telegram):
        """Test returning book on time"""
        self.client.force_authenticate(user=self.regular_user)
        mock_telegram.return_value = True

        borrowing = Borrowing.objects.create(
            user=self.regular_user,
            book=self.available_book,
            borrow_date=self.today - timedelta(days=5),
            expected_return_date=self.today + timedelta(days=2),
        )

        initial_inventory = self.available_book.inventory

        url = reverse("borrowings:borrowings-return-book", kwargs={"pk": borrowing.id})
        response = self.client.post(url)

        self.assertEqual(response.status_code, status.HTTP_200_OK)

        borrowing.refresh_from_db()
        self.assertIsNotNone(borrowing.actual_return_date)
        self.assertFalse(borrowing.was_returned_late)

        # Verify inventory restored
        self.available_book.refresh_from_db()
        self.assertEqual(self.available_book.inventory, initial_inventory + 1)

    @patch("borrowings.views.create_fine_payment_for_borrowing")
    @patch("borrowings.views.send_telegram_message")
    def test_return_book_late(self, mock_telegram, mock_fine_payment):
        """Test returning book late creates fine payment"""
        self.client.force_authenticate(user=self.regular_user)
        mock_telegram.return_value = True

        # Mock fine payment
        mock_payment_obj = MagicMock()
        mock_payment_obj.money_to_pay = Decimal("5.00")
        mock_payment_obj.session_url = "https://stripe.com/fine"
        mock_fine_payment.return_value = mock_payment_obj

        borrowing = Borrowing.objects.create(
            user=self.regular_user,
            book=self.available_book,
            borrow_date=self.today - timedelta(days=10),
            expected_return_date=self.today - timedelta(days=3),
        )

        url = reverse("borrowings:borrowings-return-book", kwargs={"pk": borrowing.id})
        response = self.client.post(url)

        self.assertEqual(response.status_code, status.HTTP_200_OK)

        borrowing.refresh_from_db()
        self.assertIsNotNone(borrowing.actual_return_date)
        self.assertTrue(borrowing.was_returned_late)

        # Verify fine payment was created
        mock_fine_payment.assert_called_once()

        # Verify telegram notification sent
        self.assertTrue(mock_telegram.called)

    def test_cannot_return_already_returned_book(self):
        """Test that already returned books cannot be returned again"""
        self.client.force_authenticate(user=self.regular_user)

        borrowing = Borrowing.objects.create(
            user=self.regular_user,
            book=self.available_book,
            borrow_date=self.today - timedelta(days=14),
            expected_return_date=self.today - timedelta(days=7),
            actual_return_date=self.today - timedelta(days=5),
        )

        url = reverse("borrowings:borrowings-return-book", kwargs={"pk": borrowing.id})
        response = self.client.post(url)

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("already been returned", str(response.data))

    def test_can_borrow_endpoint_with_no_pending_payments(self):
        """Test can_borrow endpoint when user has no pending payments"""
        self.client.force_authenticate(user=self.regular_user)

        url = reverse("borrowings:borrowings-can-borrow")
        response = self.client.get(url)

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertTrue(response.data["can_borrow"])
        self.assertEqual(response.data["pending_payments_count"], 0)

    def test_can_borrow_endpoint_with_pending_payments(self):
        """Test can_borrow endpoint when user has pending payments"""
        self.client.force_authenticate(user=self.regular_user)

        borrowing = Borrowing.objects.create(
            user=self.regular_user,
            book=self.available_book,
            borrow_date=self.today - timedelta(days=5),
            expected_return_date=self.today + timedelta(days=2),
        )

        Payment.objects.create(
            borrowing=borrowing,
            status="pending",
            type="payment",
            session_url="https://stripe.com/session",
            session_id="test_session",
            money_to_pay=Decimal("10.50"),
        )

        url = reverse("borrowings:borrowings-can-borrow")
        response = self.client.get(url)

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertFalse(response.data["can_borrow"])
        self.assertEqual(response.data["pending_payments_count"], 1)
        self.assertIn("pending_payments", response.data)
        self.assertIn("help", response.data)

    def test_user_cannot_access_other_user_borrowing(self):
        """Test that users cannot access other users' borrowings"""
        self.client.force_authenticate(user=self.regular_user)

        other_borrowing = Borrowing.objects.create(
            user=self.other_user,
            book=self.available_book,
            borrow_date=self.today,
            expected_return_date=self.today + timedelta(days=7),
        )

        url = reverse("borrowings:borrowings-detail", kwargs={"pk": other_borrowing.id})
        response = self.client.get(url)

        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

    def test_staff_can_access_any_borrowing(self):
        """Test that staff can access any user's borrowing"""
        self.client.force_authenticate(user=self.staff_user)

        borrowing = Borrowing.objects.create(
            user=self.regular_user,
            book=self.available_book,
            borrow_date=self.today,
            expected_return_date=self.today + timedelta(days=7),
        )

        url = reverse("borrowings:borrowings-detail", kwargs={"pk": borrowing.id})
        response = self.client.get(url)

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["id"], borrowing.id)
