from urllib.parse import urlsplit, urlunsplit, parse_qsl, urlencode
from django.conf import settings
from django.db import transaction
from rest_framework import serializers, mixins, viewsets
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework.throttling import UserRateThrottle
from drf_spectacular.utils import extend_schema
from branches.models import Branch
from common.access import branch_scope, require_manager
from common.permissions import has_global_scope
from common.serializers import StrictInputMixin
from .api import InboxPermission
from .models import Channel, Conversation, Template, Campaign, CannedMessage, AdDraft
from . import services


class ManagerWrites(InboxPermission):
    def has_permission(self, request, view):
        return super().has_permission(request, view) and (request.method in ('GET', 'HEAD', 'OPTIONS') or
            has_global_scope(request.user) or request.user.role == 'branch_manager')


class CannedSerializer(StrictInputMixin, serializers.ModelSerializer):
    branch_name = serializers.CharField(source='branch.name', read_only=True)

    class Meta:
        model = CannedMessage
        fields = ['id', 'branch', 'branch_name', 'title', 'body', 'is_active']
        read_only_fields = ['id']

    def get_fields(self):
        fields = super().get_fields()
        request = self.context.get('request')
        fields['branch'].queryset = branch_scope(Branch.objects.filter(is_active=True), request.user, 'pk') if request else Branch.objects.none()
        if self.instance:
            fields['branch'].read_only = True
        return fields

    def validate(self, attrs):
        require_manager(self.context['request'].user, self.instance.branch if self.instance else attrs['branch'])
        return attrs


class CannedViewSet(mixins.ListModelMixin, mixins.CreateModelMixin, mixins.UpdateModelMixin, viewsets.GenericViewSet):
    serializer_class = CannedSerializer
    permission_classes = [ManagerWrites]

    def get_queryset(self):
        rows = branch_scope(CannedMessage.objects.select_related('branch'), self.request.user)
        if self.request.query_params.get('branch'):
            rows = rows.filter(branch_id=serializers.UUIDField().run_validation(self.request.query_params['branch']))
        if self.request.query_params.get('active') == 'true':
            rows = rows.filter(is_active=True)
        return rows


class CampaignSerializer(StrictInputMixin, serializers.ModelSerializer):
    channel_name = serializers.CharField(source='channel.name', read_only=True)
    template_name = serializers.CharField(source='template.name', read_only=True)
    recipients = serializers.PrimaryKeyRelatedField(queryset=Conversation.objects.none(), many=True)
    progress = serializers.SerializerMethodField()

    class Meta:
        model = Campaign
        fields = ['id', 'name', 'channel', 'channel_name', 'template', 'template_name', 'parameters', 'recipients', 'status', 'progress', 'created_at']
        read_only_fields = ['id', 'status', 'created_at']

    def get_progress(self, obj) -> dict:
        rows = obj.messages.all()
        return {'total': rows.count(), 'sent': rows.filter(queue_status='sent').count(),
            'pending': rows.filter(queue_status__in=['queued', 'retry', 'sending']).count(),
            'blocked': rows.filter(queue_status__in=['blocked', 'failed', 'unknown']).count()}

    def get_fields(self):
        fields = super().get_fields()
        request = self.context.get('request')
        if request:
            fields['channel'].queryset = branch_scope(Channel.objects.all(), request.user)
            fields['template'].queryset = branch_scope(Template.objects.all(), request.user, 'channel__branch_id')
            fields['recipients'].child_relation.queryset = branch_scope(Conversation.objects.all(), request.user, 'channel__branch_id')
        return fields

    def validate(self, attrs):
        channel = attrs['channel']
        require_manager(self.context['request'].user, channel.branch)
        if attrs['template'].channel_id != channel.pk:
            raise serializers.ValidationError('Choose a template from this account.')
        recipients = attrs['recipients']
        if not 1 <= len(recipients) <= 200 or len({row.pk for row in recipients}) != len(recipients):
            raise serializers.ValidationError('Select 1–200 distinct conversations.')
        if any(row.channel_id != channel.pk for row in recipients):
            raise serializers.ValidationError('All recipients must belong to this account.')
        parameters = attrs.get('parameters', [])
        if not isinstance(parameters, list) or len(parameters) != attrs['template'].parameter_count or any(
            not isinstance(p, str) or not p.strip() or len(p) > 1024 for p in parameters):
            raise serializers.ValidationError('Supply the template’s text parameters.')
        return attrs

    @transaction.atomic
    def create(self, validated_data):
        recipients = validated_data.pop('recipients')
        campaign = Campaign.objects.create(created_by=self.context['request'].user, **validated_data)
        campaign.recipients.set(recipients)
        return campaign


class CampaignViewSet(mixins.ListModelMixin, mixins.CreateModelMixin, mixins.RetrieveModelMixin, viewsets.GenericViewSet):
    serializer_class = CampaignSerializer
    permission_classes = [ManagerWrites]

    def get_queryset(self):
        return branch_scope(Campaign.objects.select_related('channel', 'template'), self.request.user, 'channel__branch_id')

    @extend_schema(request=None, responses=CampaignSerializer)
    @action(detail=True, methods=['post'], url_path='queue-mock')
    @transaction.atomic
    def queue_mock(self, request, pk=None):
        campaign = self.get_object()
        channel = Channel.objects.select_for_update().get(pk=campaign.channel_id)
        require_manager(request.user, channel.branch)
        campaign = Campaign.objects.select_for_update(of=('self',)).select_related('template').get(pk=campaign.pk)
        if settings.WHATSAPP_MODE != 'mock':
            raise serializers.ValidationError('Campaign queueing is currently simulation-only. Live bulk sends are not enabled.')
        if campaign.status == 'queued':
            return Response(self.get_serializer(campaign).data)
        for conversation in campaign.recipients.order_by('id'):
            message = services.enqueue(actor=request.user, conversation=conversation,
                client_key=f'campaign_{campaign.pk.hex}_{conversation.pk.hex}', template=campaign.template, parameters=campaign.parameters)
            campaign.messages.add(message)
        campaign.status = 'queued'
        campaign.save(update_fields=['status'])
        return Response(self.get_serializer(campaign).data)


class AdSerializer(StrictInputMixin, serializers.ModelSerializer):
    tracking_url = serializers.SerializerMethodField()

    class Meta:
        model = AdDraft
        fields = ['id', 'branch', 'name', 'destination', 'platform', 'campaign_tag', 'notes', 'tracking_url', 'created_at']
        read_only_fields = ['id', 'created_at']

    def get_tracking_url(self, obj) -> str:
        url = urlsplit(obj.destination)
        params = {k: v for k, v in parse_qsl(url.query) if not k.startswith('utm_')}
        params.update(utm_source=obj.platform, utm_medium='paid_social', utm_campaign=obj.campaign_tag)
        return urlunsplit(url._replace(query=urlencode(params)))

    def get_fields(self):
        fields = super().get_fields()
        request = self.context.get('request')
        fields['branch'].queryset = branch_scope(Branch.objects.filter(is_active=True), request.user, 'pk') if request else Branch.objects.none()
        return fields

    def validate(self, attrs):
        require_manager(self.context['request'].user, attrs['branch'])
        url = urlsplit(attrs['destination'])
        if url.scheme != 'https' or url.hostname not in ['learnmoretech.in', 'www.learnmoretech.in', 'learnmoretechnologies.in', 'www.learnmoretechnologies.in'] or url.username or url.password:
            raise serializers.ValidationError('Choose an HTTPS landing page on one of your two websites.')
        return attrs

    def create(self, validated_data):
        return AdDraft.objects.create(created_by=self.context['request'].user, **validated_data)


class AdViewSet(mixins.ListModelMixin, mixins.CreateModelMixin, viewsets.GenericViewSet):
    serializer_class = AdSerializer
    permission_classes = [ManagerWrites]

    def get_queryset(self):
        return branch_scope(AdDraft.objects.all(), self.request.user)


class SettingsSerializer(serializers.Serializer):
    mode = serializers.CharField()
    live_sends_enabled = serializers.BooleanField()
    bulk_sends_enabled = serializers.BooleanField()
    access_token_configured = serializers.BooleanField()
    app_secret_configured = serializers.BooleanField()
    verify_token_configured = serializers.BooleanField()
    graph_version = serializers.CharField()
    webhook_path = serializers.CharField()
    storage_ready = serializers.BooleanField()
    webhook_url = serializers.CharField(allow_blank=True)
    webhook_verified_at = serializers.DateTimeField(allow_null=True)


class CredentialInput(StrictInputMixin, serializers.Serializer):
    graph_version = serializers.RegexField(r'^v[0-9]{1,3}\.[0-9]{1,2}$', max_length=16)
    webhook_url = serializers.URLField(max_length=500, allow_blank=True, required=False)
    access_token = serializers.CharField(max_length=8192, allow_blank=True, required=False, write_only=True)
    app_secret = serializers.CharField(max_length=1024, allow_blank=True, required=False, write_only=True)
    verify_token = serializers.CharField(max_length=1024, allow_blank=True, required=False, write_only=True)

    def validate_webhook_url(self, value):
        parts = urlsplit(value)
        if value and (parts.scheme != 'https' or parts.username or parts.password or parts.query or parts.fragment
                      or parts.path != '/api/v1/whatsapp/webhook/'):
            raise serializers.ValidationError('Use your public HTTPS CRM URL ending in /api/v1/whatsapp/webhook/.')
        return value


class WorkspaceSettings(APIView):
    permission_classes = [InboxPermission]

    @extend_schema(responses=SettingsSerializer)
    def get(self, request):
        from .configuration import readiness
        return Response(readiness())

    @extend_schema(request=CredentialInput, responses=SettingsSerializer)
    @transaction.atomic
    def patch(self, request):
        from .configuration import cipher, readiness, CredentialError
        from .models import WhatsAppConnection
        if not has_global_scope(request.user):
            self.permission_denied(request, message='Only an organization administrator can configure the Meta connection.')
        values = CredentialInput(data=request.data)
        values.is_valid(raise_exception=True)
        data = values.validated_data
        try:
            encryption = cipher()
        except CredentialError:
            raise serializers.ValidationError('Ask your server administrator to configure encrypted credential storage.') from None
        row, _ = WhatsAppConnection.objects.select_for_update().get_or_create(pk=1)
        reset_webhook = False
        for name in ('access_token', 'app_secret', 'verify_token'):
            if data.get(name):
                setattr(row, name + '_encrypted', encryption.encrypt(data[name].encode()).decode())
                reset_webhook = True
        for name in ('graph_version', 'webhook_url'):
            if name in data:
                reset_webhook = reset_webhook or getattr(row, name) != data[name]
                setattr(row, name, data[name])
        if reset_webhook:
            row.webhook_verified_at = None
        row.updated_by = request.user
        row.save()
        return Response(readiness())


class ConnectionInput(StrictInputMixin, serializers.Serializer):
    channel = serializers.UUIDField()


class ConnectionResult(serializers.Serializer):
    connected = serializers.BooleanField()
    code = serializers.CharField()
    detail = serializers.CharField()
    display_phone_number = serializers.CharField(required=False)
    verified_name = serializers.CharField(required=False)


class SetupThrottle(UserRateThrottle):
    scope = 'whatsapp_setup'
    rate = '10/min'


class ConnectionCheck(APIView):
    permission_classes = [InboxPermission]
    throttle_classes = [SetupThrottle]

    @extend_schema(request=ConnectionInput, responses=ConnectionResult)
    def post(self, request):
        from django.shortcuts import get_object_or_404
        from .provider import check_connection, ProviderError
        if not has_global_scope(request.user):
            self.permission_denied(request, message='Only an organization administrator can check the Meta connection.')
        values = ConnectionInput(data=request.data)
        values.is_valid(raise_exception=True)
        channel = get_object_or_404(branch_scope(Channel.objects.filter(is_active=True, branch__is_active=True), request.user, 'branch_id'),
                                    pk=values.validated_data['channel'])
        try:
            return Response(check_connection(channel))
        except ProviderError as error:
            details = {
                'missing_access_token': 'Save an access token before checking the connection.',
                'invalid_graph_configuration': 'Save a valid, supported Graph API version and check the account IDs.',
                'credential_storage_unavailable': 'Saved credentials could not be opened. Ask your administrator to check the encryption key.',
                'phone_number_not_in_account': 'The phone number ID was not found in this WhatsApp Business account.',
                'graph_190': 'Meta rejected the access token. Check whether it has expired or been revoked.',
                'graph_10': 'The token does not have access to this Meta business account.',
                'graph_200': 'The token does not have the required account permissions.',
            }
            return Response({'connected': False, 'code': error.code,
                             'detail': details.get(error.code, 'Meta could not verify the connection. Check the account IDs, token permissions and network, then try again.')})
