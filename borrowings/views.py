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
from payments.services import create_payment_for_borrowing


class BorrowingViewSet(viewsets.ModelViewSet):
    authentication_classes = [AuthorizeHeaderJWTAuthentication]
    permission_classes = [IsAuthenticated, IsOwnerOrStaff]

    def get_queryset(self):
        """Optimized queryset with proper joins"""
        qs = Borrowing.objects.select_related("book", "user")

        # User filtering
        if not self.request.user.is_staff:
            qs = qs.filter(user=self.request.user)
        else:
            user_id = self.request.query_params.get("user_id")
            if user_id:
                try:
                    qs = qs.filter(user_id=int(user_id))
                except (ValueError, TypeError):
                    qs = qs.none()

        # Active/inactive filtering
        is_active = self.request.query_params.get("is_active")
        if is_active == "true":
            qs = qs.filter(actual_return_date__isnull=True)
        elif is_active == "false":
            qs = qs.filter(actual_return_date__isnull=False)

        return qs.order_by("-id")

    def get_serializer_class(self):
        if self.action == "create":
            return BorrowingCreateSerializer
        elif self.action == "list":
            return BorrowingListSerializer
        return BorrowingDetailSerializer

    @transaction.atomic
    def create(self, request, *args, **kwargs):
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

        try:
            borrowing.return_book()
        except ValidationError as e:
            return Response({"error": e.message}, status=status.HTTP_400_BAD_REQUEST)

        return Response(
            BorrowingDetailSerializer(borrowing).data, status=status.HTTP_200_OK
        )
