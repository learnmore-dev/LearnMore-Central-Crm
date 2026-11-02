from django.db.models import Q
from rest_framework.exceptions import PermissionDenied, ValidationError
from .permissions import has_global_scope


def visible_contacts(user):
    from contacts.models import Contact
    if not user.is_authenticated:
        return Contact.objects.none()
    if has_global_scope(user):
        return Contact.objects.all()
    return Contact.objects.filter(Q(branch_id=user.branch_id) | Q(leads__branch_id=user.branch_id)).distinct()


def branch_scope(queryset, user, branch_field='branch_id'):
    if not user.is_authenticated:
        return queryset.none()
    return queryset if has_global_scope(user) else queryset.filter(**{branch_field: user.branch_id})


def require_sales(user):
    if not user.is_authenticated or not user.is_active or not (
            has_global_scope(user) or user.role in ('branch_manager', 'counsellor')):
        raise PermissionDenied('Sales access is required.')


def require_branch(user, branch):
    require_sales(user)
    if not has_global_scope(user) and branch.pk != user.branch_id:
        raise PermissionDenied('You cannot write records in another branch.')
    if not branch.is_active:
        raise ValidationError({'branch': 'Choose an active branch.'})


def require_manager(user, branch):
    require_branch(user, branch)
    if not has_global_scope(user) and user.role != 'branch_manager':
        raise PermissionDenied('Branch manager or management access is required.')
