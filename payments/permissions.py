from rest_framework import permissions


# If you used the generic IsOwnerOrStaff,
# it would fail because Payment doesn’t have .user;
# it’s one level deeper (Payment → Borrowing → User).
class IsOwnerOrStaffForPayments(permissions.BasePermission):
    """
    Permission to only allow owners of a payment or staff to view/edit it.
    Users can only see/create payments for their own borrowings.
    """

    def has_permission(self, request, view):
        # Authenticated users can create payments and list their own
        return request.user and request.user.is_authenticated

    def has_object_permission(self, request, view, obj):
        # Read and write permissions are only allowed to:
        # 1. The owner of the borrowing (the user who borrowed the book)
        # 2. Staff members
        return obj.borrowing.user == request.user or request.user.is_staff
