import hashlib
import json
from django.db import transaction
from rest_framework.exceptions import ValidationError
from activities.models import Activity
from common.access import require_branch, require_manager
from common.identifiers import lock_sequence
from contacts.models import DuplicateReview
from contacts.services import prepare_identifiers, candidates_for, create_contact, resolve_review
from leads.services import create_lead
from .models import CallLog


def record_activity(call, actor):
    Activity.objects.create(contact=call.contact, branch=call.branch, actor=actor, kind='note',
        body=f'{call.direction.capitalize()} call: {call.status}. Caller {call.caller_phone}. '
             f'Time {call.started_at.isoformat()}. Duration {call.duration_seconds}s. '
             f'Forwarded to: {call.forwarded_to or "Not specified"}. {call.notes}'[:4000])


@transaction.atomic
def record_call(*, actor, **data):
    require_branch(actor, data['branch'])
    digest = hashlib.sha256(json.dumps({k: str(v.pk) if hasattr(v, 'pk') else v.isoformat() if hasattr(v, 'isoformat') else v
        for k, v in data.items()}, sort_keys=True).encode()).hexdigest()
    # Serialize identity matching and retries under the existing global identity gate.
    lock_sequence('contact')
    existing = CallLog.objects.filter(branch=data['branch'], client_key=data['client_key']).first()
    if existing:
        if existing.request_hash != digest:
            raise ValidationError('This client_key was already used for a different call.')
        return existing
    identifiers = prepare_identifiers([{'kind': 'phone', 'value': data['caller_phone']}])
    candidates = list(candidates_for(identifiers)[:2])
    contact, review = None, None
    if len(candidates) == 1 and candidates[0].branch_id == data['branch'].pk:
        contact = candidates[0]
    else:
        result = create_contact(actor=actor, full_name=data.get('caller_name') or 'Caller ' + data['caller_phone'],
            branch=data['branch'], source='call', identifiers=[{'kind': 'phone', 'value': data['caller_phone']}])
        if isinstance(result, DuplicateReview):
            review = result
        else:
            contact = result
    call = CallLog.objects.create(**data, request_hash=digest, contact=contact, review=review, created_by=actor)
    if contact:
        record_activity(call, actor)
    return call


@transaction.atomic
def resolve_contact(*, actor, call, decision, reason, contact=None):
    require_manager(actor, call.branch)
    call = CallLog.objects.select_for_update(of=('self',)).select_related('review', 'branch').get(pk=call.pk)
    if call.contact_id or not call.review_id:
        raise ValidationError('This call does not need contact review.')
    review = call.review
    if review.status == 'pending':
        review = resolve_review(actor=actor, review=review, decision=decision, reason=reason, contact=contact)
    elif review.status != decision or (decision == 'linked' and review.resolved_contact_id != getattr(contact, 'pk', None)):
        raise ValidationError('This identity review was already resolved differently.')
    if review.resolved_contact_id:
        call.contact = review.resolved_contact
        call.save(update_fields=['contact'])
        record_activity(call, actor)
    return call


@transaction.atomic
def create_enquiry(*, actor, call, title):
    require_branch(actor, call.branch)
    call = CallLog.objects.select_for_update(of=('self',)).select_related('contact', 'branch', 'lead').get(pk=call.pk)
    if call.lead_id:
        return call  # repeated clicks cannot create a second enquiry
    if not call.contact_id:
        raise ValidationError('Resolve the caller contact before creating an enquiry.')
    if not title.strip() or len(title) > 200:
        raise ValidationError({'title': 'Supply an enquiry title of up to 200 characters.'})
    call.lead = create_lead(actor=actor, branch=call.branch, contact=call.contact, source='call', title=title.strip(),
        received_at=call.started_at, received_via='call_started')
    call.save(update_fields=['lead'])
    Activity.objects.create(contact=call.contact, lead=call.lead, branch=call.branch, actor=actor, kind='note',
        body=f'Enquiry created from {call.status} {call.direction} call on {call.started_at.isoformat()}. '
             f'Forwarded to: {call.forwarded_to or "Not specified"}. {call.notes}'[:4000])
    return call
