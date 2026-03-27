from rest_framework import viewsets, status
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated
from django.shortcuts import get_object_or_404

from borrowings.models import Borrowing
from borrowings.serializers import (
    BorrowingListSerializer,
    BorrowingDetailSerializer, BorrowingCreateSerializer,
)


class BorrowingViewSet(viewsets.ModelViewSet):
    queryset = Borrowing.objects.all()
    permission_classes = [IsAuthenticated]

    def get_serializer_class(self):
        """Return different serializers based on action"""
        if self.action == 'list':
            return BorrowingListSerializer
        elif self.action == 'retrieve':
            return BorrowingDetailSerializer

        return BorrowingCreateSerializer

    def destroy(self, request, *args, **kwargs):
        """Prevent deletion of borrowings"""
        return Response(
            {"error": "Deleting borrowings is not allowed."},
            status=status.HTTP_405_METHOD_NOT_ALLOWED
        )

    @action(detail=True, methods=['post'])
    def return_book(self, request, pk=None):
        """Custom action to return a borrowed book"""
        borrowing = self.get_object()

        if borrowing.is_returned:
            return Response(
                {"error": "Book has already been returned."},
                status=status.HTTP_400_BAD_REQUEST
            )

        try:
            borrowing.return_book()
            serializer = BorrowingDetailSerializer(borrowing)
            return Response(serializer.data, status=status.HTTP_200_OK)
        except Exception as e:
            return Response(
                {"error": str(e)},
                status=status.HTTP_400_BAD_REQUEST
            )
