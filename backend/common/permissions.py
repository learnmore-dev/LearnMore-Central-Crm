from rest_framework.permissions import BasePermission, SAFE_METHODS

def has_global_scope(user):
    return user.is_authenticated and (user.is_superuser or user.role in ('super_admin', 'management'))

class BranchPermissions(BasePermission):
    def has_permission(self, request, view):
        return request.user.is_authenticated and (request.method in SAFE_METHODS or has_global_scope(request.user))

    def has_object_permission(self, request, view, obj):
        return has_global_scope(request.user) or (request.method in SAFE_METHODS and request.user.branch_id == obj.pk)


class CRMRecordPermissions(BasePermission):
    """All roles may read scoped CRM records; only sales roles may write."""
    def has_permission(self, request, view):
        user = request.user
        return user.is_authenticated and (request.method in SAFE_METHODS or
            has_global_scope(user) or user.role in ('branch_manager', 'counsellor'))
