import logging
from rest_framework import viewsets, status
from drf_spectacular.utils import extend_schema, OpenApiParameter
from rest_framework.decorators import action
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from django.db import transaction, IntegrityError
from django.db.models import Exists, OuterRef, Prefetch
from django.core.exceptions import ValidationError as DjangoValidationError
from rest_framework.exceptions import ValidationError

from notifications.telegram import send_telegram_message
from notifications.formatters import (
    format_borrowing_notification,
    format_fine_notification,
)
from borrowings.permissions import IsOwnerOrStaff
from borrowings.serializers import (
    BorrowingCreateSerializer,
    BorrowingListSerializer,
    BorrowingDetailSerializer,
    BorrowingUpdateSerializer,
)
from users.authentication import AuthorizeHeaderJWTAuthentication
from borrowings.models import Borrowing
from payments.models import Payment
from payments.services import create_payment

logger = logging.getLogger(__name__)

# Constants
MAX_PAYMENTS_TO_SHOW = 5


class BorrowingViewSet(viewsets.ModelViewSet):
    authentication_classes = [AuthorizeHeaderJWTAuthentication]
    permission_classes = [IsAuthenticated, IsOwnerOrStaff]

    def get_queryset(self):
        """
        Optimized queryset with proper joins and minimal annotations.
        """
        base_qs = Borrowing.objects.select_related("book", "user")

        # Annotate only what's actually used
        base_qs = base_qs.annotate(
            has_paid_fine=Exists(
                Payment.objects.filter(
                    borrowing=OuterRef("pk"), type="fine", status="paid"
                )
            )
        )

        # Prefetch payments efficiently
        payments_qs = Payment.objects.select_related(
            "borrowing__book", "borrowing__user"
        ).order_by("created_at")

        queryset = base_qs.prefetch_related(Prefetch("payments", queryset=payments_qs))

        # Apply filters
        user = self.request.user
        if not user.is_staff:
            queryset = queryset.filter(user=user)
        else:
            user_id = self.request.query_params.get("user_id")
            if user_id:
                try:
                    queryset = queryset.filter(user_id=int(user_id))
                except (ValueError, TypeError):
                    logger.warning(f"Invalid user_id parameter: {user_id}")
                    queryset = queryset.none()

        # Active/inactive filtering
        is_active = self.request.query_params.get("is_active")
        if is_active == "true":
            queryset = queryset.filter(actual_return_date__isnull=True)
        elif is_active == "false":
            queryset = queryset.filter(actual_return_date__isnull=False)

        return queryset.order_by("-id")

    def get_serializer_class(self):
        if self.action == "create":
            return BorrowingCreateSerializer
        elif self.action == "list":
            return BorrowingListSerializer
        elif self.action in ["update", "partial_update"]:
            return BorrowingUpdateSerializer
        return BorrowingDetailSerializer

    @transaction.atomic
    def create(self, request, *args, **kwargs):
        """
        Create a new borrowing with proper transaction handling.
        """
        user = request.user

        # Check pending payments INSIDE transaction with lock
        # This prevents race condition where another request could create
        # a payment between check and borrowing creation
        pending_payments = (
            Payment.objects.select_for_update()
            .filter(borrowing__user=user, status="pending")
            .select_related("borrowing__book")
        )

        if pending_payments.exists():
            return self._build_pending_payments_error(pending_payments, user)

        # Validate and create borrowing
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        try:
            borrowing = serializer.save()
        except IntegrityError as e:
            if "unique_active_borrowing_per_user_book" in str(e):
                return Response(
                    {
                        "error": "You already have an active borrowing for this book",
                        "detail": "Please return your current borrowing before borrowing this book again",
                    },
                    status=status.HTTP_400_BAD_REQUEST,
                )
            logger.error(f"IntegrityError creating borrowing: {e}")
            raise
        except DjangoValidationError as e:
            logger.error(f"ValidationError creating borrowing: {e}")
            return Response(
                {"error": "Validation failed", "details": e.message_dict},
                status=status.HTTP_400_BAD_REQUEST,
            )

        # Create payment within same transaction
        try:
            payment = create_payment(borrowing, payment_type="payment", request=request)
        except Exception as e:
            logger.error(f"Payment creation failed for borrowing {borrowing.id}: {e}")
            raise ValidationError(f"Payment creation failed: {str(e)}")

        # Send Telegram notification
        self._send_borrowing_notification(borrowing, payment)

        response_serializer = BorrowingDetailSerializer(borrowing)
        logger.info(
            f"Successfully created borrowing {borrowing.id} for user {user.email}"
        )

        return Response(response_serializer.data, status=status.HTTP_201_CREATED)

    def _build_pending_payments_error(self, pending_payments, user):
        """
        Build detailed error response for pending payments.

        Args:
            pending_payments: QuerySet of pending Payment objects
            user: User instance

        Returns:
            Response object with detailed error information
        """
        expired_payments = Payment.objects.filter(
            borrowing__user=user, status="expired"
        ).select_related("borrowing__book")

        pending_count = pending_payments.count()
        expired_count = expired_payments.count()

        # Build payment details (limit to avoid huge responses)
        payment_details = []
        for payment in pending_payments[:MAX_PAYMENTS_TO_SHOW]:
            payment_details.append(
                {
                    "payment_id": payment.id,
                    "borrowing_id": payment.borrowing.id,
                    "book_title": payment.borrowing.book.title,
                    "amount": str(payment.money_to_pay),
                    "type": payment.get_type_display(),
                    "session_url": payment.session_url,
                    "is_renewable": payment.is_renewable,
                }
            )

        error_response = {
            "error": "Cannot create new borrowing",
            "reason": f"You have {pending_count} pending payment(s) that must be completed first",
            "pending_payments": payment_details,
            "action_required": "Please complete or renew your pending payments before borrowing new books",
        }

        # Add helpful messages
        help_messages = []
        if pending_count > 0:
            help_messages.append(
                f"{pending_count} active payment(s): Visit the session_url to complete payment"
            )
        if expired_count > 0:
            help_messages.append(
                f"{expired_count} expired session(s): Use POST /api/payments/{{id}}/renew_session/ to renew"
            )

        error_response["help"] = {
            "summary": (
                " | ".join(help_messages)
                if help_messages
                else "Complete your pending payments"
            ),
            "endpoints": {
                "view_all_payments": "GET /api/payments/my_payments/",
                "renewable_payments": "GET /api/payments/renewable_payments/",
                "renew_session": "POST /api/payments/{payment_id}/renew_session/",
            },
        }

        if pending_count > MAX_PAYMENTS_TO_SHOW:
            error_response["note"] = (
                f"Showing {MAX_PAYMENTS_TO_SHOW} of {pending_count} pending payments. "
                f"See /api/payments/my_payments/ for full list."
            )

        return Response(error_response, status=status.HTTP_400_BAD_REQUEST)

    def _send_borrowing_notification(self, borrowing, payment):
        """
        Send Telegram notification for new borrowing.
        """
        try:
            message = format_borrowing_notification(borrowing, payment)
            if not send_telegram_message(message):
                logger.warning(
                    f"Failed to send Telegram notification for borrowing {borrowing.id}"
                )
        except Exception as e:
            logger.error(f"Error sending Telegram notification: {e}")

    def update(self, request, *args, **kwargs):
        """
        Allow staff to update certain fields (like expected_return_date).
        Regular users cannot update.
        """
        if not request.user.is_staff:
            return Response(
                {
                    "error": "Only staff can update borrowings",
                    "hint": "Use /return_book/ action to return a book",
                },
                status=status.HTTP_403_FORBIDDEN,
            )

        borrowing = self.get_object()

        if borrowing.actual_return_date:
            return Response(
                {"error": "Cannot update a returned borrowing"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        return super().update(request, *args, **kwargs)

    def partial_update(self, request, *args, **kwargs):
        """Allow partial updates with same restrictions as full update."""
        return self.update(request, *args, **kwargs)

    def destroy(self, request, *args, **kwargs):
        """Only allow staff to delete, and only if no payments exist."""
        if not request.user.is_staff:
            return Response(
                {"error": "Only staff can delete borrowings"},
                status=status.HTTP_403_FORBIDDEN,
            )

        borrowing = self.get_object()

        if borrowing.payments.exists():
            return Response(
                {
                    "error": "Cannot delete borrowing with associated payments",
                    "payment_count": borrowing.payments.count(),
                },
                status=status.HTTP_400_BAD_REQUEST,
            )

        logger.warning(
            f"Staff user {request.user.email} deleted borrowing {borrowing.id}"
        )
        return super().destroy(request, *args, **kwargs)

    @action(detail=True, methods=["post"])
    @transaction.atomic
    def return_book(self, request, pk=None):
        """
        Return a borrowed book and create fine payment if late.
        """
        borrowing = self.get_object()

        if borrowing.actual_return_date:
            return Response(
                {"error": "This borrowing has already been returned."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        try:
            borrowing.return_book()

            # Create fine payment if returned late
            if borrowing.was_returned_late:
                try:
                    fine_payment = create_payment(
                        borrowing, payment_type="fine", request=request
                    )
                    self._send_fine_notification(borrowing, fine_payment)
                except Exception as e:
                    logger.error(
                        f"Failed to create fine payment for borrowing {borrowing.id}: {e}"
                    )

        except DjangoValidationError as e:
            logger.error(f"Validation error returning book {borrowing.id}: {e}")
            return Response({"error": str(e)}, status=status.HTTP_400_BAD_REQUEST)

        response_data = BorrowingDetailSerializer(borrowing).data
        logger.info(
            f"Book returned for borrowing {borrowing.id}. Late: {borrowing.was_returned_late}"
        )

        return Response(response_data, status=status.HTTP_200_OK)

    def _send_fine_notification(self, borrowing, fine_payment):
        """
        Send Telegram notification for fine payment.
        """
        try:
            message = format_fine_notification(borrowing, fine_payment)
            if not send_telegram_message(message):
                logger.warning(
                    f"Failed to send fine notification for borrowing {borrowing.id}"
                )
        except Exception as e:
            logger.error(f"Error sending fine notification: {e}")

    @action(detail=False, methods=["get"])
    def can_borrow(self, request):
        """
        Check if the current user can create a new borrowing.
        Returns borrowing eligibility and pending payment details.
        """
        user = request.user

        pending_payments = Payment.objects.filter(
            borrowing__user=user, status="pending"
        ).select_related("borrowing__book")

        pending_count = pending_payments.count()

        if pending_count == 0:
            return Response(
                {
                    "can_borrow": True,
                    "message": "You can create new borrowings",
                    "pending_payments_count": 0,
                }
            )

        # Build payment details
        payment_details = []
        for payment in pending_payments[:MAX_PAYMENTS_TO_SHOW]:
            payment_details.append(
                {
                    "payment_id": payment.id,
                    "borrowing_id": payment.borrowing.id,
                    "book_title": payment.borrowing.book.title,
                    "amount": str(payment.money_to_pay),
                    "type": payment.get_type_display(),
                    "session_url": payment.session_url,
                    "is_renewable": payment.is_renewable,
                }
            )

        return Response(
            {
                "can_borrow": False,
                "message": f"You have {pending_count} pending payment(s). Please complete them before borrowing.",
                "pending_payments_count": pending_count,
                "pending_payments": payment_details,
                "help": {
                    "view_payments": "/api/payments/my_payments/",
                    "renewable_payments": "/api/payments/renewable_payments/",
                    "renew_session": "/api/payments/{payment_id}/renew_session/",
                },
            }
        )

    @extend_schema(
        parameters=[
            OpenApiParameter(
                "user_id",
                type=int,
                description="Filter by user id. Only for staff (ex. ?user_id=1)",
            ),
            OpenApiParameter(
                "is_active",
                type=bool,
                description="Filter by active and nonactive borrowings (ex. ?is_active=True)",
            ),
        ]
    )
    def list(self, request, *args, **kwargs):
        """Get list of borrowings."""
        return super().list(request, args, **kwargs)
