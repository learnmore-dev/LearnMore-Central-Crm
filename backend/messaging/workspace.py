from urllib.parse import urlsplit, urlunsplit, parse_qsl, urlencode
from django.conf import settings
from django.db import transaction
from rest_framework import serializers, mixins, viewsets
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.views import APIView
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


class WorkspaceSettings(APIView):
    permission_classes = [InboxPermission]

    @extend_schema(responses=SettingsSerializer)
    def get(self, request):
        return Response({'mode': settings.WHATSAPP_MODE, 'live_sends_enabled': settings.WHATSAPP_LIVE_SENDS_ENABLED,
            'bulk_sends_enabled': False, 'access_token_configured': bool(settings.WHATSAPP_ACCESS_TOKEN),
            'app_secret_configured': bool(settings.WHATSAPP_APP_SECRET), 'verify_token_configured': bool(settings.WHATSAPP_VERIFY_TOKEN),
            'graph_version': settings.WHATSAPP_GRAPH_VERSION, 'webhook_path': '/api/v1/whatsapp/webhook/'})
