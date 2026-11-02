"""Application employee administration; never exposes Django permission flags or hashes."""
from django.contrib.auth import password_validation, update_session_auth_hash
from django.core.exceptions import ValidationError as DjangoValidationError
from django.db import transaction
from django.db.models import Q, Count, F
from rest_framework import mixins, serializers, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import ValidationError, PermissionDenied
from rest_framework.permissions import BasePermission
from rest_framework.response import Response
from drf_spectacular.utils import extend_schema
from branches.models import Branch
from common.identifiers import lock_sequence
from common.serializers import StrictInputMixin
from leads.models import Lead
from routing.models import CounsellorProfile
from django.contrib.sessions.models import Session
from django.utils import timezone
from .models import User, UserAccessEvent


def can_manage_users(user):
    return user.is_authenticated and user.is_active and (user.is_superuser or user.role == User.Role.SUPER_ADMIN)


class EmployeeAdminPermission(BasePermission):
    def has_permission(self, request, view):
        return can_manage_users(request.user)


def validate_password(password, user):
    try:
        password_validation.validate_password(password, user)
    except DjangoValidationError as error:
        raise ValidationError({'password': error.messages}) from None


def revoke_sessions(user):
    keys = [session.pk for session in Session.objects.filter(expire_date__gt=timezone.now()).iterator()
            if session.get_decoded().get('_auth_user_id') == str(user.pk)]
    Session.objects.filter(pk__in=keys).delete()


def lock_admin_request(request):
    lock_sequence('employee_admin')
    request.user.refresh_from_db()
    if not can_manage_users(request.user):
        raise PermissionDenied('Administrator access has changed. Sign in again.')


class EmployeeAdminSerializer(StrictInputMixin, serializers.ModelSerializer):
    password = serializers.CharField(write_only=True, required=False, max_length=1024, trim_whitespace=False)
    branch = serializers.PrimaryKeyRelatedField(queryset=Branch.objects.filter(is_active=True), allow_null=True, required=False)
    branch_name = serializers.CharField(source='branch.name', read_only=True, allow_null=True)
    can_receive_leads = serializers.BooleanField(required=False)
    max_active_leads = serializers.IntegerField(min_value=1, max_value=1000, required=False)
    routing_enabled = serializers.SerializerMethodField()
    capacity = serializers.SerializerMethodField()
    active_enquiries = serializers.SerializerMethodField()
    protected_account = serializers.BooleanField(source='is_superuser', read_only=True)

    class Meta:
        model = User
        fields = ['id', 'username', 'first_name', 'last_name', 'email', 'role', 'branch', 'branch_name', 'is_active',
            'password', 'can_receive_leads', 'max_active_leads', 'routing_enabled', 'capacity', 'active_enquiries', 'protected_account', 'date_joined', 'last_login']
        read_only_fields = ['id', 'date_joined', 'last_login']

    def get_fields(self):
        fields = super().get_fields()
        if isinstance(self.instance, User):
            fields['branch'].queryset = Branch.objects.filter(Q(is_active=True) | Q(pk=self.instance.branch_id))
        return fields

    def get_routing_enabled(self, obj) -> bool:
        profile = getattr(obj, 'counsellor_profile', None)
        return bool(profile and profile.can_receive_leads and profile.is_available and obj.is_active and obj.role in ('counsellor', 'branch_manager'))

    def get_capacity(self, obj) -> int:
        profile = getattr(obj, 'counsellor_profile', None)
        return profile.max_active_leads if profile else 50

    def get_active_enquiries(self, obj) -> int:
        return Lead.objects.filter(owner=obj, status__in=['new', 'contacted', 'qualified']).count()

    def validate_username(self, value):
        duplicates = User.objects.filter(username__iexact=value)
        if self.instance:
            duplicates = duplicates.exclude(pk=self.instance.pk)
        if duplicates.exists():
            raise ValidationError('This username is already in use.')
        return value

    def validate(self, data):
        instance = self.instance
        role = data.get('role', instance.role if instance else User.Role.COUNSELLOR)
        branch = data.get('branch', instance.branch if instance else None)
        active = data.get('is_active', instance.is_active if instance else True)
        if role not in ('super_admin', 'management') and not branch and not (instance and instance.is_superuser):
            raise ValidationError({'branch': 'Choose a branch for this role.'})
        if data.get('can_receive_leads') and (role not in ('counsellor', 'branch_manager') or not active or not branch or not branch.is_active):
            raise ValidationError({'can_receive_leads': 'Automatic assignment requires an active counsellor or manager in an active branch.'})
        if instance is None and not data.get('password'):
            raise ValidationError({'password': 'Set an initial password.'})
        if instance and 'password' in data:
            raise ValidationError({'password': 'Use the separate Reset password action.'})
        if instance:
            changing_access = role != instance.role or getattr(branch, 'pk', None) != instance.branch_id or active != instance.is_active
            actor = self.context['request'].user
            if instance.is_superuser and instance.pk != actor.pk and not actor.is_superuser:
                raise ValidationError('Only a system administrator can edit a protected system account.')
            if instance.pk == actor.pk and changing_access:
                raise ValidationError('You cannot change your own role, branch or active status here.')
            if instance.is_superuser and changing_access:
                raise ValidationError('This is a protected system account. Its access cannot be changed here.')
            removes_ownership = not active or getattr(branch, 'pk', None) != instance.branch_id or (role not in ('counsellor', 'branch_manager') and role != instance.role)
            if removes_ownership:
                count = Lead.objects.filter(owner=instance, status__in=['new', 'contacted', 'qualified']).count()
                if count:
                    raise ValidationError(f'Reassign this employee’s {count} active enquiries before changing branch, removing sales access or deactivating.')
        if not instance:
            candidate = User(**{k: v for k, v in data.items() if k not in ('password', 'can_receive_leads', 'max_active_leads')})
            validate_password(data['password'], candidate)
        return data

    def create(self, data):
        enabled = data.pop('can_receive_leads', False)
        capacity = data.pop('max_active_leads', 50)
        password = data.pop('password')
        user = User(**data)
        user.set_password(password)
        user.save()
        if user.role in ('counsellor', 'branch_manager'):
            CounsellorProfile.objects.create(user=user, is_available=enabled, can_receive_leads=enabled, max_active_leads=capacity)
        UserAccessEvent.objects.create(actor=self.context['request'].user, target=user, action='created',
            detail={'role': user.role, 'branch': str(user.branch_id) if user.branch_id else None, 'active': user.is_active, 'automatic_assignment': enabled})
        return user

    def update(self, user, data):
        enabled = data.pop('can_receive_leads', None)
        capacity = data.pop('max_active_leads', None)
        before = {k: str(getattr(user, k)) for k in data}
        revoke = any(k in data and data[k] != getattr(user, k) for k in ('role', 'branch', 'is_active'))
        for key, value in data.items():
            setattr(user, key, value)
        user.save()
        if revoke:
            revoke_sessions(user)
            # Standalone callbacks return to the manager queue on access changes.
            from automation.models import AutomationTask
            from education.models import DemoTask
            AutomationTask.objects.filter(assignee=user, status__in=['pending', 'escalated']).update(assignee=None)
            DemoTask.objects.filter(assignee=user, status='pending').update(assignee=None)
        profile = getattr(user, 'counsellor_profile', None)
        if user.role in ('counsellor', 'branch_manager') and not profile:
            profile = CounsellorProfile.objects.create(user=user, is_available=False, can_receive_leads=False)
        if profile:
            if enabled is not None:
                profile.is_available = profile.can_receive_leads = enabled
            if capacity is not None:
                profile.max_active_leads = capacity
            if not user.is_active or user.role not in ('counsellor', 'branch_manager'):
                profile.is_available = profile.can_receive_leads = False
            profile.save()
        after = {k: str(getattr(user, k)) for k in data}
        UserAccessEvent.objects.create(actor=self.context['request'].user, target=user, action='updated',
            detail={'before': before, 'after': after, 'automatic_assignment': enabled, 'capacity': capacity})
        return user


class EmployeePasswordInput(StrictInputMixin, serializers.Serializer):
    password = serializers.CharField(write_only=True, max_length=1024, trim_whitespace=False)
    current_password = serializers.CharField(write_only=True, max_length=1024, trim_whitespace=False, required=False)


class PasswordResetResult(serializers.Serializer):
    detail = serializers.CharField()


class EmployeeSummarySerializer(serializers.Serializer):
    total = serializers.IntegerField()
    active = serializers.IntegerField()
    inactive = serializers.IntegerField()
    assignment_ready = serializers.IntegerField()


class EmployeeAdminViewSet(mixins.ListModelMixin, mixins.RetrieveModelMixin, mixins.CreateModelMixin, mixins.UpdateModelMixin, viewsets.GenericViewSet):
    permission_classes = [EmployeeAdminPermission]
    serializer_class = EmployeeAdminSerializer
    http_method_names = ['get', 'post', 'patch', 'head', 'options']

    @extend_schema(responses=EmployeeSummarySerializer)
    @action(detail=False, methods=['get'])
    def summary(self, request):
        users = User.objects.all()
        return Response({'total': users.count(), 'active': users.filter(is_active=True).count(),
            'inactive': users.filter(is_active=False).count(), 'assignment_ready': users.filter(is_active=True,
                role__in=['counsellor', 'branch_manager'], branch__is_active=True,
                counsellor_profile__is_available=True, counsellor_profile__can_receive_leads=True).annotate(
                    open_count=Count('leads', filter=Q(leads__status__in=['new', 'contacted', 'qualified']))
                ).filter(open_count__lt=F('counsellor_profile__max_active_leads')).count()})

    def get_queryset(self):
        rows = User.objects.select_related('branch', 'counsellor_profile').order_by('username')
        if search := self.request.query_params.get('search', '').strip():
            rows = rows.filter(Q(username__icontains=search) | Q(first_name__icontains=search) | Q(last_name__icontains=search) | Q(email__icontains=search))
        if role := self.request.query_params.get('role'):
            rows = rows.filter(role=serializers.ChoiceField(choices=User.Role.choices).run_validation(role))
        if branch := self.request.query_params.get('branch'):
            rows = rows.filter(branch_id=serializers.UUIDField().run_validation(branch))
        if (active := self.request.query_params.get('active')) is not None:
            rows = rows.filter(is_active=serializers.BooleanField().run_validation(active))
        return rows

    @transaction.atomic
    def create(self, request, *args, **kwargs):
        lock_admin_request(request)
        return super().create(request, *args, **kwargs)

    @transaction.atomic
    def partial_update(self, request, *args, **kwargs):
        lock_admin_request(request)
        # Routing takes branch locks before user/profile changes.
        from routing.services import lock_branches
        row = self.get_object()
        branch_ids = [row.branch_id] if row.branch_id else []
        if branch := request.data.get('branch'):
            branch_ids.append(serializers.UUIDField().run_validation(branch))
        lock_branches(branch_ids)
        return super().partial_update(request, *args, **kwargs)

    @extend_schema(request=EmployeePasswordInput, responses=PasswordResetResult)
    @action(detail=True, methods=['post'], url_path='reset-password')
    @transaction.atomic
    def reset_password(self, request, pk=None):
        lock_admin_request(request)
        target = self.get_object()
        if target.is_superuser and target.pk != request.user.pk and not request.user.is_superuser:
            raise ValidationError('Only a system administrator can reset a protected system account.')
        form = EmployeePasswordInput(data=request.data)
        form.is_valid(raise_exception=True)
        if target.pk == request.user.pk and not target.check_password(form.validated_data.get('current_password', '')):
            raise ValidationError({'current_password': 'Enter your current password to change your own password.'})
        validate_password(form.validated_data['password'], target)
        target.set_password(form.validated_data['password'])
        target.save(update_fields=['password'])
        UserAccessEvent.objects.create(actor=request.user, target=target, action='password_reset', detail={'self_service': target.pk == request.user.pk})
        if target.pk == request.user.pk:
            update_session_auth_hash(request, target)
        return Response({'detail': 'Password updated. Other existing sessions are invalidated.'})


class UserAccessEventSerializer(serializers.ModelSerializer):
    actor_name = serializers.CharField(source='actor.username')
    target_name = serializers.CharField(source='target.username')

    class Meta:
        model = UserAccessEvent
        fields = ['id', 'actor_name', 'target_name', 'action', 'detail', 'created_at']
        read_only_fields = fields


class UserAccessEventViewSet(viewsets.ReadOnlyModelViewSet):
    permission_classes = [EmployeeAdminPermission]
    serializer_class = UserAccessEventSerializer

    def get_queryset(self):
        rows = UserAccessEvent.objects.select_related('actor', 'target')
        if target := self.request.query_params.get('target'):
            rows = rows.filter(target_id=serializers.UUIDField().run_validation(target))
        return rows
