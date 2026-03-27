import logging
from rest_framework import viewsets, status
from drf_spectacular.utils import extend_schema, OpenApiParameter
from rest_framework.decorators import action
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from django.db import transaction, IntegrityError
from django.db.models import Q, Count, Exists, OuterRef, Prefetch
from django.core.exceptions import ValidationError as DjangoValidationError
from django.utils.html import escape
from rest_framework.exceptions import ValidationError

from notifications.telegram import send_telegram_message
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
from payments.services import (
    create_payment_for_borrowing,
    create_fine_payment_for_borrowing,
)

logger = logging.getLogger(__name__)


class BorrowingViewSet(viewsets.ModelViewSet):
    authentication_classes = [AuthorizeHeaderJWTAuthentication]
    permission_classes = [IsAuthenticated, IsOwnerOrStaff]

    def get_queryset(self):
        """Optimized queryset with proper joins"""
        base_qs = Borrowing.objects.select_related("book", "user")

        # Annotate once
        base_qs = base_qs.annotate(
            has_paid_fine=Exists(
                Payment.objects.filter(
                    borrowing=OuterRef("pk"), type="fine", status="paid"
                )
            ),
            has_pending_fine=Exists(
                Payment.objects.filter(
                    borrowing=OuterRef("pk"), type="fine", status="pending"
                )
            ),
        )

        # Prefetch payments (single prefetch)
        payments_qs = Payment.objects.select_related(
            "borrowing__book", "borrowing__user"
        ).order_by("created_at")

        queryset = base_qs.prefetch_related(Prefetch("payments", queryset=payments_qs))

        # User filtering
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
        Entire operation is atomic - if payment fails, borrowing is rolled back.
        Users cannot borrow if they have any pending payments.
        """
        user = request.user

        # Check for pending payments BEFORE creating borrowing
        pending_payments = Payment.objects.filter(
            borrowing__user=user, status="pending"
        ).select_related("borrowing__book")

        expired_payments = Payment.objects.filter(
            borrowing__user=user, status="expired"
        ).select_related("borrowing__book")

        pending_count = pending_payments.count()
        expired_count = expired_payments.count()

        if pending_count > 0:
            # Build detailed error response with payment information
            payment_details = []
            for payment in pending_payments[:5]:  # Show max 5 payments
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

            if pending_count > 5:
                error_response["note"] = (
                    f"Showing 5 of {pending_count} pending payments. "
                    f"See /api/payments/my_payments/ for full list."
                )

            return Response(error_response, status=status.HTTP_400_BAD_REQUEST)

        # No pending payments - proceed with borrowing creation
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        try:
            # This will handle book inventory atomically
            borrowing = serializer.save()
        except IntegrityError as e:
            # Handle unique constraint violations
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

        # Create payment + stripe session within same transaction
        try:
            payment = create_payment_for_borrowing(borrowing, request=request)
        except Exception as e:
            logger.error(f"Payment creation failed for borrowing {borrowing.id}: {e}")
            # Transaction will rollback automatically due to @transaction.atomic
            raise ValidationError(f"Payment creation failed: {str(e)}")

        response_serializer = BorrowingDetailSerializer(borrowing)

        # Send Telegram notification (fire-and-forget)
        try:
            b = borrowing
            book = b.book
            user = b.user
            msg = (
                "<b>📚 New Borrowing</b>\n"
                f"👤 <b>User</b>: {escape(user.full_name)} ({escape(user.email)})\n"
                f"📖 <b>Book</b>: {escape(book.title)} — {escape(book.author)}\n"
                f"📅 <b>Borrowed</b>: {b.borrow_date:%Y-%m-%d}\n"
                f"🗓️ <b>Due</b>: {b.expected_return_date:%Y-%m-%d}\n"
                f"💸 <b>Daily fee</b>: {book.daily_fee}\n"
                f"📦 <b>Inventory left</b>: {book.inventory}\n"
                f"🧾 <b>Borrowing ID</b>: {b.id}\n"
                f"💳 <b>Payment</b>: {payment.money_to_pay} — {payment.get_type_display()}\n"
                f"🔗 <a href='{payment.session_url}'>Pay now</a>"
            )
            if not send_telegram_message(msg):
                logger.warning(
                    f"Failed to send Telegram notification for borrowing {b.id}"
                )
        except Exception as e:
            logger.error(f"Error sending Telegram notification: {e}")

        logger.info(
            f"Successfully created borrowing {borrowing.id} for user {user.email}"
        )
        return Response(response_serializer.data, status=status.HTTP_201_CREATED)

    def update(self, request, *args, **kwargs):
        """
        FIX: Allow staff to update certain fields (like expected_return_date).
        Regular users still cannot update.
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

        # Prevent updating if already returned
        if borrowing.actual_return_date:
            return Response(
                {"error": "Cannot update a returned borrowing"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        return super().update(request, *args, **kwargs)

    def partial_update(self, request, *args, **kwargs):
        """Allow partial updates with same restrictions as full update"""
        return self.update(request, *args, **kwargs)

    def destroy(self, request, *args, **kwargs):
        """FIX: Only allow staff to delete, and only if no payments exist"""
        if not request.user.is_staff:
            return Response(
                {"error": "Only staff can delete borrowings"},
                status=status.HTTP_403_FORBIDDEN,
            )

        borrowing = self.get_object()

        # Prevent deletion if payments exist
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
        borrowing = self.get_object()

        # Check if borrowing is already returned
        if borrowing.actual_return_date:
            return Response(
                {"error": "This borrowing has already been returned."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        try:
            # Set return date (this will trigger is_overdue calculation)
            borrowing.return_book()

            # Check if fine payment is needed
            fine_payment = None
            if borrowing.was_returned_late:
                try:
                    fine_payment = create_fine_payment_for_borrowing(
                        borrowing, request=request
                    )

                    # Send Telegram notification for fine
                    book = borrowing.book
                    user = borrowing.user
                    days_overdue = borrowing.days_overdue
                    fine_amount = fine_payment.money_to_pay

                    msg = (
                        "<b>💸 Fine Payment Required</b>\n"
                        f"👤 <b>User</b>: {escape(user.full_name)} ({escape(user.email)})\n"
                        f"📖 <b>Book</b>: {escape(book.title)} — {escape(book.author)}\n"
                        f"📅 <b>Returned</b>: {borrowing.actual_return_date:%Y-%m-%d}\n"
                        f"🗓️ <b>Was due</b>: {borrowing.expected_return_date:%Y-%m-%d}\n"
                        f"⏰ <b>Days overdue</b>: {days_overdue}\n"
                        f"💰 <b>Fine amount</b>: ${fine_amount}\n"
                        f"🧾 <b>Borrowing ID</b>: {borrowing.id}\n"
                        f"🔗 <a href='{fine_payment.session_url}'>Pay Fine</a>"
                    )
                    if not send_telegram_message(msg):
                        logger.warning(
                            f"Failed to send fine notification for borrowing {borrowing.id}"
                        )

                except Exception as e:
                    logger.error(
                        f"Failed to create fine payment for borrowing {borrowing.id}: {e}"
                    )

        except DjangoValidationError as e:
            logger.error(f"Validation error returning book {borrowing.id}: {e}")
            return Response({"error": str(e)}, status=status.HTTP_400_BAD_REQUEST)

        response_data = BorrowingDetailSerializer(borrowing).data
        logger.info(
            f"Book returned for borrowing {borrowing.id}. "
            f"Late: {borrowing.was_returned_late}"
        )

        return Response(response_data, status=status.HTTP_200_OK)

    @action(detail=False, methods=["get"])
    def can_borrow(self, request):
        """
        Check if the current user can create a new borrowing.
        Returns borrowing eligibility and pending payment details.
        """
        user = request.user

        # Check for pending payments
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
        for payment in pending_payments:
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
        """Get list of borrowings"""
        return super().list(request, args, **kwargs)

    # def list(self, request, *args, **kwargs):
    #     from django.db import reset_queries, connection
    #
    #     reset_queries()
    #
    #     print("\n" + "=" * 80)
    #     print("STARTING BORROWING LIST REQUEST")
    #     print("=" * 80)
    #
    #     response = super().list(request, *args, **kwargs)
    #
    #     print("\n" + "=" * 80)
    #     print(f"TOTAL QUERIES: {len(connection.queries)}")
    #     print("=" * 80)
    #
    #     for i, query in enumerate(connection.queries, 1):
    #         sql = query['sql']
    #         print(f"\nQuery {i} [{query['time']}s]:")
    #         print(sql[:4000])
    #
    #         # ✅ Better detection - check for WHERE with single ID (N+1 pattern)
    #         if 'users_user' in sql and 'WHERE "users_user"."id" =' in sql:
    #             print("⚠️  INDIVIDUAL USER QUERY - N+1 DETECTED")
    #         if 'books_book' in sql and 'WHERE "books_book"."id" =' in sql:
    #             print("⚠️  INDIVIDUAL BOOK QUERY - N+1 DETECTED")
    #         if 'payments_payment' in sql and 'WHERE "payments_payment"."borrowing_id" =' in sql:
    #             print("⚠️  INDIVIDUAL PAYMENT QUERY - N+1 DETECTED")
    #
    #     print("\n" + "=" * 80)
    #
    #     return response
    #
    # def retrieve(self, request, *args, **kwargs):
    #     """Debug retrieve to see query count"""
    #     from django.db import reset_queries, connection
    #
    #     reset_queries()
    #
    #     print("\n" + "=" * 80)
    #     print("STARTING BORROWING RETRIEVE")
    #     print("=" * 80)
    #
    #     response = super().retrieve(request, *args, **kwargs)
    #
    #     print("\n" + "=" * 80)
    #     print(f"TOTAL QUERIES: {len(connection.queries)}")
    #     print("=" * 80)
    #
    #     for i, query in enumerate(connection.queries, 1):
    #         sql = query['sql']
    #         print(f"\nQuery {i} [{query['time']}s]:")
    #         print(sql[:500])
    #
    #         # Detect N+1 patterns for borrowing detail
    #         if 'payments_payment' in sql and 'WHERE "payments_payment"."id" =' in sql:
    #             print("⚠️  INDIVIDUAL PAYMENT QUERY - N+1 DETECTED")
    #         if 'books_book' in sql and 'WHERE "books_book"."id" =' in sql:
    #             print("⚠️  INDIVIDUAL BOOK QUERY - N+1 DETECTED")
    #         if 'users_user' in sql and 'WHERE "users_user"."id" =' in sql:
    #             print("⚠️  INDIVIDUAL USER QUERY - N+1 DETECTED")
    #
    #     print("\n" + "=" * 80)
    #
    #     return response
