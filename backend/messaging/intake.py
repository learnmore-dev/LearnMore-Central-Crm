"""Branch-scoped, idempotent WhatsApp identity matching and enquiry routing."""
from django.db import transaction
from django.utils import timezone
from rest_framework.exceptions import ValidationError
from activities.models import Activity
from common.access import require_manager
from common.identifiers import lock_sequence
from common.permissions import has_global_scope
from contacts.models import DuplicateReview
from contacts.services import candidates_for, prepare_identifiers, create_contact, resolve_review
from leads.models import Lead
from leads.services import create_lead
from .models import Conversation

ACTIVE = ['new', 'contacted', 'qualified']


def attach_enquiry(conversation, actor, title=None, selected=None, received_at=None):
    branch = conversation.channel.branch
    if conversation.lead_id and conversation.lead.branch_id == branch.pk and conversation.lead.status in ACTIVE:
        if selected and selected.pk == conversation.lead_id:
            return
        if title and title.strip() == conversation.lead.title:
            return  # retry of the same explicit course-enquiry request
    if conversation.lead_id and not title and selected is None:
        if conversation.lead.branch_id == branch.pk and conversation.lead.status in ACTIVE:
            return
        conversation.lead = None
    if not conversation.contact_id:
        return
    if selected:
        if selected.branch_id != branch.pk or selected.contact_id != conversation.contact_id or selected.status not in ACTIVE:
            raise ValidationError('Choose an active enquiry for this contact in this branch.')
        lead = selected
    else:
        existing = list(Lead.objects.filter(contact_id=conversation.contact_id, branch=branch, status__in=ACTIVE).order_by('-created_at')[:2])
        if len(existing) > 1 and not title:
            conversation.intake_note = 'Multiple active enquiries: a manager must choose the relevant course enquiry.'
            conversation.save(update_fields=['lead', 'intake_note'])
            return
        if existing and not title:
            lead = existing[0]
        else:
            timing = {'received_at': received_at, 'received_via': 'whatsapp_received'} if received_at else {}
            lead = create_lead(actor=actor, branch=branch, contact=conversation.contact,
                source='whatsapp', title=title or 'WhatsApp course enquiry', **timing)
    # Reusing a lead preserves its counsellor, acknowledgement and routing history.
    conversation.lead = lead
    conversation.intake_note = 'Enquiry linked. See its assignment history for ownership.'
    conversation.save(update_fields=['lead', 'intake_note'])
    Activity.objects.create(contact=conversation.contact, lead=lead, branch=branch, actor=actor, kind='note',
        body=f'WhatsApp conversation linked to enquiry {lead.lead_id}. Inbox: {conversation.channel.name}.')


@transaction.atomic
def receive(conversation, profile_name='', received_at=None):
    channel = conversation.channel
    if not channel.auto_intake:
        return conversation
    actor = channel.intake_actor
    if not channel.is_active or not channel.branch.is_active:
        conversation.intake_note = 'Intake paused: business inbox or branch is inactive.'
        conversation.save(update_fields=['intake_note'])
        return conversation
    if not actor or not actor.is_active or not (has_global_scope(actor) or (actor.role == 'branch_manager' and actor.branch_id == channel.branch_id)):
        conversation.identity_status, conversation.intake_note = 'blocked', 'Configure an active intake manager for this business inbox.'
        conversation.save(update_fields=['identity_status', 'intake_note'])
        return conversation
    # Opt-outs are persisted by the receiver but never start new sales work.
    if conversation.consent == 'revoked':
        return conversation
    lock_sequence('contact')
    if conversation.review_id:
        if conversation.review.status == 'rejected':
            conversation.identity_status = 'rejected'
            conversation.save(update_fields=['identity_status'])
            return conversation
        if conversation.review.status == 'pending':
            return conversation
        conversation.contact = conversation.review.resolved_contact
        conversation.identity_status = 'matched' if conversation.review.status == 'linked' else 'new'
        conversation.save(update_fields=['contact', 'identity_status'])
    if not conversation.contact_id:
        identifiers = prepare_identifiers([{'kind': 'phone', 'value': '+' + conversation.wa_id}])
        candidates = list(candidates_for(identifiers)[:2])
        if len(candidates) == 1 and candidates[0].branch_id == channel.branch_id:
            conversation.contact, conversation.identity_status = candidates[0], 'matched'
        else:
            result = create_contact(actor=actor, branch=channel.branch, source='whatsapp',
                full_name=(profile_name.strip()[:200] or 'WhatsApp +' + conversation.wa_id),
                identifiers=[{'kind': 'phone', 'value': '+' + conversation.wa_id}])
            if isinstance(result, DuplicateReview):
                conversation.review, conversation.identity_status = result, 'review'
                conversation.intake_note = 'Existing or shared phone identity needs manager verification before assignment.'
                conversation.save(update_fields=['review', 'identity_status', 'intake_note'])
                return conversation
            conversation.contact, conversation.identity_status = result, 'new'
        conversation.save(update_fields=['contact', 'identity_status'])
    elif conversation.identity_status in ('unlinked', 'blocked', 'new'):
        conversation.identity_status = 'matched'
        conversation.save(update_fields=['identity_status'])
    if received_at is None:
        received_at = conversation.messages.filter(direction='inbound').order_by('occurred_at').values_list('occurred_at', flat=True).first()
    attach_enquiry(conversation, actor, received_at=received_at)
    return conversation


@transaction.atomic
def resolve_identity(*, actor, conversation, decision, reason, contact=None):
    require_manager(actor, conversation.channel.branch)
    lock_sequence('contact')
    conversation = Conversation.objects.select_for_update().select_related('channel__branch', 'review').get(pk=conversation.pk)
    if not conversation.review_id or conversation.contact_id:
        raise ValidationError('This conversation does not need identity review.')
    review = conversation.review
    if review.status == 'pending':
        review = resolve_review(actor=actor, review=review, decision=decision, reason=reason, contact=contact)
    elif review.status != decision or (decision == 'linked' and review.resolved_contact_id != getattr(contact, 'pk', None)):
        raise ValidationError('This identity review was resolved differently.')
    if review.status == 'rejected':
        conversation.identity_status, conversation.intake_note = 'rejected', 'Identity link rejected by manager.'
        conversation.save(update_fields=['identity_status', 'intake_note'])
    else:
        conversation.contact = review.resolved_contact
        conversation.identity_status = 'matched' if decision == 'linked' else 'new'
        conversation.save(update_fields=['contact', 'identity_status'])
        if conversation.consent != 'revoked':
            received_at = conversation.messages.filter(direction='inbound').order_by('occurred_at').values_list('occurred_at', flat=True).first()
            attach_enquiry(conversation, actor, received_at=received_at)
    return conversation


@transaction.atomic
def choose_enquiry(*, actor, conversation, lead=None, title=None):
    require_manager(actor, conversation.channel.branch)
    conversation = Conversation.objects.select_for_update().select_related('channel__branch', 'contact', 'lead').get(pk=conversation.pk)
    if not conversation.contact_id:
        raise ValidationError('Resolve the contact identity before choosing an enquiry.')
    if conversation.consent == 'revoked':
        raise ValidationError('This contact opted out; new follow-up work is blocked.')
    if not lead and not title:
        raise ValidationError('Choose an existing enquiry or provide a new course title.')
    attach_enquiry(conversation, actor, title=title, selected=lead)
    return conversation
