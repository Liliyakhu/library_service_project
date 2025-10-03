from rest_framework import viewsets, status
from rest_framework.decorators import action
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from django.db import transaction
from django.core.exceptions import ValidationError
from django.utils.html import escape
from notifications.telegram import send_telegram_message

from borrowings.permissions import IsOwnerOrStaff
from borrowings.serializers import (
    BorrowingCreateSerializer,
    BorrowingListSerializer,
    BorrowingDetailSerializer,
)
from users.authentication import AuthorizeHeaderJWTAuthentication
from borrowings.models import Borrowing
from payments.models import Payment
from payments.services import (
    create_payment_for_borrowing,
    create_fine_payment_for_borrowing,
)


class BorrowingViewSet(viewsets.ModelViewSet):
    authentication_classes = [AuthorizeHeaderJWTAuthentication]
    permission_classes = [IsAuthenticated, IsOwnerOrStaff]

    def get_queryset(self):
        """Optimized queryset with proper joins"""
        queryset = Borrowing.objects.select_related("book", "user")

        # User filtering
        if not self.request.user.is_staff:
            queryset = queryset.filter(user=self.request.user)
        else:
            user_id = self.request.query_params.get("user_id")
            if user_id:
                try:
                    queryset = queryset.filter(user_id=int(user_id))
                except (ValueError, TypeError):
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
        return BorrowingDetailSerializer

    @transaction.atomic
    def create(self, request, *args, **kwargs):
        """
                Create a new borrowing.
                Users cannot borrow if they have any pending payments.
                """
        user = request.user

        # Check for pending payments BEFORE creating borrowing
        pending_payments = Payment.objects.filter(
            borrowing__user=user,
            status="pending"
        ).select_related("borrowing__book")

        expired_payments = Payment.objects.filter(
            borrowing__user=user,
            status="expired"
        ).select_related("borrowing__book")

        pending_count = pending_payments.count()
        expired_count = expired_payments.count()

        if pending_count > 0:
            # Build detailed error response with payment information
            payment_details = []
            for payment in pending_payments[:5]:  # Show max 5 payments
                payment_details.append({
                    "payment_id": payment.id,
                    "borrowing_id": payment.borrowing.id,
                    "book_title": payment.borrowing.book.title,
                    "amount": str(payment.money_to_pay),
                    "type": payment.get_type_display(),
                    "session_url": payment.session_url,
                    "created_at": payment.created_at.isoformat(),
                    "is_renewable": payment.is_renewable,
                })

            error_response = {
                "error": "Cannot create new borrowing",
                "reason": f"You have {pending_count} pending payment(s) that must be completed first",
                "pending_payments": payment_details,
                "action_required": "Please complete or renew your pending payments before borrowing new books",
            }

            # Add helpful hints based on payment states
            # expired_count = sum(1 for p in payment_details if p["is_renewable"])
            # active_count = len(payment_details) - expired_count

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
                "summary": " | ".join(help_messages) if help_messages else "Complete your pending payments",
                "endpoints": {
                    "view_all_payments": "GET /api/payments/my_payments/",
                    "renewable_payments": "GET /api/payments/renewable_payments/",
                    "renew_session": "POST /api/payments/{payment_id}/renew_session/"
                }
            }

            if pending_count > 5:
                error_response[
                    "note"] = f"Showing 5 of {pending_count} pending payments. See /api/payments/my_payments/ for full list."

            return Response(error_response, status=status.HTTP_400_BAD_REQUEST)

        # No pending payments - proceed with borrowing creation
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        borrowing = serializer.save()

        # Create payment + stripe session
        try:
            payment = create_payment_for_borrowing(borrowing, request=request)
        except Exception as e:
            # If payment/session creation failed, rollback borrowing too
            raise ValidationError(f"Payment creation failed: {str(e)}")

        response_serializer = BorrowingDetailSerializer(borrowing)

        # Build a neat, HTML-safe message
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
        # Fire-and-forget; we don't block user if Telegram fails
        send_telegram_message(msg)

        return Response(response_serializer.data, status=status.HTTP_201_CREATED)

    def update(self, request, *args, **kwargs):
        return Response(
            {"error": "Updating borrowings not allowed. Use return_book action."},
            status=status.HTTP_405_METHOD_NOT_ALLOWED,
        )

    def destroy(self, request, *args, **kwargs):
        return Response(
            {"error": "Deleting borrowings not allowed."},
            status=status.HTTP_405_METHOD_NOT_ALLOWED,
        )

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
                    send_telegram_message(msg)

                except Exception as e:
                    # Log error but don't fail the return process
                    import logging

                    logger = logging.getLogger(__name__)
                    logger.error(
                        f"Failed to create fine payment for borrowing {borrowing.id}: {e}"
                    )

        except ValidationError as e:
            return Response({"error": e.message}, status=status.HTTP_400_BAD_REQUEST)

        # Prepare response data
        response_data = BorrowingDetailSerializer(borrowing).data

        # Add fine payment info if applicable
        # if fine_payment:
        #     response_data["fine_payment"] = {
        #         "id": fine_payment.id,
        #         "amount": str(fine_payment.money_to_pay),
        #         "session_url": fine_payment.session_url,
        #         "status": fine_payment.status,
        #         "message": "Fine payment required for overdue return",
        #     }

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
            borrowing__user=user,
            status="pending"
        ).select_related("borrowing__book")

        pending_count = pending_payments.count()

        if pending_count == 0:
            return Response({
                "can_borrow": True,
                "message": "You can create new borrowings",
                "pending_payments_count": 0
            })

        # Build payment details
        payment_details = []
        for payment in pending_payments:
            payment_details.append({
                "payment_id": payment.id,
                "borrowing_id": payment.borrowing.id,
                "book_title": payment.borrowing.book.title,
                "amount": str(payment.money_to_pay),
                "type": payment.get_type_display(),
                "session_url": payment.session_url,
                "is_renewable": payment.is_renewable,
            })

        return Response({
            "can_borrow": False,
            "message": f"You have {pending_count} pending payment(s). Please complete them before borrowing.",
            "pending_payments_count": pending_count,
            "pending_payments": payment_details,
            "help": {
                "view_payments": "/api/payments/my_payments/",
                "renewable_payments": "/api/payments/renewable_payments/",
                "renew_session": "/api/payments/{payment_id}/renew_session/"
            }
        })
