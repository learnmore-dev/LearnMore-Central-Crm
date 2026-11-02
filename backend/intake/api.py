import hashlib
import hmac
import json
import re
import time
from urllib.parse import urlsplit
from django.conf import settings
from rest_framework import serializers, mixins, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import ValidationError
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework.throttling import ScopedRateThrottle
from drf_spectacular.utils import extend_schema
from common.access import branch_scope, visible_contacts
from common.permissions import CRMRecordPermissions
from common.serializers import StrictInputMixin
from contacts.normalization import normalize_phone
from contacts.models import Contact
from .models import WebsiteSource, WebsiteSubmission
from . import services


class SubmissionInput(StrictInputMixin, serializers.Serializer):
    submission_id = serializers.RegexField(r'^[A-Za-z0-9_-]{1,100}$')
    full_name = serializers.CharField(max_length=200)
    phone = serializers.CharField(max_length=40, required=False, allow_blank=True, default='')
    email = serializers.EmailField(required=False, allow_blank=True, default='')
    course = serializers.CharField(max_length=180, required=False, allow_blank=True, default='')
    message = serializers.CharField(max_length=2000, required=False, allow_blank=True, default='')
    page_url = serializers.URLField(max_length=1000, required=False, allow_blank=True, default='')
    form_name = serializers.CharField(max_length=100, required=False, allow_blank=True, default='')
    preferred_branch = serializers.CharField(max_length=100, required=False, allow_blank=True, default='')
    branch_code = serializers.SlugField(max_length=40, required=False, allow_blank=True, default='')
    training_mode = serializers.CharField(max_length=50, required=False, allow_blank=True, default='')
    utm = serializers.DictField(child=serializers.CharField(max_length=200), required=False, default=dict)

    def validate(self, attrs):
        from django.core.exceptions import ValidationError as DjangoValidationError
        if not attrs['phone'] and not attrs['email']:
            raise ValidationError('A phone number or email is required.')
        if attrs['phone']:
            try:
                attrs['phone'] = normalize_phone(attrs['phone'])
            except DjangoValidationError:
                raise ValidationError({'phone': 'Enter a valid phone number.'}) from None
        attrs['email'] = attrs['email'].casefold()
        if set(attrs['utm']) - {'source', 'medium', 'campaign', 'term', 'content'}:
            raise ValidationError({'utm': 'Only standard UTM fields are supported.'})
        if attrs['page_url']:
            parsed = urlsplit(attrs['page_url'])
            domain = self.context['source'].domain
            if parsed.scheme != 'https' or parsed.hostname not in (domain, 'www.' + domain) or parsed.username or parsed.password or parsed.port not in (443, None):
                raise ValidationError({'page_url': 'Use an HTTPS page on the submitting website.'})
            # Query parameters may contain customer PII or tracking tokens.
            attrs['page_url'] = parsed._replace(query='', fragment='').geturl()
        return attrs


class ReceiptSerializer(serializers.Serializer):
    received = serializers.BooleanField()
    receipt_id = serializers.UUIDField()


class WebsiteWebhook(APIView):
    authentication_classes = []
    permission_classes = [AllowAny]
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = 'website_intake'

    @extend_schema(request=SubmissionInput, responses={202: ReceiptSerializer}, auth=[])
    def post(self, request, site):
        secret = settings.WEBSITE_INTAKE_SECRETS.get(site, '')
        timestamp = request.headers.get('X-Website-Timestamp', '')
        signature = request.headers.get('X-Website-Signature', '')
        if not secret:
            return Response({'detail': 'Website intake is not configured.'}, status=503)
        if not re.fullmatch(r'[0-9]{10,11}', timestamp) or abs(time.time() - int(timestamp)) > 300:
            return Response({'detail': 'Invalid or expired signature.'}, status=403)
        if len(request.body) > 16_384:
            return Response({'detail': 'Form payload is too large.'}, status=413)
        expected = 'sha256=' + hmac.new(secret.encode(), f'{site}.{timestamp}.'.encode() + request.body, hashlib.sha256).hexdigest()
        if not re.fullmatch(r'sha256=[0-9a-f]{64}', signature) or not hmac.compare_digest(expected, signature):
            return Response({'detail': 'Invalid or expired signature.'}, status=403)
        source = WebsiteSource.objects.filter(slug=site, is_active=True).first()
        if not source:
            return Response({'detail': 'Website intake is not configured.'}, status=503)
        try:
            data = json.loads(request.body)
        except (ValueError, UnicodeDecodeError):
            return Response({'detail': 'Invalid JSON.'}, status=400)
        form = SubmissionInput(data=data, context={'source': source})
        form.is_valid(raise_exception=True)
        submission, _ = services.receive_submission(source, form.validated_data)
        # Public receipt never discloses contact IDs, matches, owners or lead status.
        return Response({'received': True, 'receipt_id': submission.pk}, status=202)


class SubmissionSerializer(serializers.ModelSerializer):
    website = serializers.CharField(source='source.domain', read_only=True)
    branch_name = serializers.CharField(source='branch.name', read_only=True)
    lead_label = serializers.CharField(source='lead.lead_id', read_only=True, allow_null=True)
    owner_name = serializers.SerializerMethodField()
    candidates = serializers.SerializerMethodField()

    def get_owner_name(self, obj) -> str | None:
        return (obj.lead.owner.get_full_name() or obj.lead.owner.username) if obj.lead_id and obj.lead.owner_id else None

    def get_candidates(self, obj) -> list[dict]:
        if not obj.review_id:
            return []
        return list(visible_contacts(self.context['request'].user).filter(duplicate_reviews=obj.review).values('id', 'full_name', 'contact_id'))

    class Meta:
        model = WebsiteSubmission
        fields = ['id', 'website', 'full_name', 'phone', 'email', 'course', 'message', 'page_url', 'form_name',
            'preferred_branch', 'training_mode', 'utm', 'branch', 'branch_name', 'status', 'lead', 'lead_label', 'owner_name', 'review', 'candidates', 'created_at']
        read_only_fields = fields


class ResolveInput(StrictInputMixin, serializers.Serializer):
    decision = serializers.ChoiceField(choices=['linked', 'separate', 'rejected'])
    reason = serializers.CharField(max_length=2000)
    contact = serializers.PrimaryKeyRelatedField(queryset=Contact.objects.none(), required=False)

    def get_fields(self):
        fields = super().get_fields()
        if self.context.get('request'):
            fields['contact'].queryset = visible_contacts(self.context['request'].user)
        return fields


class WebsiteSubmissionViewSet(mixins.ListModelMixin, mixins.RetrieveModelMixin, viewsets.GenericViewSet):
    serializer_class = SubmissionSerializer
    permission_classes = [CRMRecordPermissions]

    def get_queryset(self):
        rows = branch_scope(WebsiteSubmission.objects.select_related('source', 'branch', 'lead__owner', 'review'), self.request.user)
        if self.request.query_params.get('submission'):
            rows = rows.filter(pk=serializers.UUIDField().run_validation(self.request.query_params['submission']))
        if self.request.query_params.get('status'):
            value = serializers.ChoiceField(choices=WebsiteSubmission.Status.choices).run_validation(self.request.query_params['status'])
            rows = rows.filter(status=value)
        return rows

    @extend_schema(request=ResolveInput, responses=SubmissionSerializer)
    @action(detail=True, methods=['post'])
    def resolve(self, request, pk=None):
        submission = self.get_object()
        form = ResolveInput(data=request.data, context=self.get_serializer_context())
        form.is_valid(raise_exception=True)
        result = services.resolve_submission(actor=request.user, submission=submission, **form.validated_data)
        return Response(self.get_serializer(result).data)
