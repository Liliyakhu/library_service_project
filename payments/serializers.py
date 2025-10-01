from datetime import timedelta

import pytz
from rest_framework import serializers
from rest_framework.fields import DateTimeField
from django.utils import timezone

from payments.models import Payment
from borrowings.models import Borrowing

KYIV_TZ = pytz.timezone("Europe/Kyiv")


class PaymentSerializer(serializers.ModelSerializer):
    """Serializer for Payment model"""

    # Related fields for better readability
    borrowing_id = serializers.IntegerField(source="borrowing.id", read_only=True)
    book_title = serializers.CharField(source="borrowing.book.title", read_only=True)
    user_email = serializers.CharField(source="borrowing.user.email", read_only=True)

    # New fields for session expiration handling
    is_expired = serializers.ReadOnlyField()
    is_renewable = serializers.ReadOnlyField()
    time_until_expiry = serializers.SerializerMethodField()

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
            "session_expires_at",
            "is_expired",
            "is_renewable",
            "time_until_expiry",
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
            "session_expires_at",
        ]

    def get_time_until_expiry(self, obj):
        """Calculate time until session expiry"""
        if not obj.session_expires_at:
            return None

        now = timezone.now().astimezone(KYIV_TZ)

        if obj.session_expires_at <= now:
            return "Expired"

        time_diff = obj.session_expires_at - now
        hours = int(time_diff.total_seconds() // 3600)
        minutes = int((time_diff.total_seconds() % 3600) // 60)

        if hours > 0:
            return f"{hours}h {minutes}m"
        else:
            return f"{minutes}m"


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

        # Check if borrowing already has a pending or expired payment that could be renewed
        existing_payments = value.payments.filter(status__in=["pending", "expired"])
        if existing_payments.exists():
            # Check if any pending payments are not expired
            for payment in existing_payments:
                if payment.status == "pending" and not payment.is_expired:
                    raise serializers.ValidationError(
                        "This borrowing already has an active payment session. "
                        "Please complete the existing payment or wait for it to expire."
                    )

            # If we have only expired payments, that's ok - user can create new payment
            # But we might want to suggest renewal instead
            if existing_payments.filter(status="expired").exists():
                raise serializers.ValidationError(
                    "This borrowing has expired payment sessions. "
                    "Consider renewing an existing payment instead of creating a new one."
                )

        return value


class PaymentDetailSerializer(serializers.ModelSerializer):
    """Detailed serializer for individual payment view"""

    # Related borrowing information
    borrowing_details = serializers.SerializerMethodField()

    # Session expiration info
    is_expired = serializers.ReadOnlyField()
    is_renewable = serializers.ReadOnlyField()
    time_until_expiry = serializers.SerializerMethodField()
    session_status_info = serializers.SerializerMethodField()
    new_session_created_at = serializers.SerializerMethodField()

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
            "session_expires_at",
            "is_expired",
            "is_renewable",
            "time_until_expiry",
            "session_status_info",
            "new_session_created_at",
        ]
        read_only_fields = [
            "id",
            "session_url",
            "session_id",
            "money_to_pay",
            "created_at",
            "session_expires_at",
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

    def get_time_until_expiry(self, obj):
        """Calculate time until session expiry"""
        if not obj.session_expires_at:
            return None

        now = timezone.now().astimezone(KYIV_TZ)
        if obj.session_expires_at <= now:
            return "Expired"

        time_diff = obj.session_expires_at - now
        hours = int(time_diff.total_seconds() // 3600)
        minutes = int((time_diff.total_seconds() % 3600) // 60)

        if hours > 0:
            return f"{hours}h {minutes}m"
        else:
            return f"{minutes}m"

    def get_session_status_info(self, obj):
        """Get session status information"""
        datetime_field = DateTimeField()
        return {
            "has_session": bool(obj.session_id),
            # "session_id": obj.session_id,
            # "is_expired": obj.is_expired,
            # "is_renewable": obj.is_renewable,
            # "expires_at": (
            #     datetime_field.to_representation(obj.session_expires_at)
            #     if obj.session_expires_at else None
            # ),
            "status_display": obj.get_status_display(),
        }

    def get_new_session_created_at(self, obj):
        datetime_field = DateTimeField()
        return datetime_field.to_representation(
            obj.session_expires_at - timedelta(hours=24)
        )


class PaymentRenewalSerializer(serializers.Serializer):
    """Serializer for payment renewal requests"""

    payment_id = serializers.IntegerField()

    def validate_payment_id(self, value):
        """Validate that payment exists and can be renewed"""
        try:
            payment = Payment.objects.get(id=value)
        except Payment.DoesNotExist:
            raise serializers.ValidationError("Payment not found")

        # Check permissions
        request = self.context.get("request")
        if request and hasattr(request, "user"):
            if not request.user.is_staff and payment.borrowing.user != request.user:
                raise serializers.ValidationError(
                    "You can only renew your own payments"
                )

        # Check if renewable
        if not payment.is_renewable:
            raise serializers.ValidationError(
                f"Payment cannot be renewed. Current status: {payment.status}"
            )

        return value


class PaymentStatusUpdateSerializer(serializers.Serializer):
    """Serializer for bulk payment status updates (staff only)"""

    payment_ids = serializers.ListField(
        child=serializers.IntegerField(),
        min_length=1,
        max_length=100,  # Limit bulk operations
        help_text="List of payment IDs to check/update",
    )

    action = serializers.ChoiceField(
        choices=["check_status", "force_expire"],
        default="check_status",
        help_text="Action to perform on the payments",
    )

    def validate_payment_ids(self, value):
        """Validate that all payment IDs exist"""
        existing_ids = set(
            Payment.objects.filter(id__in=value).values_list("id", flat=True)
        )

        missing_ids = set(value) - existing_ids
        if missing_ids:
            raise serializers.ValidationError(
                f"Payments not found: {sorted(missing_ids)}"
            )

        return value
