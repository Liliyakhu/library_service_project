from django.contrib.auth import get_user_model
from rest_framework import permissions
from rest_framework.test import APITestCase, APIRequestFactory

from books.permissions import IsAdminOrReadOnly

User = get_user_model()


class IsAdminOrReadOnlyTestCase(APITestCase):
    def setUp(self):
        User.objects.all().delete()

        self.factory = APIRequestFactory()
        self.permission = IsAdminOrReadOnly()

        # Admin user (is_staff=True)
        self.admin_user = User.objects.create_user(
            email="admin@example.com",
            password="adminpass",
            is_staff=True,
        )

        # Regular (non-admin) user
        self.normal_user = User.objects.create_user(
            email="user@example.com",
            password="userpass",
            is_staff=False,
        )

    def test_safe_methods_are_allowed_for_anyone(self):
        for method in permissions.SAFE_METHODS:
            request = getattr(self.factory, method.lower())("/")
            request.user = None  # anonymous
            self.assertTrue(self.permission.has_permission(request, None))

    def test_unsafe_methods_denied_for_anonymous(self):
        for method in ["POST", "PUT", "PATCH", "DELETE"]:
            request = getattr(self.factory, method.lower())("/")
            request.user = None
            self.assertFalse(self.permission.has_permission(request, None))

    def test_unsafe_methods_denied_for_authenticated_non_admin(self):
        for method in ["POST", "PUT", "PATCH", "DELETE"]:
            request = getattr(self.factory, method.lower())("/")
            request.user = self.normal_user
            self.assertFalse(self.permission.has_permission(request, None))

    def test_unsafe_methods_allowed_for_admin(self):
        for method in ["POST", "PUT", "PATCH", "DELETE"]:
            request = getattr(self.factory, method.lower())("/")
            request.user = self.admin_user
            self.assertTrue(self.permission.has_permission(request, None))
