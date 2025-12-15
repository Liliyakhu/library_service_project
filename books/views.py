from drf_spectacular.utils import extend_schema, OpenApiParameter
from rest_framework import viewsets
from rest_framework.permissions import IsAuthenticatedOrReadOnly

from books.models import Book
from books.serializers import BookSerializer
from books.permissions import IsAdminOrReadOnly
from users.authentication import AuthorizeHeaderJWTAuthentication


class BookViewSet(viewsets.ModelViewSet):
    """
    ViewSet for managing books.
    """

    queryset = Book.objects.all()
    serializer_class = BookSerializer
    authentication_classes = [AuthorizeHeaderJWTAuthentication]
    permission_classes = [IsAuthenticatedOrReadOnly, IsAdminOrReadOnly]

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
