from django.conf import settings
from django.db import transaction
from django.db.models import Count
from django.http import HttpResponseRedirect
from django.utils import timezone
from drf_spectacular.utils import extend_schema
from rest_framework import serializers, viewsets, mixins
from rest_framework.decorators import action
from rest_framework.exceptions import ValidationError
from rest_framework.response import Response
from accounts.employee_admin import EmployeeAdminPermission
from common.serializers import StrictInputMixin
from .models import GoogleConnection, GoogleSyncJob, GoogleSyncItem, GoogleOAuthAttempt
from . import services, provider


class ConnectionStatusSerializer(serializers.Serializer):
    configured = serializers.BooleanField()
    configuration_errors = serializers.ListField(child=serializers.CharField())
    state = serializers.CharField()
    email = serializers.CharField()
    automatic = serializers.BooleanField()
    interval_minutes = serializers.IntegerField()
    last_success_at = serializers.DateTimeField(allow_null=True)
    last_worker_at = serializers.DateTimeField(allow_null=True)
    worker_stale = serializers.BooleanField()
    last_error = serializers.CharField()
    callback_url = serializers.CharField()
    crm_origin = serializers.CharField()


class ConnectionSettingsInput(StrictInputMixin, serializers.Serializer):
    automatic = serializers.BooleanField()
    interval_minutes = serializers.IntegerField(min_value=5, max_value=1440, default=15)


class AuthorizationURLSerializer(serializers.Serializer):
    authorization_url = serializers.URLField()


class SyncJobSerializer(serializers.ModelSerializer):
    counts = serializers.SerializerMethodField()
    actor_name = serializers.CharField(source='actor.username', read_only=True, allow_null=True)

    def get_counts(self, obj) -> dict:
        field = 'action' if obj.status == 'preview' else 'status'
        return {row[field]: row['total'] for row in obj.items.values(field).annotate(total=Count('pk'))}

    class Meta:
        model = GoogleSyncJob
        fields = ['id', 'email', 'status', 'automatic', 'actor_name', 'error_code', 'created_at', 'completed_at', 'counts']
        read_only_fields = fields


class GoogleIntegrationViewSet(viewsets.ViewSet):
    permission_classes = [EmployeeAdminPermission]

    @extend_schema(responses=ConnectionStatusSerializer)
    def list(self, request):
        conn = services.connection()
        errors = services.configuration_errors()
        return Response(dict(configured=not errors, configuration_errors=errors, state=conn.state, email=conn.email,
            automatic=conn.automatic, interval_minutes=conn.interval_minutes, last_success_at=conn.last_success_at, last_worker_at=conn.last_worker_at,
            worker_stale=not conn.last_worker_at or (timezone.now()-conn.last_worker_at).total_seconds() > 180,
            last_error=conn.last_error, callback_url=settings.GOOGLE_CONTACTS_REDIRECT_URI or 'http://127.0.0.1:3100/api/v1/integrations/google-contacts/callback/',
            crm_origin=settings.GOOGLE_CONTACTS_CRM_ORIGIN))

    @extend_schema(request=None, responses=AuthorizationURLSerializer)
    @action(detail=False, methods=['post'])
    def connect(self, request):
        return Response({'authorization_url': services.authorization_url(request)})

    @extend_schema(responses={302: None})
    @action(detail=False, methods=['get'])
    def callback(self, request):
        # No raw OAuth code, state or provider error is echoed to the browser.
        outcome = 'connected'
        try:
            services.finish_authorization(request)
        except (provider.GoogleError, ValidationError):
            outcome = 'connection_failed'
        origin = settings.GOOGLE_CONTACTS_CRM_ORIGIN
        if services.configuration_errors():
            return Response({'detail': 'Google Contacts is not configured on this server.'}, status=400)
        response = HttpResponseRedirect(origin.rstrip('/')+'/admin/google-contacts?oauth='+outcome)
        response['Referrer-Policy'] = 'no-referrer'
        response['Cache-Control'] = 'no-store'
        return response

    @extend_schema(request=ConnectionSettingsInput, responses=ConnectionStatusSerializer)
    @action(detail=False, methods=['post'], url_path='settings')
    def configure(self, request):
        form = ConnectionSettingsInput(data=request.data); form.is_valid(raise_exception=True)
        if form.validated_data['automatic']:
            services.require_configuration()
        with transaction.atomic():
            services.connection()
            conn = GoogleConnection.objects.select_for_update().get(pk=1)
            if form.validated_data['automatic'] and conn.state != 'connected':
                raise ValidationError('Connect Google before enabling automatic sync.')
            conn.automatic = form.validated_data['automatic']
            conn.interval_minutes = form.validated_data['interval_minutes']
            if conn.automatic:
                conn.connected_by = request.user
            conn.save(update_fields=['automatic', 'interval_minutes', 'connected_by'])
        return self.list(request)

    @extend_schema(request=None, responses=ConnectionStatusSerializer)
    @action(detail=False, methods=['post'])
    def disconnect(self, request):
        with transaction.atomic():
            services.connection()
            conn = GoogleConnection.objects.select_for_update().get(pk=1)
            if conn.lease_until and conn.lease_until > timezone.now():
                raise ValidationError('A Google operation is active. Disconnect after it finishes.')
            conn.refresh_token_encrypted, conn.state, conn.automatic = '', 'disconnected', False
            conn.save(update_fields=['refresh_token_encrypted', 'state', 'automatic'])
            GoogleSyncJob.objects.filter(status__in=['queued', 'running']).update(status='cancelled', error_code='disconnected')
            GoogleOAuthAttempt.objects.filter(used_at__isnull=True).update(used_at=timezone.now(), verifier_encrypted='')
        return self.list(request)

    @extend_schema(request=None, responses=SyncJobSerializer)
    @action(detail=False, methods=['post'])
    def preview(self, request):
        try:
            job = services.preview(actor=request.user)
        except provider.GoogleError as error:
            raise ValidationError({'google': error.code}) from None
        return Response(SyncJobSerializer(job).data, status=201)


class GoogleSyncJobViewSet(viewsets.ReadOnlyModelViewSet):
    permission_classes = [EmployeeAdminPermission]
    serializer_class = SyncJobSerializer
    queryset = GoogleSyncJob.objects.select_related('actor').all()

    @extend_schema(request=None, responses=SyncJobSerializer)
    @action(detail=True, methods=['post'])
    def start(self, request, pk=None):
        return Response(SyncJobSerializer(services.start_job(self.get_object(), request.user)).data)


class GoogleSyncItemSerializer(serializers.ModelSerializer):
    contact_name = serializers.CharField(source='contact.full_name')
    contact_label = serializers.CharField(source='contact.contact_id')

    class Meta:
        model = GoogleSyncItem
        fields = ['id', 'job', 'contact', 'contact_name', 'contact_label', 'action', 'status', 'reason', 'payload', 'candidates']
        read_only_fields = fields


class GoogleLinkApprovalInput(StrictInputMixin, serializers.Serializer):
    resource_name = serializers.RegexField(r'^people/[A-Za-z0-9_-]{1,200}$')
    confirm_replace_managed_fields = serializers.BooleanField()

    def validate_confirm_replace_managed_fields(self, value):
        if not value:
            raise serializers.ValidationError('Confirm that the selected Google contact’s CRM-managed fields will be replaced on the next approved sync.')
        return value


class GoogleSyncItemViewSet(mixins.ListModelMixin, mixins.RetrieveModelMixin, viewsets.GenericViewSet):
    permission_classes = [EmployeeAdminPermission]
    serializer_class = GoogleSyncItemSerializer

    def get_queryset(self):
        rows = GoogleSyncItem.objects.select_related('contact', 'job').all()
        if job := self.request.query_params.get('job'):
            rows = rows.filter(job_id=serializers.UUIDField().run_validation(job))
        return rows

    @extend_schema(request=GoogleLinkApprovalInput, responses=GoogleSyncItemSerializer)
    @action(detail=True, methods=['post'], url_path='approve-link')
    def approve_link(self, request, pk=None):
        form = GoogleLinkApprovalInput(data=request.data); form.is_valid(raise_exception=True)
        item = self.get_object()
        try:
            services.approve_existing(item, form.validated_data['resource_name'], request.user)
        except provider.GoogleError as error:
            raise ValidationError({'google': error.code}) from None
        item.refresh_from_db()
        return Response(self.get_serializer(item).data)
