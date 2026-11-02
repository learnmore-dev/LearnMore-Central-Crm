import base64
import hashlib
import json
import secrets
import uuid
from datetime import timedelta
from urllib.parse import urlencode, urlsplit
from cryptography.fernet import Fernet, InvalidToken
from django.conf import settings
from django.db import transaction
from django.db.models import Q
from django.utils import timezone
from rest_framework.exceptions import ValidationError
from accounts.employee_admin import can_manage_users
from contacts.models import Contact
from contacts.normalization import normalize_phone
from .models import GoogleConnection, GoogleOAuthAttempt, GoogleContactLink, GoogleSyncJob, GoogleSyncItem
from . import provider

CONFIG = ('CLIENT_ID', 'CLIENT_SECRET', 'ENCRYPTION_KEY', 'REDIRECT_URI', 'CRM_ORIGIN')
MANAGED_FIELDS = provider.MANAGED.split(',')


def configuration_errors():
    missing = ['GOOGLE_CONTACTS_'+key for key in CONFIG if not getattr(settings, 'GOOGLE_CONTACTS_'+key, '')]
    if missing:
        return missing
    try:
        Fernet(settings.GOOGLE_CONTACTS_ENCRYPTION_KEY.encode())
        origin, callback = urlsplit(settings.GOOGLE_CONTACTS_CRM_ORIGIN), urlsplit(settings.GOOGLE_CONTACTS_REDIRECT_URI)
        if not origin.hostname or origin.username or origin.password or origin.path not in ('', '/') or origin.query or origin.fragment:
            raise ValueError()
        if origin.scheme != 'https' and not (settings.DEBUG and origin.scheme == 'http' and origin.hostname in ('localhost', '127.0.0.1')):
            raise ValueError()
        if (origin.scheme, origin.netloc) != (callback.scheme, callback.netloc) or callback.path != '/api/v1/integrations/google-contacts/callback/' or callback.query or callback.fragment:
            raise ValueError()
    except (ValueError, TypeError):
        return ['Invalid encryption key, CRM origin or callback URL. Use HTTPS except for local development.']
    return []


def require_configuration():
    if errors := configuration_errors():
        raise ValidationError({'configuration': errors})


def encrypt(value):
    return Fernet(settings.GOOGLE_CONTACTS_ENCRYPTION_KEY.encode()).encrypt(value.encode()).decode()


def decrypt(value):
    try:
        return Fernet(settings.GOOGLE_CONTACTS_ENCRYPTION_KEY.encode()).decrypt(value.encode()).decode()
    except (InvalidToken, ValueError):
        raise provider.GoogleError('google_token_decryption_failed') from None


def digest(value):
    return hashlib.sha256(value.encode()).hexdigest()


def connection():
    return GoogleConnection.objects.get_or_create(pk=1)[0]


def authorization_url(request):
    require_configuration()
    if not request.session.session_key:
        request.session.save()
    state, verifier = secrets.token_urlsafe(32), secrets.token_urlsafe(48)
    GoogleOAuthAttempt.objects.create(digest=digest(state), actor=request.user,
        session_digest=digest(request.session.session_key), verifier_encrypted=encrypt(verifier), expires_at=timezone.now()+timedelta(minutes=10))
    challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b'=').decode()
    return 'https://accounts.google.com/o/oauth2/v2/auth?'+urlencode(dict(client_id=settings.GOOGLE_CONTACTS_CLIENT_ID,
        redirect_uri=settings.GOOGLE_CONTACTS_REDIRECT_URI, response_type='code', scope='openid email '+provider.CONTACT_SCOPE,
        access_type='offline', prompt='consent select_account', state=state, code_challenge=challenge, code_challenge_method='S256'))


def finish_authorization(request):
    require_configuration()
    with transaction.atomic():
        attempt = GoogleOAuthAttempt.objects.select_for_update().filter(digest=digest(request.GET.get('state', ''))).first()
        if not attempt or attempt.used_at or attempt.expires_at < timezone.now() or attempt.actor_id != request.user.pk or attempt.session_digest != digest(request.session.session_key or ''):
            raise ValidationError('Google authorization expired or did not match this browser session. Connect again.')
        verifier = decrypt(attempt.verifier_encrypted)
        attempt.used_at, attempt.verifier_encrypted = timezone.now(), ''
        attempt.save(update_fields=['used_at', 'verifier_encrypted'])
    if request.GET.get('error') or not request.GET.get('code'):
        raise ValidationError('Google connection was cancelled or permission was not granted.')
    request.user.refresh_from_db()
    if not can_manage_users(request.user):
        raise ValidationError('Administrator access has changed. Connect again using an active administrator.')
    tokens = provider.exchange(request.GET['code'], verifier)
    if provider.CONTACT_SCOPE not in tokens.get('scope', '').split() or not tokens.get('refresh_token') or not tokens.get('access_token'):
        raise provider.GoogleError('google_contacts_permission_or_offline_access_missing')
    identity = provider.identity(tokens['access_token'])
    if not identity.get('sub') or not identity.get('email') or identity.get('email_verified') is not True:
        raise provider.GoogleError('google_verified_identity_required')
    expected = settings.GOOGLE_CONTACTS_EXPECTED_EMAIL
    if expected and identity['email'].casefold() != expected.casefold():
        raise provider.GoogleError('google_account_does_not_match_expected_email')
    with transaction.atomic():
        connection()
        conn = GoogleConnection.objects.select_for_update().get(pk=1)
        if conn.lease_until and conn.lease_until > timezone.now():
            raise ValidationError('A sync is active. Try connecting again after it finishes.')
        if conn.state != 'disconnected' and conn.account_id and conn.account_id != identity['sub']:
            raise ValidationError('Disconnect the current Google account before switching accounts.')
        conn.account_id, conn.email = identity['sub'], identity['email']
        conn.refresh_token_encrypted = encrypt(tokens['refresh_token'])
        conn.state, conn.automatic, conn.last_error, conn.connected_by = 'connected', False, '', request.user
        conn.save()


def acquire():
    require_configuration()
    with transaction.atomic():
        connection()
        conn = GoogleConnection.objects.select_for_update().get(pk=1)
        if conn.state != 'connected' or not conn.refresh_token_encrypted:
            raise ValidationError('Connect the shared Google account first.')
        if conn.lease_until and conn.lease_until > timezone.now():
            raise ValidationError('Another Google sync operation is in progress. Try again shortly.')
        lease = uuid.uuid4()
        conn.lease, conn.lease_until = lease, timezone.now()+timedelta(minutes=10)
        conn.save(update_fields=['lease', 'lease_until'])
    return conn, lease


def release(lease):
    GoogleConnection.objects.filter(pk=1, lease=lease).update(lease=None, lease_until=None)


def renew_lease(conn):
    if not GoogleConnection.objects.filter(pk=1, lease=conn.lease).update(lease_until=timezone.now()+timedelta(minutes=10)):
        raise ValidationError('Google operation ownership changed. Retry using a fresh preview.')


def access_token(conn):
    try:
        return provider.refresh(decrypt(conn.refresh_token_encrypted))
    except provider.GoogleError as error:
        GoogleConnection.objects.filter(pk=1).update(last_error=error.code)
        if error.code in ('google_reconnect_required', 'google_token_decryption_failed', 'google_http_401'):
            GoogleConnection.objects.filter(pk=1).update(state='reconnect_required', automatic=False)
        raise


def payload_for(contact, conn):
    phones = sorted({i.normalized_value for i in contact.identifiers.all() if i.kind == 'phone'})
    emails = sorted({i.normalized_value for i in contact.identifiers.all() if i.kind == 'email'})
    leads = list(contact.leads.select_related('branch', 'owner').order_by('received_at', 'id'))
    notes = ['LearnMore Technologies', 'Contact ID: '+contact.contact_id]
    if leads:
        notes.append('First enquiry: '+timezone.localtime(leads[0].received_at).strftime('%d %b %Y, %I:%M %p IST')+(' (CRM recorded)' if leads[0].received_via == 'crm_recorded' else ''))
    for lead in leads[-30:]:
        owner = (lead.owner.get_full_name() or lead.owner.username) if lead.owner_id else 'Unassigned'
        notes.append(f'{lead.lead_id} | {lead.title} | {lead.branch.name} | {owner} | {lead.status}')
    if len(leads) > 30:
        notes.append('More enquiries are available in the CRM profile.')
    url = settings.GOOGLE_CONTACTS_CRM_ORIGIN.rstrip('/')+'/contacts/'+str(contact.pk)
    return dict(names=[{'givenName': contact.full_name+' · '+contact.contact_id}],
        phoneNumbers=[{'value': p, 'type': 'mobile'} for p in phones], emailAddresses=[{'value': e, 'type': 'work'} for e in emails],
        organizations=[{'name': 'LearnMore Technologies'}], biographies=[{'value': '\n'.join(notes), 'contentType': 'TEXT_PLAIN'}],
        urls=[{'value': url, 'type': 'profile'}], userDefined=[{'key': 'lmt_crm_contact', 'value': str(contact.pk)}, {'key': 'lmt_crm_instance', 'value': str(conn.namespace)}])


def fingerprint(person):
    result = {}
    generated = {'metadata', 'formattedType', 'canonicalForm', 'displayName', 'displayNameLastFirst', 'unstructuredName'}
    for field in MANAGED_FIELDS:
        values = []
        for row in person.get(field, []):
            if field == 'userDefined' and not row.get('key', '').startswith('lmt_crm_'):
                continue
            value = {k: v for k, v in row.items() if k not in generated and v not in ('', None)}
            if field == 'phoneNumbers':
                try:
                    value['value'] = normalize_phone(row.get('canonicalForm') or row.get('value', ''))
                except Exception:
                    pass
            if field == 'emailAddresses' and value.get('value'):
                value['value'] = value['value'].casefold()
            values.append(value)
        result[field] = sorted(values, key=lambda v: json.dumps(v, sort_keys=True))
    return digest(json.dumps(result, sort_keys=True, ensure_ascii=False))


def markers(person):
    return {v.get('key'): v.get('value') for v in person.get('userDefined', [])}


def identities(person):
    values = set()
    for phone in person.get('phoneNumbers', []):
        try:
            values.add('p:'+normalize_phone(phone.get('canonicalForm') or phone.get('value', '')))
        except Exception:
            pass
    values.update('e:'+v['value'].strip().casefold() for v in person.get('emailAddresses', []) if v.get('value'))
    return values


def summary_person(person):
    return {'resource_name': person['resourceName'], 'name': (person.get('names') or [{}])[0].get('displayName') or (person.get('names') or [{}])[0].get('givenName', ''),
        'phones': [x.get('value', '') for x in person.get('phoneNumbers', [])], 'emails': [x.get('value', '') for x in person.get('emailAddresses', [])]}


def build_preview(conn, token, actor=None, automatic=False):
    contacts = list(Contact.objects.prefetch_related('identifiers').order_by('pk')[:5001])
    if len(contacts) > 5000:
        raise ValidationError('This integration supports up to 5,000 CRM contacts per sync. No contacts were written.')
    people = provider.list_people(token, heartbeat=lambda: renew_lease(conn))
    by_resource = {p['resourceName']: p for p in people if p.get('resourceName')}
    by_identity, by_marker, crm_identities = {}, {}, {}
    payloads = {}
    for index, contact in enumerate(contacts):
        if index % 100 == 0:
            renew_lease(conn)
        payloads[contact.pk] = payload_for(contact, conn)
    for person in people:
        for value in identities(person):
            by_identity.setdefault(value, set()).add(person['resourceName'])
        custom = markers(person)
        if custom.get('lmt_crm_instance') == str(conn.namespace):
            by_marker.setdefault(custom.get('lmt_crm_contact'), []).append(person)
    for pk, payload in payloads.items():
        for value in identities(payload):
            crm_identities.setdefault(value, set()).add(pk)
    links = {l.contact_id: l for l in GoogleContactLink.objects.filter(account_id=conn.account_id)}
    job = GoogleSyncJob.objects.create(account_id=conn.account_id, email=conn.email, actor=actor, automatic=automatic)
    items = []
    for contact in contacts:
        payload, link = payloads[contact.pk], links.get(contact.pk)
        marked = by_marker.get(str(contact.pk), [])
        found = by_resource.get(link.resource_name) if link and link.resource_name else marked[0] if len(marked) == 1 else None
        action, reason, candidates = 'create', '', []
        if not identities(payload):
            action, reason = 'skip', 'No phone or email to sync.'
        elif any(len(crm_identities[v]) > 1 for v in identities(payload)):
            action, reason = 'review', 'Multiple CRM contacts share a phone or email. Resolve identity before syncing.'
        elif len(marked) > 1:
            action, reason = 'review', 'Multiple Google contacts have this CRM marker.'
        elif found:
            custom = markers(found)
            if custom.get('lmt_crm_contact') and (custom.get('lmt_crm_contact') != str(contact.pk) or custom.get('lmt_crm_instance') != str(conn.namespace)):
                action, reason = 'review', 'Google contact belongs to another CRM identity.'
            elif fingerprint(found) == fingerprint(payload):
                action = 'unchanged'
            elif link and link.remote_hash and fingerprint(found) == link.remote_hash:
                action = 'update' if fingerprint(payload) != link.local_hash else 'unchanged'
            else:
                action, reason = 'review', 'Google contact was edited or has no trusted baseline. Review before replacing CRM-managed fields.'
            candidates = [summary_person(found)]
        elif link and (link.resource_name or link.state == 'uncertain'):
            action, reason = 'review', 'Google contact is missing or a previous creation outcome is unknown. Do not create another copy.'
        else:
            matches = set().union(*(by_identity.get(v, set()) for v in identities(payload)))
            if matches:
                action, reason = 'review', 'Matching personal Google contact found. Select and approve it before linking.'
                candidates = [summary_person(by_resource[v]) for v in sorted(matches)[:10]]
        items.append(GoogleSyncItem(job=job, contact=contact, action=action, reason=reason, payload=payload,
            local_hash=fingerprint(payload), resource_name=found['resourceName'] if found else '', remote_hash=fingerprint(found) if found else '', candidates=candidates))
    GoogleSyncItem.objects.bulk_create(items)
    return job


def preview(actor=None, automatic=False):
    conn, lease = acquire()
    try:
        return build_preview(conn, access_token(conn), actor, automatic)
    except provider.GoogleError as error:
        GoogleConnection.objects.filter(pk=1).update(last_error=error.code)
        GoogleSyncJob.objects.create(account_id=conn.account_id, email=conn.email, actor=actor, status='failed', error_code=error.code)
        raise
    finally:
        release(lease)


@transaction.atomic
def start_job(job, actor=None):
    conn = GoogleConnection.objects.select_for_update().get(pk=1)
    job = GoogleSyncJob.objects.select_for_update().get(pk=job.pk)
    if conn.state != 'connected' or conn.account_id != job.account_id or job.status != 'preview' or job.created_at < timezone.now()-timedelta(minutes=30):
        raise ValidationError('Preview expired or account changed. Build a new preview.')
    if GoogleSyncJob.objects.filter(status__in=['queued', 'running']).exists():
        raise ValidationError('A sync is already queued or running.')
    job.status = 'queued'
    if actor:
        job.actor = actor
    job.save(update_fields=['status', 'actor'])
    return job


def approve_existing(item, resource_name, actor):
    conn, lease = acquire()
    try:
        if item.job.account_id != conn.account_id or item.job.status != 'preview' or item.action != 'review':
            raise ValidationError('Build a current review preview first.')
        if resource_name not in {p['resource_name'] for p in item.candidates}:
            raise ValidationError('Choose a Google contact shown in this review.')
        person = provider.get_person(access_token(conn), resource_name)
        custom = markers(person)
        if custom.get('lmt_crm_contact') and (custom['lmt_crm_contact'] != str(item.contact_id) or custom.get('lmt_crm_instance') != str(conn.namespace)):
            raise ValidationError('This Google contact is linked to another CRM identity.')
        if GoogleContactLink.objects.filter(account_id=conn.account_id, resource_name=resource_name).exclude(contact=item.contact).exists():
            raise ValidationError('This Google contact is already linked to another CRM contact.')
        GoogleContactLink.objects.update_or_create(account_id=conn.account_id, contact=item.contact,
            defaults=dict(resource_name=resource_name, remote_hash=fingerprint(person), local_hash='', state='linked', error_code=''))
        item.reason = 'Link approved by administrator. Build a new preview to sync.'
        item.save(update_fields=['reason'])
    finally:
        release(lease)


def process_item(item, conn, token, google_people=None):
    contact = Contact.objects.prefetch_related('identifiers').get(pk=item.contact_id)
    payload = payload_for(contact, conn)
    if fingerprint(payload) != item.local_hash:
        item.status, item.reason = 'review', 'CRM data changed after preview. Build a new preview.'
        item.save(update_fields=['status', 'reason']); return
    if item.action in ('review', 'skip'):
        item.status = 'review' if item.action == 'review' else 'skipped'
        item.save(update_fields=['status']); return
    link, _ = GoogleContactLink.objects.get_or_create(contact=contact, account_id=conn.account_id)
    item.status = 'processing'; item.save(update_fields=['status'])
    creating = not item.resource_name
    try:
        if creating:
            people = google_people if google_people is not None else provider.list_people(token)
            marked = [p for p in people if markers(p).get('lmt_crm_instance') == str(conn.namespace) and markers(p).get('lmt_crm_contact') == str(contact.pk)]
            if len(marked) == 1 and fingerprint(marked[0]) == item.local_hash:
                person = marked[0]
            elif marked or any(identities(p) & identities(payload) for p in people):
                raise provider.GoogleError('google_changed_since_preview')
            elif link.resource_name or link.state == 'uncertain':
                raise provider.GoogleError('create_requires_fresh_preview')
            else:
                link.state = 'uncertain'; link.save(update_fields=['state'])
                person = provider.create_person(token, payload)
                people.append(person)
        else:
            previous = provider.get_person(token, item.resource_name)
            if fingerprint(previous) == item.local_hash:
                person = previous
            elif fingerprint(previous) != item.remote_hash:
                raise provider.GoogleError('google_changed_since_preview')
            elif item.action == 'unchanged':
                person = previous
            else:
                person = provider.update_person(token, item.resource_name, payload, previous)
        try:
            provider.resource(person.get('resourceName', ''))
        except provider.GoogleError:
            raise provider.GoogleError('invalid_google_write_response', ambiguous=creating) from None
        link.resource_name, link.local_hash, link.remote_hash = person['resourceName'], item.local_hash, fingerprint(person)
        link.state, link.error_code, link.synced_at = 'linked', '', timezone.now()
        link.save()
        item.status, item.reason = 'synced', ''
    except provider.GoogleError as error:
        if creating and error.ambiguous:
            item.status, link.state = 'unknown', 'uncertain'
        else:
            item.status = 'review' if error.code in ('google_changed_since_preview', 'create_requires_fresh_preview') else 'failed'
            if creating and error.code != 'create_requires_fresh_preview':
                link.state = 'linked'
        item.reason, link.error_code = error.code, error.code
        link.save(update_fields=['state', 'error_code'])
    item.save(update_fields=['status', 'reason'])


def process_queue(limit=20):
    conn = connection()
    GoogleConnection.objects.filter(pk=1).update(last_worker_at=timezone.now())
    if configuration_errors() or connection().state != 'connected':
        return {'status': 'not_connected'}
    try:
        conn, lease = acquire()
    except ValidationError:
        return {'status': 'busy_or_disconnected'}
    job = None
    try:
        job = GoogleSyncJob.objects.filter(account_id=conn.account_id, status__in=['queued', 'running']).order_by('created_at').first()
        if not job and conn.automatic and (not conn.last_scheduled_at or conn.last_scheduled_at < timezone.now()-timedelta(minutes=conn.interval_minutes)):
            if not conn.connected_by or not can_manage_users(conn.connected_by):
                GoogleConnection.objects.filter(pk=1).update(automatic=False, last_error='connecting_admin_access_removed')
                return {'status': 'admin_access_removed'}
            GoogleConnection.objects.filter(pk=1).update(last_scheduled_at=timezone.now())
            job = build_preview(conn, access_token(conn), conn.connected_by, automatic=True)
            job = start_job(job)
            GoogleConnection.objects.filter(pk=1).update(last_scheduled_at=timezone.now())
        if not job:
            return {'status': 'idle'}
        if not job.actor_id or not can_manage_users(job.actor):
            job.status, job.error_code = 'cancelled', 'initiating_admin_access_removed'
            job.save(update_fields=['status', 'error_code'])
            return {'status': 'cancelled'}
        job.status = 'running'; job.save(update_fields=['status'])
        token = access_token(conn)
        # Interrupted processing never blindly repeats a Google contact creation.
        job.items.filter(status='processing').update(status='unknown', reason='Previous operation interrupted. Build a new preview to reconcile.')
        batch = list(job.items.filter(status='planned')[:limit])
        people = provider.list_people(token, heartbeat=lambda: renew_lease(conn)) if any(i.action == 'create' for i in batch) else None
        for item in batch:
            job.actor.refresh_from_db()
            if not can_manage_users(job.actor):
                job.status, job.error_code = 'cancelled', 'initiating_admin_access_removed'
                job.save(update_fields=['status', 'error_code'])
                return {'status': 'cancelled'}
            renew_lease(conn)
            process_item(item, conn, token, people)
        if not job.items.filter(status='planned').exists():
            partial = job.items.filter(status__in=['review', 'failed', 'unknown']).exists()
            job.status, job.completed_at = 'partial' if partial else 'completed', timezone.now()
            job.save(update_fields=['status', 'completed_at'])
            updates = {'last_error': 'review_required' if partial else ''}
            if not partial:
                updates['last_success_at'] = timezone.now()
            GoogleConnection.objects.filter(pk=1).update(**updates)
        return {'status': job.status}
    except provider.GoogleError as error:
        GoogleConnection.objects.filter(pk=1).update(last_error=error.code)
        if job:
            job.status, job.error_code = 'partial', error.code
            job.save(update_fields=['status', 'error_code'])
        return {'status': 'error', 'error': error.code}
    except ValidationError:
        GoogleConnection.objects.filter(pk=1).update(last_error='sync_validation_failed')
        if job:
            job.status, job.error_code = 'partial', 'sync_validation_failed'
            job.save(update_fields=['status', 'error_code'])
        else:
            GoogleSyncJob.objects.create(account_id=conn.account_id, email=conn.email, actor=conn.connected_by,
                automatic=True, status='failed', error_code='sync_validation_failed')
        return {'status': 'error', 'error': 'sync_validation_failed'}
    finally:
        release(lease)
