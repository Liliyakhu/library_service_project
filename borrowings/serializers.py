from django.conf import settings
from rest_framework import serializers

from borrowings.models import Borrowing
from payments.models import Payment
from books.serializers import BookSerializer
from payments.serializers import PaymentSerializer


class BorrowingCreateSerializer(serializers.ModelSerializer):
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
        today = settings.KYIV_TIME.date()

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
        user = self.context["request"].user
        return Borrowing.objects.create(user=user, **validated_data)


class BorrowingDetailSerializer(serializers.ModelSerializer):
    """Detailed read serializer for Borrowing with full book information"""

    book = BookSerializer(read_only=True)
    user_email = serializers.CharField(source="user.email", read_only=True)
    # user_full_name = serializers.CharField(source="user.full_name", read_only=True)

    # Calculated fields
    is_returned = serializers.BooleanField(read_only=True)
    is_overdue = serializers.BooleanField(read_only=True)
    days_overdue = serializers.IntegerField(read_only=True)
    borrowing_days = serializers.IntegerField(read_only=True)
    payment_fee = serializers.DecimalField(max_digits=8, decimal_places=2, read_only=True)
    fine_fee = serializers.DecimalField(max_digits=8, decimal_places=2, read_only=True)
    total_amount_due = serializers.DecimalField(max_digits=8, decimal_places=2, read_only=True)
    was_returned_late = serializers.BooleanField(read_only=True)
    needs_fine_payment = serializers.BooleanField(read_only=True)
    payments = PaymentSerializer(many=True, read_only=True)

    class Meta:
        model = Borrowing
        fields = [
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
        ]

    # def get_fine_payment(self, obj):
    #     """Get fine payment for this borrowing if it exists"""
    #     fine_payment = Payment.objects.filter(borrowing=obj, type="FINE").first()
    #
    #     if fine_payment:
    #         return {
    #             "id": fine_payment.id,
    #             "amount": str(fine_payment.money_to_pay),
    #             "status": fine_payment.status,
    #             "session_url": fine_payment.session_url,
    #             "session_id": fine_payment.session_id,
    #         }
    #     return None


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
