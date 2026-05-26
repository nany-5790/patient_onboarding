from rest_framework.permissions import BasePermission


class IsAdminOrClinicalStaff(BasePermission):
    """
    Only allow access to admin users or those in the 'clinical_staff' group.
    """

    def has_permission(self, request, view):
        return (
            request.user.is_staff or
            request.user.groups.filter(name='clinical_staff').exists()
        )
