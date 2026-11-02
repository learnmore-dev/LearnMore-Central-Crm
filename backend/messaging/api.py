import hashlib
import hmac
import json
import re
from django.conf import settings
from django.db import transaction
from django.http import HttpResponse, JsonResponse
from django.utils.decorators import method_decorator
from django.views import View
from django.views.decorators.csrf import csrf_exempt
from rest_framework import mixins, serializers, viewsets
from rest_framework.decorators import action
from rest_framework.permissions import BasePermission, SAFE_METHODS
from rest_framework.response import Response
from rest_framework.validators import UniqueValidator
from drf_spectacular.utils import extend_schema
from branches.models import Branch
from contacts.models import Contact
from contacts.api import ResolveSerializer
from common.access import branch_scope
from common.permissions import has_global_scope
from common.serializers import StrictInputMixin
from common.identifiers import canonical_identifier_search
from common.access import visible_contacts
from accounts.models import User
from leads.models import Lead
from .models import Channel, Conversation, Message, Template, WebhookDelivery
from . import services


@method_decorator(csrf_exempt, name='dispatch')
class WebhookView(View):
    """Meta is authenticated by raw-body HMAC, never a browser session."""
    def get(self, request):
        expected = settings.WHATSAPP_VERIFY_TOKEN
        supplied = request.GET.get('hub.verify_token', '')
        if expected and request.GET.get('hub.mode') == 'subscribe' and hmac.compare_digest(expected.encode(), supplied.encode()):
            return HttpResponse(request.GET.get('hub.challenge', ''), content_type='text/plain')
        return HttpResponse(status=403)

    def post(self, request):
        secret = settings.WHATSAPP_APP_SECRET
        if not secret:
            return HttpResponse(status=503)
        try:
            length = int(request.META.get('CONTENT_LENGTH') or 0)
        except ValueError:
            return HttpResponse(status=400)
        if length > 1_000_000:
            return HttpResponse(status=413)
        raw = request.body
        if len(raw) > 1_000_000:
            return HttpResponse(status=413)
        signature = request.headers.get('X-Hub-Signature-256', '')
        expected = 'sha256=' + hmac.new(secret.encode(), raw, hashlib.sha256).hexdigest()
        if not re.fullmatch(r'sha256=[0-9a-f]{64}', signature) or not hmac.compare_digest(expected, signature):
            return HttpResponse(status=403)
        try:
            payload = json.loads(raw)
            if not isinstance(payload, dict) or payload.get('object') != 'whatsapp_business_account' or not isinstance(payload.get('entry'), list):
                raise ValueError()
        except (ValueError, UnicodeDecodeError):
            return HttpResponse(status=400)
        WebhookDelivery.objects.get_or_create(digest=hashlib.sha256(raw).hexdigest(), defaults={'payload': payload})
        # Beat processes durable receipts; ACK does not depend on Redis availability.
        return JsonResponse({'received': True})


class InboxPermission(BasePermission):
    def has_permission(self, request, view):
        user = request.user
        return user.is_authenticated and user.is_active and (has_global_scope(user) or user.role in ('branch_manager', 'counsellor', 'support'))


class ChannelPermission(InboxPermission):
    def has_permission(self, request, view):
        return super().has_permission(request, view) and (request.method in SAFE_METHODS or has_global_scope(request.user))


class ChannelSerializer(StrictInputMixin, serializers.ModelSerializer):
    branch_name = serializers.CharField(source='branch.name', read_only=True)
    phone_number_id = serializers.RegexField(r'^[0-9]{1,40}$', validators=[UniqueValidator(queryset=Channel.objects.all())])
    waba_id = serializers.RegexField(r'^[0-9]{1,40}$')
    branch = serializers.PrimaryKeyRelatedField(queryset=Branch.objects.filter(is_active=True))
    intake_actor = serializers.PrimaryKeyRelatedField(queryset=User.objects.filter(is_active=True), allow_null=True, required=False)

    class Meta:
        model = Channel
        fields = ['id', 'name', 'branch', 'branch_name', 'phone_number_id', 'waba_id', 'is_active', 'business_phone', 'intake_actor', 'auto_intake']
        read_only_fields = ['id']

    def validate(self, attrs):
        actor = attrs.get('intake_actor', self.instance.intake_actor if self.instance else self.context['request'].user)
        branch = self.instance.branch if self.instance else attrs['branch']
        if actor and not (has_global_scope(actor) or (actor.role == 'branch_manager' and actor.branch_id == branch.pk)):
            raise serializers.ValidationError('Intake actor must manage this branch.')
        if not self.instance:
            attrs.setdefault('intake_actor', actor)
        return attrs

    def validate_business_phone(self, value):
        if not value:
            return ''
        from contacts.normalization import normalize_phone
        from django.core.exceptions import ValidationError as DjangoValidationError
        try:
            return normalize_phone(value)
        except DjangoValidationError:
            raise serializers.ValidationError('Enter a valid public WhatsApp business number.') from None

    def get_fields(self):
        fields = super().get_fields()
        if self.instance:
            for key in ['branch', 'phone_number_id', 'waba_id']:
                fields[key].read_only = True
        return fields


class MockTemplateResult(serializers.Serializer):
    id = serializers.UUIDField()
    mode = serializers.CharField()


class ChannelViewSet(mixins.ListModelMixin, mixins.CreateModelMixin, mixins.UpdateModelMixin, viewsets.GenericViewSet):
    serializer_class = ChannelSerializer
    permission_classes = [ChannelPermission]

    def get_queryset(self):
        return branch_scope(Channel.objects.select_related('branch'), self.request.user)

    @extend_schema(request=None, responses=MockTemplateResult)
    @action(detail=True, methods=['post'], url_path='mock-template')
    def mock_template(self, request, pk=None):
        channel = self.get_object()
        if settings.WHATSAPP_MODE != 'mock':
            raise serializers.ValidationError('Mock templates can only be installed in mock mode. Sync live approvals with the server command.')
        from django.utils import timezone
        template, _ = Template.objects.update_or_create(channel=channel, name='mock_welcome', language='en_US', defaults={
            'provider_id': 'mock-template', 'status': 'APPROVED', 'body': 'Hello {{1}}, how can we help?',
            'parameter_count': 1, 'supported': True, 'source_mode': 'mock', 'synced_at': timezone.now()})
        return Response({'id': str(template.pk), 'mode': 'mock'})


class ConversationSerializer(StrictInputMixin, serializers.ModelSerializer):
    branch_name = serializers.CharField(source='channel.branch.name', read_only=True)
    branch = serializers.UUIDField(source='channel.branch_id', read_only=True)
    channel_name = serializers.CharField(source='channel.name', read_only=True)
    contact_name = serializers.CharField(source='contact.full_name', read_only=True, allow_null=True)
    service_window_open = serializers.SerializerMethodField()
    mode = serializers.SerializerMethodField()
    live_sends_enabled = serializers.SerializerMethodField()
    contact_label = serializers.CharField(source='contact.contact_id', read_only=True, allow_null=True)
    ownership = serializers.SerializerMethodField()
    review_candidates = serializers.SerializerMethodField()

    def get_ownership(self, obj) -> dict:
        lead = obj.lead
        user = self.context['request'].user
        if not lead or (not has_global_scope(user) and lead.branch_id != user.branch_id):
            return {'lead': None, 'lead_label': None, 'owner': None, 'owner_name': None, 'course': None, 'status': None}
        return {'lead': str(lead.pk), 'lead_label': lead.lead_id, 'owner': str(lead.owner_id) if lead.owner_id else None,
            'owner_name': (lead.owner.get_full_name() or lead.owner.username) if lead.owner_id else 'Unassigned / manager queue', 'course': lead.title, 'status': lead.status, 'received_at': lead.received_at.isoformat(), 'received_via': lead.received_via, 'origin_branch_code': lead.origin_branch_code, 'origin_branch_name': lead.origin_branch.name if lead.origin_branch_id else None}

    def get_review_candidates(self, obj) -> list[dict]:
        user = self.context['request'].user
        if not obj.review_id or not (has_global_scope(user) or user.role == 'branch_manager'):
            return []
        return list(visible_contacts(user).filter(pk__in=obj.review.candidates.values('pk')).values('id', 'contact_id', 'full_name'))

    def get_service_window_open(self, obj) -> bool:
        return services.window_open(obj)

    def get_mode(self, obj) -> str:
        return settings.WHATSAPP_MODE

    def get_live_sends_enabled(self, obj) -> bool:
        return settings.WHATSAPP_LIVE_SENDS_ENABLED

    class Meta:
        model = Conversation
        fields = ['id', 'channel', 'channel_name', 'branch', 'branch_name', 'wa_id', 'contact', 'contact_name', 'last_inbound_at',
            'consent', 'consent_evidence', 'consent_at', 'updated_at', 'service_window_open', 'mode', 'live_sends_enabled',
            'contact_label', 'ownership', 'identity_status', 'intake_note', 'review', 'review_candidates']
        read_only_fields = fields


class ConversationInput(StrictInputMixin, serializers.Serializer):
    channel = serializers.PrimaryKeyRelatedField(queryset=Channel.objects.none())
    wa_id = serializers.RegexField(r'^[1-9][0-9]{6,14}$', help_text='International WhatsApp phone number, digits only.')

    def get_fields(self):
        fields = super().get_fields()
        request = self.context.get('request')
        fields['channel'].queryset = branch_scope(Channel.objects.filter(is_active=True), request.user) if request else Channel.objects.none()
        return fields


class ConsentInput(StrictInputMixin, serializers.Serializer):
    state = serializers.ChoiceField(choices=['granted', 'revoked'])
    evidence = serializers.CharField(max_length=1000)


class LinkInput(StrictInputMixin, serializers.Serializer):
    contact = serializers.PrimaryKeyRelatedField(queryset=Contact.objects.none())

    def get_fields(self):
        fields = super().get_fields()
        request = self.context.get('request')
        fields['contact'].queryset = branch_scope(Contact.objects.all(), request.user) if request else Contact.objects.none()
        return fields


class WhatsAppEnquiryInput(StrictInputMixin, serializers.Serializer):
    lead = serializers.PrimaryKeyRelatedField(queryset=Lead.objects.none(), required=False)
    title = serializers.CharField(max_length=200, required=False)

    def get_fields(self):
        fields = super().get_fields()
        fields['lead'].queryset = branch_scope(Lead.objects.all(), self.context['request'].user)
        return fields

    def validate(self, attrs):
        if ('lead' in attrs) == ('title' in attrs):
            raise serializers.ValidationError('Choose an enquiry or supply a new course title, not both.')
        return attrs


class ConversationViewSet(mixins.ListModelMixin, mixins.RetrieveModelMixin, viewsets.GenericViewSet):
    serializer_class = ConversationSerializer
    permission_classes = [InboxPermission]

    def get_queryset(self):
        rows = branch_scope(Conversation.objects.select_related('channel__branch', 'contact', 'lead__owner', 'review'), self.request.user, 'channel__branch_id')
        if self.request.query_params.get('mine') == 'true':
            rows = rows.filter(lead__owner=self.request.user, lead__branch_id=self.request.user.branch_id) if not has_global_scope(self.request.user) else rows.filter(lead__owner=self.request.user)
        if self.request.query_params.get('contact'):
            rows = rows.filter(contact_id=serializers.UUIDField().run_validation(self.request.query_params['contact']))
        if self.request.query_params.get('channel'):
            rows = rows.filter(channel_id=serializers.UUIDField().run_validation(self.request.query_params['channel']))
        if self.request.query_params.get('search'):
            from django.db.models import Q
            search = canonical_identifier_search(self.request.query_params['search'][:200])
            rows = rows.filter(Q(wa_id__icontains=search) | Q(contact__full_name__icontains=search) | Q(contact__contact_id__icontains=search) | Q(lead__lead_id__icontains=search) | Q(lead__legacy_lead_id__icontains=search))
        return rows

    @extend_schema(request=ConversationInput, responses=ConversationSerializer)
    def create(self, request):
        form = ConversationInput(data=request.data, context=self.get_serializer_context())
        form.is_valid(raise_exception=True)
        channel = form.validated_data['channel']
        services.require_messaging(request.user, channel)
        conversation, _ = Conversation.objects.get_or_create(**form.validated_data)
        return Response(self.get_serializer(conversation).data, status=201)

    @extend_schema(request=ConsentInput, responses=ConversationSerializer)
    @action(detail=True, methods=['post'])
    def consent(self, request, pk=None):
        conversation = self.get_object()
        form = ConsentInput(data=request.data)
        form.is_valid(raise_exception=True)
        return Response(self.get_serializer(services.set_consent(actor=request.user, conversation=conversation, **form.validated_data)).data)

    @extend_schema(request=LinkInput, responses=ConversationSerializer)
    @action(detail=True, methods=['post'])
    def link(self, request, pk=None):
        conversation = self.get_object()
        form = LinkInput(data=request.data, context=self.get_serializer_context())
        form.is_valid(raise_exception=True)
        return Response(self.get_serializer(services.link_contact(actor=request.user, conversation=conversation, **form.validated_data)).data)

    @extend_schema(request=ResolveSerializer, responses=ConversationSerializer)
    @action(detail=True, methods=['post'], url_path='resolve-identity')
    def resolve_identity(self, request, pk=None):
        from .intake import resolve_identity
        form = ResolveSerializer(data=request.data, context=self.get_serializer_context())
        form.is_valid(raise_exception=True)
        row = resolve_identity(actor=request.user, conversation=self.get_object(), **form.validated_data)
        return Response(self.get_serializer(row).data)

    @extend_schema(request=None, responses=ConversationSerializer)
    @action(detail=True, methods=['post'], url_path='retry-intake')
    def retry_intake(self, request, pk=None):
        from common.access import require_manager
        from .intake import receive
        row = self.get_object()
        require_manager(request.user, row.channel.branch)
        with transaction.atomic():
            row = Conversation.objects.select_for_update().select_related('channel__branch', 'channel__intake_actor', 'lead', 'contact', 'review').get(pk=row.pk)
            row = receive(row)
        return Response(self.get_serializer(row).data)

    @extend_schema(request=WhatsAppEnquiryInput, responses=ConversationSerializer)
    @action(detail=True, methods=['post'], url_path='enquiry')
    def enquiry(self, request, pk=None):
        from .intake import choose_enquiry
        form = WhatsAppEnquiryInput(data=request.data, context=self.get_serializer_context())
        form.is_valid(raise_exception=True)
        row = choose_enquiry(actor=request.user, conversation=self.get_object(), **form.validated_data)
        return Response(self.get_serializer(row).data)


class TemplateSerializer(serializers.ModelSerializer):
    class Meta:
        model = Template
        fields = ['id', 'channel', 'name', 'language', 'status', 'body', 'parameter_count', 'supported', 'synced_at', 'source_mode']
        read_only_fields = fields


class TemplateViewSet(mixins.ListModelMixin, viewsets.GenericViewSet):
    serializer_class = TemplateSerializer
    permission_classes = [InboxPermission]

    def get_queryset(self):
        rows = branch_scope(Template.objects.all(), self.request.user, 'channel__branch_id')
        if self.request.query_params.get('channel'):
            rows = rows.filter(channel_id=serializers.UUIDField().run_validation(self.request.query_params['channel']))
        return rows


class MessageSerializer(serializers.ModelSerializer):
    template_name = serializers.CharField(source='template.name', read_only=True, allow_null=True)
    recipient = serializers.CharField(source='conversation.wa_id', read_only=True)
    channel_name = serializers.CharField(source='conversation.channel.name', read_only=True)
    actor_name = serializers.CharField(source='created_by.username', read_only=True, allow_null=True)

    class Meta:
        model = Message
        fields = ['id', 'conversation', 'direction', 'kind', 'text', 'template', 'template_name', 'parameters', 'client_key',
            'provider_id', 'mode', 'queue_status', 'delivery_status', 'attempts', 'next_attempt_at', 'error_code', 'occurred_at', 'created_at', 'recipient', 'channel_name', 'actor_name']
        read_only_fields = fields


class MessageInput(StrictInputMixin, serializers.Serializer):
    conversation = serializers.PrimaryKeyRelatedField(queryset=Conversation.objects.none())
    client_key = serializers.RegexField(r'^[A-Za-z0-9_-]{1,100}$')
    text = serializers.CharField(max_length=4096, required=False, allow_blank=True)
    template = serializers.PrimaryKeyRelatedField(queryset=Template.objects.none(), required=False, allow_null=True)
    parameters = serializers.ListField(child=serializers.CharField(max_length=1024), max_length=100, required=False)

    def get_fields(self):
        fields = super().get_fields()
        request = self.context.get('request')
        if request:
            fields['conversation'].queryset = branch_scope(Conversation.objects.all(), request.user, 'channel__branch_id')
            fields['template'].queryset = branch_scope(Template.objects.all(), request.user, 'channel__branch_id')
        return fields


class MessageViewSet(mixins.ListModelMixin, mixins.RetrieveModelMixin, viewsets.GenericViewSet):
    serializer_class = MessageSerializer
    permission_classes = [InboxPermission]

    def get_queryset(self):
        rows = branch_scope(Message.objects.select_related('template', 'conversation__channel'), self.request.user, 'conversation__channel__branch_id')
        if self.request.query_params.get('conversation'):
            rows = rows.filter(conversation_id=serializers.UUIDField().run_validation(self.request.query_params['conversation']))
        if self.request.query_params.get('direction'):
            rows = rows.filter(direction=serializers.ChoiceField(choices=['inbound', 'outbound']).run_validation(self.request.query_params['direction']))
        if self.request.query_params.get('status'):
            rows = rows.filter(queue_status=serializers.ChoiceField(choices=Message.QueueStatus.choices).run_validation(self.request.query_params['status']))
        if self.request.query_params.get('search'):
            rows = rows.filter(conversation__wa_id__icontains=self.request.query_params['search'][:20])
        return rows

    @extend_schema(request=MessageInput, responses=MessageSerializer)
    def create(self, request):
        form = MessageInput(data=request.data, context=self.get_serializer_context())
        form.is_valid(raise_exception=True)
        message = services.enqueue(actor=request.user, **form.validated_data)
        return Response(self.get_serializer(message).data, status=202)
