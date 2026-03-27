from rest_framework import viewsets

from books.models import Book
from books.serializers import BookSerializer
from books.permissions import IsAdminOrReadOnly
from users.authentication import AuthorizeHeaderJWTAuthentication


class BookViewSet(viewsets.ModelViewSet):
    queryset = Book.objects.all()
    serializer_class = BookSerializer
    authentication_classes = []
    permission_classes = [IsAdminOrReadOnly]
