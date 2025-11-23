from rest_framework import serializers
from payments.models import Payment
from borrowings.models import Borrowing


class PaymentSerializer(serializers.ModelSerializer):
    """Serializer for Payment model"""

    # Related fields for better readability
    borrowing_id = serializers.IntegerField(source="borrowing.id", read_only=True)
    book_title = serializers.CharField(source="borrowing.book.title", read_only=True)
    user_email = serializers.CharField(source="borrowing.user.email", read_only=True)

    class Meta:
        model = Payment
        fields = [
            "id",
            "status",
            "type",
            "borrowing_id",
            "book_title",
            "user_email",
            "session_url",
            "session_id",
            "money_to_pay",
            "created_at",
        ]
        read_only_fields = [
            "id",
            "session_url",
            "session_id",
            "money_to_pay",
            "created_at",
            "borrowing_id",
            "book_title",
            "user_email",
        ]


class PaymentCreateSerializer(serializers.ModelSerializer):
    """Serializer for creating payments"""

    class Meta:
        model = Payment
        fields = [
            "borrowing",
            "type",
        ]

    def validate_borrowing(self, value):
        """Validate that borrowing belongs to the requesting user"""
        request = self.context.get("request")
        if request and hasattr(request, "user"):
            # Staff can create payments for any borrowing
            if not request.user.is_staff:
                # Regular users can only create payments for their own borrowings
                if value.user != request.user:
                    raise serializers.ValidationError(
                        "You can only create payments for your own borrowings."
                    )

        # Check if borrowing already has a pending payment
        if value.payments.filter(status="pending").exists():
            raise serializers.ValidationError(
                "This borrowing already has a pending payment."
            )

        return value


class PaymentDetailSerializer(serializers.ModelSerializer):
    """Detailed serializer for individual payment view"""

    # Related borrowing information
    borrowing_details = serializers.SerializerMethodField()

    class Meta:
        model = Payment
        fields = [
            "id",
            "status",
            "type",
            "borrowing",
            "borrowing_details",
            "session_url",
            "session_id",
            "money_to_pay",
            "created_at",
        ]
        read_only_fields = [
            "id",
            "session_url",
            "session_id",
            "money_to_pay",
            "created_at",
        ]

    def get_borrowing_details(self, obj):
        """Get detailed borrowing information"""
        borrowing = obj.borrowing
        return {
            "id": borrowing.id,
            "book_title": borrowing.book.title,
            "book_author": borrowing.book.author,
            "user_email": borrowing.user.email,
            "user_full_name": borrowing.user.full_name,
            "borrow_date": borrowing.borrow_date,
            "expected_return_date": borrowing.expected_return_date,
            "actual_return_date": borrowing.actual_return_date,
            "is_overdue": borrowing.is_overdue,
            "days_overdue": borrowing.days_overdue,
            "payment_fee": borrowing.payment_fee,
            "fine_fee": borrowing.fine_fee,
            "total_amount_due": borrowing.total_amount_due,

        }



