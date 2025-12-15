from rest_framework import generics
from rest_framework.permissions import IsAuthenticated, AllowAny
from users.authentication import AuthorizeHeaderJWTAuthentication

from users.serializers import UserSerializer


class CreateUserView(generics.CreateAPIView):
    serializer_class = UserSerializer
    permission_classes = [AllowAny]


class ManageUserView(generics.RetrieveUpdateAPIView):
    serializer_class = UserSerializer
    authentication_classes = (AuthorizeHeaderJWTAuthentication,)
    permission_classes = (IsAuthenticated,)

    def get_object(self):
        return self.request.user
