from datetime import timedelta
from decimal import Decimal
from unittest.mock import patch, PropertyMock

from django.conf import settings
from rest_framework.test import APITestCase, APIClient, APIRequestFactory
from django.contrib.auth import get_user_model
from rest_framework.exceptions import ValidationError

from borrowings.models import Borrowing
from borrowings.serializers import (
    BorrowingCreateSerializer,
    BorrowingUpdateSerializer,
    BorrowingDetailSerializer,
    BorrowingListSerializer,
)
from books.models import Book
from payments.models import Payment
from core.utils.timezone_utils import kyiv_today


User = get_user_model()


class BorrowingSerializerTests(APITestCase):
    def setUp(self):
        self.client = APIClient()
        self.factory = APIRequestFactory()

        self.user = User.objects.create_user(
            email="test@example.com",
            password="pass1234",
        )
        self.book = Book.objects.create(
            title="Clean Code",
            author="Robert C. Martin",
            daily_fee=Decimal("3.00"),
            inventory=5,
        )
        self.borrow_date = kyiv_today()
        self.expected_return_date = self.borrow_date + timedelta(days=5)

    # ---- BorrowingCreateSerializer ----
    @patch("books.models.Book.is_available", new_callable=PropertyMock)
    def test_create_serializer_valid(self, mock_available):
        mock_available.return_value = True

        request = self.factory.post("/")
        request.user = self.user
        expected_return_date = kyiv_today() + timedelta(days=5)

        serializer = BorrowingCreateSerializer(
            data={
                "book": self.book.id,
                "expected_return_date": expected_return_date,
            },
            context={"request": request},
        )

        self.assertTrue(serializer.is_valid(), serializer.errors)
        borrowing = serializer.save()
        self.assertEqual(borrowing.user, self.user)
        self.assertEqual(borrowing.book, self.book)

    @patch("books.models.Book.is_available", new_callable=PropertyMock)
    def test_create_serializer_invalid_book_unavailable(self, mock_available):
        mock_available.return_value = False

        request = self.factory.post("/")
        request.user = self.user
        expected_return_date = kyiv_today() + timedelta(days=5)

        serializer = BorrowingCreateSerializer(
            data={
                "book": self.book.id,
                "expected_return_date": expected_return_date,
            },
            context={"request": request},
        )

        with self.assertRaises(ValidationError):
            serializer.is_valid(raise_exception=True)

    @patch("books.models.Book.is_available", new_callable=PropertyMock)
    def test_create_serializer_expected_date_in_past_invalid(self, mock_available):
        mock_available.return_value = True

        request = self.factory.post("/")
        request.user = self.user
        data = {"book": self.book.id, "expected_return_date": kyiv_today()}

        serializer = BorrowingCreateSerializer(data=data, context={"request": request})
        with self.assertRaises(ValidationError):
            serializer.is_valid(raise_exception=True)

    @patch("books.models.Book.is_available", new_callable=PropertyMock)
    def test_create_serializer_exceeds_max_days_invalid(self, mock_available):
        mock_available.return_value = True

        request = self.factory.post("/")
        request.user = self.user

        too_far_date = kyiv_today() + timedelta(days=settings.MAX_BORROWING_DAYS + 5)
        data = {"book": self.book.id, "expected_return_date": too_far_date}

        serializer = BorrowingCreateSerializer(data=data, context={"request": request})
        with self.assertRaises(ValidationError):
            serializer.is_valid(raise_exception=True)

    # ---- BorrowingUpdateSerializer ----
    def test_update_serializer_valid(self):
        """Should allow updating expected_return_date to a valid later date."""
        borrowing = Borrowing.objects.create(
            user=self.user,
            book=self.book,
            borrow_date=self.borrow_date,
            expected_return_date=self.expected_return_date,
        )
        new_date = borrowing.borrow_date + timedelta(days=10)

        serializer = BorrowingUpdateSerializer(
            instance=borrowing, data={"expected_return_date": new_date}
        )
        self.assertTrue(serializer.is_valid(), serializer.errors)

    def test_update_serializer_invalid_before_borrow_date(self):
        """Reject expected_return_date before borrow_date."""
        borrowing = Borrowing.objects.create(
            user=self.user,
            book=self.book,
            borrow_date=self.borrow_date,
            expected_return_date=self.expected_return_date,
        )
        earlier_date = borrowing.borrow_date - timedelta(days=1)
        serializer = BorrowingUpdateSerializer(
            instance=borrowing, data={"expected_return_date": earlier_date}
        )
        with self.assertRaises(ValidationError):
            serializer.is_valid(raise_exception=True)

    def test_update_serializer_invalid_exceeds_max_days(self):
        """Reject expected_return_date beyond MAX_BORROWING_DAYS limit."""
        borrowing = Borrowing.objects.create(
            user=self.user,
            book=self.book,
            borrow_date=self.borrow_date,
            expected_return_date=self.expected_return_date,
        )
        too_far = borrowing.borrow_date + timedelta(
            days=settings.MAX_BORROWING_DAYS + 1
        )
        serializer = BorrowingUpdateSerializer(
            instance=borrowing, data={"expected_return_date": too_far}
        )
        with self.assertRaises(ValidationError):
            serializer.is_valid(raise_exception=True)

    # ---- BorrowingDetailSerializer ----
    def test_detail_serializer_contains_all_fields(self):
        """Ensure BorrowingDetailSerializer includes calculated + nested fields."""
        borrowing = Borrowing.objects.create(
            user=self.user,
            book=self.book,
            borrow_date=self.borrow_date,
            expected_return_date=self.expected_return_date,
        )

        Payment.objects.create(
            borrowing=borrowing,
            session_url="https://test.payment",
            session_id="sess_123",
            money_to_pay=Decimal("15.00"),
            type="payment",
            status="pending",
        )

        serializer = BorrowingDetailSerializer(borrowing)
        data = serializer.data

        expected_fields = {
            "id",
            "borrow_date",
            "expected_return_date",
            "actual_return_date",
            "book",
            "user_email",
            "is_returned",
            "is_overdue",
            "days_overdue",
            "borrowing_days",
            "payment_fee",
            "fine_fee",
            "total_amount_due",
            "was_returned_late",
            "needs_fine_payment",
            "payments",
        }
        self.assertTrue(expected_fields.issubset(data.keys()))
        self.assertEqual(data["book"]["title"], "Clean Code")
        self.assertEqual(data["user_email"], self.user.email)

    # ---- BorrowingListSerializer ----
    def test_list_serializer_outputs_expected_fields(self):
        """Ensure BorrowingListSerializer returns correct simplified fields."""
        borrowing = Borrowing.objects.create(
            user=self.user,
            book=self.book,
            borrow_date=self.borrow_date,
            expected_return_date=self.expected_return_date,
        )

        serializer = BorrowingListSerializer(borrowing)
        data = serializer.data
        expected_fields = {
            "id",
            "borrow_date",
            "expected_return_date",
            "actual_return_date",
            "book_title",
            "book_author",
            "is_returned",
            "is_overdue",
        }
        self.assertTrue(expected_fields.issubset(data.keys()))
        self.assertEqual(data["book_title"], "Clean Code")
        self.assertEqual(data["book_author"], "Robert C. Martin")
