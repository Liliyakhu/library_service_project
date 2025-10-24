from drf_spectacular.utils import extend_schema, OpenApiParameter
from rest_framework import viewsets

from books.models import Book
from books.serializers import BookSerializer
from books.permissions import IsAdminOrReadOnly


class BookViewSet(viewsets.ModelViewSet):
    queryset = Book.objects.all()
    serializer_class = BookSerializer
    authentication_classes = []
    permission_classes = [IsAdminOrReadOnly]

    def get_queryset(self):
        """Optimized queryset with proper joins"""
        queryset = Book.objects.all()

        # Filtering by title:
        title = self.request.query_params.get("title")
        if title:
            queryset = queryset.filter(title__icontains=title)

        return queryset.order_by("title")

    @extend_schema(
        parameters=[
            OpenApiParameter(
                "title",
                type=str,
                description="Filter by book title (ex. ?title=option",
            )
        ]
    )
    def list(self, request, *args, **kwargs):
        """Get list of books"""
        return super().list(request, args, **kwargs)
