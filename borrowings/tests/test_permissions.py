from rest_framework.test import APITestCase, APIClient, APIRequestFactory
from rest_framework import permissions
from django.contrib.auth import get_user_model
from django.test import RequestFactory

from borrowings.permissions import IsAdminOrReadOnly, IsOwnerOrStaff


User = get_user_model()


class IsAdminOrReadOnlyTests(APITestCase):
    def setUp(self):
        self.factory = APIRequestFactory()
        self.permission = IsAdminOrReadOnly()
        self.client = APIClient()

        self.admin_user = User.objects.create_user(
            email="admin@example.com", password="adminpass", is_staff=True
        )
        self.regular_user = User.objects.create_user(
            email="user@example.com", password="userpass", is_staff=False
        )

    def test_safe_methods_allowed_for_all(self):
        """GET, HEAD, OPTIONS should be allowed for anyone."""
        for method in permissions.SAFE_METHODS:
            request = self.factory.generic(method, "/")
            request.user = self.regular_user
            self.assertTrue(self.permission.has_permission(request, view=None))

    def test_non_safe_methods_allowed_for_admin_only(self):
        """POST, PUT, PATCH, DELETE should be allowed only for staff users."""
        for method in ["POST", "PUT", "PATCH", "DELETE"]:
            request = self.factory.generic(method, "/")
            request.user = self.admin_user
            self.assertTrue(
                self.permission.has_permission(request, view=None),
                msg=f"Admin should be allowed to perform {method}",
            )

            request.user = self.regular_user
            self.assertFalse(
                self.permission.has_permission(request, view=None),
                msg=f"Non-admin should NOT be allowed to perform {method}",
            )


class DummyBorrowing:
    """Simple dummy object to simulate a model instance with a user field."""

    def __init__(self, user):
        self.user = user


class IsOwnerOrStaffTests(APITestCase):
    def setUp(self):
        self.factory = APIRequestFactory()
        self.permission = IsOwnerOrStaff()

        self.owner = User.objects.create_user(
            email="owner@example.com", password="ownerpass", is_staff=False
        )
        self.other_user = User.objects.create_user(
            email="other@example.com", password="otherpass", is_staff=False
        )
        self.staff = User.objects.create_user(
            email="staff@example.com", password="staffpass", is_staff=True
        )
        self.borrowing = DummyBorrowing(user=self.owner)

    def test_has_permission_authenticated_users_only(self):
        """Authenticated users can list/create their borrowings."""
        request = self.factory.get("/")
        request.user = self.owner
        self.assertTrue(self.permission.has_permission(request, view=None))

        # Anonymous user should be denied
        request.user = None
        self.assertFalse(self.permission.has_permission(request, view=None))

    def test_owner_has_object_permission(self):
        """Owner of borrowing should have object permission."""
        request = self.factory.get("/")
        request.user = self.owner
        self.assertTrue(
            self.permission.has_object_permission(request, None, self.borrowing)
        )

    def test_staff_has_object_permission(self):
        """Staff users should always have object permission."""
        request = self.factory.get("/")
        request.user = self.staff
        self.assertTrue(
            self.permission.has_object_permission(request, None, self.borrowing)
        )

    def test_other_user_denied_object_permission(self):
        """Non-owner, non-staff users should be denied."""
        request = self.factory.get("/")
        request.user = self.other_user
        self.assertFalse(
            self.permission.has_object_permission(request, None, self.borrowing)
        )
