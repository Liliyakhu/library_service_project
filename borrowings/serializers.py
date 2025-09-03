from rest_framework import serializers
from django.utils import timezone

from borrowings.models import Borrowing
from books.models import Book
from books.serializers import BookSerializer


class BorrowingCreateSerializer(serializers.ModelSerializer):
    """Serializer for creating new borrowings"""

    class Meta:
        model = Borrowing
        fields = [
            "expected_return_date",
            "book",
        ]

    def validate_book(self, value):
        """Validate that the book is available for borrowing"""
        if not value.is_available:
            raise serializers.ValidationError(
                "This book is currently not available for borrowing."
            )
        return value

    def validate_expected_return_date(self, value):
        """Validate expected return date"""
        today = timezone.now().date()

        if value <= today:
            raise serializers.ValidationError(
                "Expected return date must be after today."
            )

        # Optional: limit borrowing period (e.g., max 30 days)
        max_days = 30
        if (value - today).days > max_days:
            raise serializers.ValidationError(
                f"Maximum borrowing period is {max_days} days."
            )

        return value

    def create(self, validated_data):
        """Create a new borrowing with current user attached"""
        # Get the current user from the request context
        user = self.context["request"].user

        # Create the borrowing with the current user
        borrowing = Borrowing.objects.create(user=user, **validated_data)

        return borrowing


class BorrowingDetailSerializer(serializers.ModelSerializer):
    """Detailed read serializer for Borrowing with full book information"""

    book = BookSerializer(read_only=True)
    user_email = serializers.CharField(source="user.email", read_only=True)
    user_full_name = serializers.CharField(source="user.full_name", read_only=True)

    # Calculated fields
    is_returned = serializers.BooleanField(read_only=True)
    is_overdue = serializers.BooleanField(read_only=True)
    days_overdue = serializers.IntegerField(read_only=True)
    borrowing_days = serializers.IntegerField(read_only=True)
    total_fee = serializers.DecimalField(max_digits=8, decimal_places=2, read_only=True)

    class Meta:
        model = Borrowing
        fields = [
            "id",
            "borrow_date",
            "expected_return_date",
            "actual_return_date",
            "book",
            "user_email",
            "user_full_name",
            "is_returned",
            "is_overdue",
            "days_overdue",
            "borrowing_days",
            "total_fee",
        ]


class BorrowingListSerializer(serializers.ModelSerializer):
    """Simplified serializer for listing borrowings"""

    book_title = serializers.CharField(source="book.title", read_only=True)
    book_author = serializers.CharField(source="book.author", read_only=True)
    user_full_name = serializers.CharField(source="user.full_name", read_only=True)
    is_returned = serializers.BooleanField(read_only=True)
    is_overdue = serializers.BooleanField(read_only=True)

    class Meta:
        model = Borrowing
        fields = [
            "id",
            "borrow_date",
            "expected_return_date",
            "actual_return_date",
            "book_title",
            "book_author",
            "user_full_name",
            "is_returned",
            "is_overdue",
        ]
