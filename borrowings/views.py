from rest_framework import viewsets, status
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated
from django.shortcuts import get_object_or_404
from django.contrib.auth import get_user_model


from borrowings.models import Borrowing
from borrowings.serializers import (
    BorrowingListSerializer,
    BorrowingDetailSerializer,
    BorrowingCreateSerializer,
)
from borrowings.permissions import IsOwnerOrStaff


class BorrowingViewSet(viewsets.ModelViewSet):
    queryset = Borrowing.objects.all()
    permission_classes = [IsAuthenticated, IsOwnerOrStaff]

    def get_queryset(self):
        """Filter borrowings based on user role and query parameters"""
        queryset = Borrowing.objects.all()

        # Get query parameters
        is_active = self.request.query_params.get("is_active")
        user_id = self.request.query_params.get("user_id")

        # Apply user filtering based on role
        if self.request.user.is_staff:
            # Admin users can see all borrowings, but can filter by specific user
            if user_id:
                try:
                    user_id = int(user_id)
                    queryset = queryset.filter(user_id=user_id)
                except (ValueError, TypeError):
                    # Invalid user_id, return empty queryset
                    queryset = queryset.none()
        else:
            # Regular users can only see their own borrowings
            queryset = queryset.filter(user=self.request.user)

        # Apply is_active filtering
        if is_active is not None:
            if is_active.lower() in ["true", "1"]:
                # Show only active borrowings (not returned yet)
                queryset = queryset.filter(actual_return_date__isnull=True)
            elif is_active.lower() in ["false", "0"]:
                # Show only returned borrowings
                queryset = queryset.filter(actual_return_date__isnull=False)

        return queryset.order_by("id")

    def get_serializer_class(self):
        """Return different serializers based on action"""
        if self.action == "create":
            return BorrowingCreateSerializer
        elif self.action == "list":
            return BorrowingListSerializer
        elif self.action == "retrieve":
            return BorrowingDetailSerializer

        return BorrowingDetailSerializer

    def create(self, request, *args, **kwargs):
        """Create a new borrowing"""
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        try:
            borrowing = serializer.save()
            # Return the detailed serializer data for the created borrowing
            response_serializer = BorrowingDetailSerializer(borrowing)
            return Response(response_serializer.data, status=status.HTTP_201_CREATED)
        except Exception as e:
            return Response({"error": str(e)}, status=status.HTTP_400_BAD_REQUEST)

    def update(self, request, *args, **kwargs):
        """Prevent updating borrowings (only return action should be allowed)"""
        return Response(
            {"error": "Updating borrowings is not allowed. Use return action instead."},
            status=status.HTTP_405_METHOD_NOT_ALLOWED,
        )

    def partial_update(self, request, *args, **kwargs):
        """Prevent partial updating of borrowings"""
        return Response(
            {"error": "Updating borrowings is not allowed. Use return action instead."},
            status=status.HTTP_405_METHOD_NOT_ALLOWED,
        )

    def destroy(self, request, *args, **kwargs):
        """Prevent deletion of borrowings"""
        return Response(
            {"error": "Deleting borrowings is not allowed."},
            status=status.HTTP_405_METHOD_NOT_ALLOWED,
        )

    @action(detail=True, methods=["post"])
    def return_book(self, request, pk=None):
        """Custom action to return a borrowed book"""
        borrowing = self.get_object()

        if borrowing.is_returned:
            return Response(
                {"error": "Book has already been returned."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        try:
            borrowing.return_book()
            serializer = BorrowingDetailSerializer(borrowing)
            return Response(serializer.data, status=status.HTTP_200_OK)
        except Exception as e:
            return Response({"error": str(e)}, status=status.HTTP_400_BAD_REQUEST)
