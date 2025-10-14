from decimal import Decimal
from datetime import timedelta, date
from unittest.mock import MagicMock, patch

from django.core.exceptions import ValidationError
from django.conf import settings
from django.utils import timezone
from rest_framework.test import APITestCase, APIClient
from django.contrib.auth import get_user_model

from books.models import Book
from borrowings.models import Borrowing
from core.utils.timezone_utils import kyiv_today


User = get_user_model()


class BorrowingModelTests(APITestCase):
    def setUp(self):
        self.client = APIClient()
        self.user = User.objects.create_user(
            email="test@example.com",
            password="password123",
        )
        self.book = Book.objects.create(
            title="Django Deep Dive",
            author="Author X",
            inventory=5,
            daily_fee=Decimal("2.50"),
        )

        self.borrow_date = kyiv_today() - timedelta(days=5)
        self.expected_return_date = kyiv_today() + timedelta(days=5)

    def test_create_valid_borrowing(self):
        """Should create borrowing successfully and reduce book inventory."""
        # Mock book.borrow() to succeed
        self.book.borrow = MagicMock(return_value=True)

        borrowing = Borrowing.objects.create(
            user=self.user,
            book=self.book,
            borrow_date=self.borrow_date,
            expected_return_date=self.expected_return_date,
        )

        self.book.borrow.assert_called_once()
        self.assertEqual(borrowing.user, self.user)
        self.assertEqual(borrowing.book, self.book)
        self.assertTrue(borrowing.is_active)
        self.assertFalse(borrowing.is_returned)

    def test_expected_return_date_before_borrow_date_raises_error(self):
        """Validation should fail if expected_return_date <= borrow_date."""
        with self.assertRaises(ValidationError):
            Borrowing.objects.create(
                user=self.user,
                book=self.book,
                borrow_date=kyiv_today(),
                expected_return_date=kyiv_today(),
            )

    def test_borrow_date_in_future_raises_error(self):
        """Validation should fail if borrow_date is in the future."""
        future_date = kyiv_today() + timedelta(days=2)
        with self.assertRaises(ValidationError):
            Borrowing.objects.create(
                user=self.user,
                book=self.book,
                borrow_date=future_date,
                expected_return_date=future_date + timedelta(days=5),
            )

    def test_actual_return_date_before_borrow_date_raises_error(self):
        """Validation should fail if actual_return_date < borrow_date."""
        with self.assertRaises(ValidationError):
            Borrowing.objects.create(
                user=self.user,
                book=self.book,
                borrow_date=self.borrow_date,
                expected_return_date=self.expected_return_date,
                actual_return_date=self.borrow_date - timedelta(days=1),
            )

    @patch("books.models.Book.return_book")
    def test_return_book_method_marks_returned_and_calls_return_book(self, mock_return):
        """Should call return_book() on Book and set actual_return_date."""
        self.book.borrow = MagicMock(return_value=True)
        borrowing = Borrowing.objects.create(
            user=self.user,
            book=self.book,
            borrow_date=self.borrow_date,
            expected_return_date=self.expected_return_date,
        )

        return_date = kyiv_today()
        borrowing.return_book(return_date)

        mock_return.assert_called_once()
        self.assertTrue(borrowing.is_returned)
        self.assertFalse(borrowing.is_active)
        self.assertEqual(borrowing.actual_return_date, return_date)

    def test_borrowing_properties(self):
        """Test computed properties like overdue, fine, total_amount."""
        self.book.borrow = MagicMock(return_value=True)
        borrowing = Borrowing.objects.create(
            user=self.user,
            book=self.book,
            borrow_date=self.borrow_date,
            expected_return_date=self.expected_return_date,
        )

        # Not overdue or returned yet
        self.assertFalse(borrowing.is_overdue)
        self.assertFalse(borrowing.was_returned_late)
        self.assertEqual(borrowing.fine_fee, Decimal("0.00"))
        self.assertGreater(borrowing.payment_fee, Decimal("0.00"))

        # Mark as late returned
        borrowing.actual_return_date = borrowing.expected_return_date + timedelta(
            days=3
        )
        self.assertTrue(borrowing.was_returned_late)
        fine = borrowing.fine_fee
        fine_multiplier = Decimal(str(getattr(settings, "FINE_MULTIPLIER", 2.0)))
        expected_fine = Decimal("2.50") * 3 * fine_multiplier
        self.assertEqual(fine, expected_fine.quantize(Decimal("0.01")))

    def test_days_overdue_and_total_amount_due(self):
        """Should correctly calculate overdue days and total due."""
        self.book.borrow = MagicMock(return_value=True)
        borrowing = Borrowing.objects.create(
            user=self.user,
            book=self.book,
            borrow_date=self.borrow_date,
            expected_return_date=kyiv_today() - timedelta(days=2),
        )

        # Overdue but not returned
        overdue_days = borrowing.days_overdue
        self.assertEqual(overdue_days, 2)
        self.assertTrue(borrowing.is_overdue)

        # Returned late
        borrowing.actual_return_date = kyiv_today()
        borrowing.save()
        self.assertTrue(borrowing.was_returned_late)
        self.assertGreater(borrowing.total_amount_due, borrowing.payment_fee)

    def test_unique_active_borrowing_constraint(self):
        """User cannot borrow same book twice simultaneously."""
        self.book.borrow = MagicMock(return_value=True)
        Borrowing.objects.create(
            user=self.user,
            book=self.book,
            borrow_date=self.borrow_date,
            expected_return_date=self.expected_return_date,
        )

        with self.assertRaises(Exception):  # IntegrityError or ValidationError
            Borrowing.objects.create(
                user=self.user,
                book=self.book,
                borrow_date=self.borrow_date,
                expected_return_date=self.expected_return_date + timedelta(days=2),
            )
