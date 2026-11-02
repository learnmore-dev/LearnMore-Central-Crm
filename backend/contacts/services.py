from django.core.exceptions import ValidationError as DjangoValidationError
from django.db import transaction
from django.db.models import Q
from django.utils import timezone
from rest_framework.exceptions import PermissionDenied, ValidationError
from activities.models import Activity
from common.access import require_branch, require_manager, visible_contacts
from common.identifiers import lock_sequence
from .models import Contact, ContactIdentifier, DuplicateReview
from .normalization import normalize_identifier


def prepare_identifiers(identifiers):
    if not identifiers or len(identifiers) > 20:
        raise ValidationError({'identifiers': 'Supply between 1 and 20 identifiers.'})
    prepared, seen = [], set()
    for item in identifiers:
        try:
            normalized, namespace = normalize_identifier(item['kind'], item['value'], item.get('namespace', ''))
        except DjangoValidationError as error:
            raise ValidationError({'identifiers': error.messages})
        key = (item['kind'], namespace, normalized)
        if key in seen:
            raise ValidationError({'identifiers': 'The same normalized identifier was supplied twice.'})
        seen.add(key)
        prepared.append({'kind': item['kind'], 'value': item['value'].strip(),
                         'namespace': namespace, 'normalized_value': normalized})
    return prepared


def candidates_for(identifiers, exclude=None):
    query = Q(pk__in=[])
    for item in identifiers:
        query |= Q(kind=item['kind'], namespace=item['namespace'], normalized_value=item['normalized_value'])
    matches = ContactIdentifier.objects.filter(query)
    if exclude:
        matches = matches.exclude(contact_id=exclude)
    return Contact.objects.filter(pk__in=matches.values('contact_id'))


def _add_identifiers(contact, identifiers):
    for item in identifiers:
        # Never bulk_create: model save is the normalization boundary too.
        ContactIdentifier.objects.get_or_create(contact=contact, kind=item['kind'],
            namespace=item['namespace'], normalized_value=item['normalized_value'], defaults={'value': item['value']})


def _new_contact(*, full_name, branch, source, identifiers, actor):
    contact = Contact.objects.create(full_name=full_name, branch=branch, source=source, created_by=actor)
    _add_identifiers(contact, identifiers)
    Activity.objects.create(contact=contact, branch=branch, actor=actor,
        kind=Activity.Kind.CONTACT_CREATED, body='Contact created via %s.' % source)
    return contact


def _review(*, full_name, branch, source, identifiers, candidates, actor, target_contact=None):
    review = DuplicateReview.objects.create(full_name=full_name, branch=branch, source=source,
        identifiers=identifiers, created_by=actor, target_contact=target_contact)
    review.candidates.set(candidates)
    return review


@transaction.atomic
def create_contact(*, actor, full_name, branch, source='manual', identifiers):
    require_branch(actor, branch)
    identifiers = prepare_identifiers(identifiers)
    # Global identity gate: matching and insertion are one serialized transaction,
    # including when another transaction has not committed an identical intake yet.
    lock_sequence('contact')
    candidates = candidates_for(identifiers)
    if candidates.exists():
        return _review(full_name=full_name, branch=branch, source=source, identifiers=identifiers,
                       candidates=candidates, actor=actor)
    return _new_contact(full_name=full_name, branch=branch, source=source, identifiers=identifiers, actor=actor)


@transaction.atomic
def add_identifier(*, actor, contact, kind, value, namespace=''):
    require_branch(actor, contact.branch)
    identifiers = prepare_identifiers([{'kind': kind, 'value': value, 'namespace': namespace}])
    lock_sequence('contact')
    item = identifiers[0]
    existing = contact.identifiers.filter(kind=kind, namespace=item['namespace'], normalized_value=item['normalized_value']).first()
    if existing:
        return existing
    candidates = candidates_for(identifiers, exclude=contact.pk)
    if candidates.exists():
        return _review(full_name=contact.full_name, branch=contact.branch, source=contact.source,
                       identifiers=identifiers, candidates=candidates, actor=actor, target_contact=contact)
    _add_identifiers(contact, identifiers)
    Activity.objects.create(contact=contact, branch=contact.branch, actor=actor,
        kind=Activity.Kind.IDENTIFIER_ADDED, body='Added a %s identifier.' % kind)
    return contact.identifiers.get(kind=kind, namespace=item['namespace'], normalized_value=item['normalized_value'])


@transaction.atomic
def update_contact(*, actor, contact, full_name):
    require_branch(actor, contact.branch)
    contact = Contact.objects.select_for_update().get(pk=contact.pk)
    if contact.full_name != full_name:
        contact.full_name = full_name
        contact.save(update_fields=['full_name', 'updated_at'])
        Activity.objects.create(contact=contact, branch=contact.branch, actor=actor,
            kind=Activity.Kind.CONTACT_UPDATED, body='Contact name updated.')
    return contact


@transaction.atomic
def resolve_review(*, actor, review, decision, reason, contact=None):
    require_manager(actor, review.branch)
    if not reason.strip():
        raise ValidationError({'reason': 'An explicit review reason is required.'})
    lock_sequence('contact')
    review = DuplicateReview.objects.select_for_update().get(pk=review.pk)
    if review.status != DuplicateReview.Status.PENDING:
        raise ValidationError({'decision': 'This review has already been resolved.'})
    if decision == 'linked':
        if review.target_contact_id:
            raise ValidationError({'decision': 'An identifier review can only be confirmed separate or rejected.'})
        if contact is None or not review.candidates.filter(pk=contact.pk).exists():
            raise ValidationError({'contact': 'Choose a candidate from this review.'})
        if not visible_contacts(actor).filter(pk=contact.pk).exists():
            raise PermissionDenied('Management must review candidates outside your branch.')
        # Linking an intake never overwrites the contact or appends conflicting IDs.
        # A distinct enquiry is created separately as a new Lead.
    elif decision == 'separate':
        if contact is not None:
            raise ValidationError({'contact': 'Do not supply a contact for a separate-person decision.'})
        external = [item for item in review.identifiers if item['kind'] == 'external']
        if external and candidates_for(external, exclude=review.target_contact_id).exists():
            raise ValidationError({'decision': 'A provider resource ID cannot belong to two contacts.'})
        if review.target_contact_id:
            contact = review.target_contact
            require_branch(actor, contact.branch)
            _add_identifiers(contact, review.identifiers)
        else:
            contact = _new_contact(full_name=review.full_name, branch=review.branch, source=review.source,
                                   identifiers=review.identifiers, actor=review.created_by)
    elif decision == 'rejected':
        if contact is not None:
            raise ValidationError({'contact': 'Do not supply a contact when rejecting intake.'})
    else:
        raise ValidationError({'decision': 'Choose linked, separate or rejected.'})
    review.status, review.reason = decision, reason.strip()
    review.resolved_contact, review.resolved_by, review.resolved_at = contact, actor, timezone.now()
    review.save(update_fields=['status', 'reason', 'resolved_contact', 'resolved_by', 'resolved_at'])
    if contact:
        Activity.objects.create(contact=contact, branch=review.branch, actor=actor,
            kind=Activity.Kind.DUPLICATE_RESOLVED, body='Duplicate review %s: %s. %s' % (review.pk, decision, reason.strip()))
    return review
