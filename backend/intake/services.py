import hashlib
import json
from django.db import transaction
from rest_framework.exceptions import ValidationError
from activities.models import Activity
from common.access import require_branch, require_manager
from contacts.models import DuplicateReview
from contacts.services import create_contact, resolve_review
from leads.services import create_lead
from .models import WebsiteSource, WebsiteSubmission


def create_submission_lead(submission, contact, actor):
    title = submission.course or 'Website enquiry'
    lead = create_lead(actor=actor, branch=submission.branch, contact=contact, title=title, source='website',
        received_at=submission.created_at, received_via='website_received')
    details = [f'Website: {submission.source.domain}', f'Form: {submission.form_name or "enquiry"}']
    for label, value in [('Course', submission.course), ('Message', submission.message), ('Page', submission.page_url),
                         ('Preferred branch', submission.preferred_branch), ('Training mode', submission.training_mode)]:
        if value:
            details.append(f'{label}: {value}')
    Activity.objects.create(contact=contact, lead=lead, branch=submission.branch, actor=actor, kind='note', body='\n'.join(details)[:4000])
    return lead


@transaction.atomic
def receive_submission(source, data):
    source = WebsiteSource.objects.select_for_update(of=('self',)).select_related('default_branch', 'actor').get(pk=source.pk)
    if not source.is_active:
        raise ValidationError('Website intake is disabled.')
    digest = hashlib.sha256(json.dumps(data, sort_keys=True, separators=(',', ':')).encode()).hexdigest()
    existing = WebsiteSubmission.objects.filter(source=source, submission_id=data['submission_id']).first()
    if existing:
        if existing.request_hash != digest:
            raise ValidationError('This submission_id was used for different form data.')
        return existing, False
    branch = source.default_branch
    branch_code = data.get('branch_code', '')
    if branch_code:
        if branch_code != branch.code:
            branch = source.allowed_branches.filter(code=branch_code, is_active=True).first()
            if not branch:
                raise ValidationError({'branch_code': 'Choose an enabled branch for this website.'})
    require_branch(source.actor, branch)
    identifiers = ([{'kind': 'phone', 'value': data['phone']}] if data.get('phone') else []) + (
        [{'kind': 'email', 'value': data['email']}] if data.get('email') else [])
    result = create_contact(actor=source.actor, full_name=data['full_name'], branch=branch, source='website', identifiers=identifiers)
    submission = WebsiteSubmission.objects.create(source=source, request_hash=digest, branch=branch,
        **{key: value for key, value in data.items() if key != 'branch_code'},
        status='review' if isinstance(result, DuplicateReview) else 'created',
        review=result if isinstance(result, DuplicateReview) else None)
    if not submission.review_id:
        submission.lead = create_submission_lead(submission, result, source.actor)
        submission.save(update_fields=['lead'])
    return submission, True


@transaction.atomic
def resolve_submission(*, actor, submission, decision, reason, contact=None):
    require_manager(actor, submission.branch)
    submission = WebsiteSubmission.objects.select_for_update(of=('self',)).select_related('review', 'source', 'branch').get(pk=submission.pk)
    if submission.status != 'review':
        raise ValidationError('This website enquiry does not need identity review.')
    review = submission.review
    if review.status == 'pending':
        review = resolve_review(actor=actor, review=review, decision=decision, reason=reason, contact=contact)
    elif review.status != decision or (decision == 'linked' and review.resolved_contact_id != getattr(contact, 'pk', None)):
        raise ValidationError('The identity review was already resolved differently.')
    if review.status == 'rejected':
        submission.status = 'rejected'
    else:
        submission.lead = create_submission_lead(submission, review.resolved_contact, actor)
        submission.status = 'created'
    submission.save(update_fields=['status', 'lead'])
    return submission
