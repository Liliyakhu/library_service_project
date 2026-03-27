from rest_framework import permissions


class IsAdminOrReadOnly(permissions.BasePermission):
    """
    Only admin users can create/update/delete.
    Read-only for others, including unauthenticated users.
    """

    def has_permission(self, request, view):
        print(f"Permission check: method={request.method}, user={request.user}, authenticated={request.user.is_authenticated}")

        if request.method in permissions.SAFE_METHODS:  # GET, HEAD, OPTIONS
            print("Safe method - allowing access")
            return True

        # For write operations, require authenticated admin user
        result = request.user.is_authenticated and request.user.is_staff
        print(f"Write method - allowing: {result}")
        return result
