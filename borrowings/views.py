from rest_framework import viewsets, status
from rest_framework.decorators import action
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from django.db import transaction
from django.core.exceptions import ValidationError

from borrowings.permissions import IsOwnerOrStaff
from borrowings.serializers import (
    BorrowingCreateSerializer,
    BorrowingListSerializer,
    BorrowingDetailSerializer,
)
from users.authentication import AuthorizeHeaderJWTAuthentication
from borrowings.models import Borrowing


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

        return qs.order_by("-borrow_date")

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
        response_serializer = BorrowingDetailSerializer(borrowing)
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
            BorrowingDetailSerializer(borrowing).data,
            status=status.HTTP_200_OK
        )
