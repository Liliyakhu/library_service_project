from rest_framework import permissions


class IsAdminOrReadOnly(permissions.BasePermission):
    """
    Only admin users can create/update/delete.
    Read-only for others, including unauthenticated users.
    """

    def has_permission(self, request, view):

        if request.method in permissions.SAFE_METHODS:  # GET, HEAD, OPTIONS
            return True
        # For write operations, require authenticated admin user
        result = request.user.is_authenticated and request.user.is_staff
        return result
