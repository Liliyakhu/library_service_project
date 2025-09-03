from rest_framework import permissions


class IsAdminOrReadOnly(permissions.BasePermission):
    """
    Only admin users can create/update/delete.
    Read-only for others.
    """

    def has_permission(self, request, view):
        if request.method in permissions.SAFE_METHODS:  # GET, HEAD, OPTIONS
            return True
        return request.user and request.user.is_staff


class IsOwnerOrStaff(permissions.BasePermission):
    """
    Permission to only allow owners of a borrowing or staff to view/edit it.
    """

    def has_permission(self, request, view):
        # Authenticated users can create borrowings and list their own
        return request.user and request.user.is_authenticated

    def has_object_permission(self, request, view, obj):
        # Read and write permissions are only allowed to the owner or staff
        return obj.user == request.user or request.user.is_staff
