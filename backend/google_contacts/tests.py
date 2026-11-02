import copy
import hashlib
import json
from datetime import timedelta
from urllib.parse import parse_qs, urlsplit
from unittest.mock import patch
from cryptography.fernet import Fernet
from django.core.cache import cache
from django.test import TestCase, override_settings
from django.utils import timezone
from rest_framework.test import APIClient
from rest_framework.exceptions import ValidationError
from accounts.models import User
from common.test_utils import crm_fixtures
from contacts.models import ContactIdentifier
from leads.services import create_lead
from .models import GoogleConnection, GoogleOAuthAttempt, GoogleContactLink, GoogleSyncJob
from . import services, provider

TEST_KEY = Fernet.generate_key().decode()
TRANSPORT_UPDATE = provider.update_person


@override_settings(DEBUG=True, GOOGLE_CONTACTS_CLIENT_ID='synthetic-client', GOOGLE_CONTACTS_CLIENT_SECRET='synthetic-secret',
    GOOGLE_CONTACTS_ENCRYPTION_KEY=TEST_KEY, GOOGLE_CONTACTS_REDIRECT_URI='http://127.0.0.1:3100/api/v1/integrations/google-contacts/callback/',
    GOOGLE_CONTACTS_CRM_ORIGIN='http://127.0.0.1:3100', GOOGLE_CONTACTS_EXPECTED_EMAIL='')
class GoogleContactsTests(TestCase):
    def setUp(self):
        cache.clear()
        self.a, self.b, self.owner, self.manager, self.other, self.management, self.contact = crm_fixtures()
        self.admin = User.objects.create_user(username='google-admin', role='super_admin')
        ContactIdentifier.objects.create(contact=self.contact, kind='phone', value='+919876543210')
        self.conn = GoogleConnection.objects.create(account_id='account-1', email='shared@example.com', state='connected',
            refresh_token_encrypted=services.encrypt('synthetic-refresh-token'), connected_by=self.admin)
        self.client = APIClient(); self.client.force_authenticate(self.admin)
        self.url = '/api/v1/integrations/google-contacts/'
        self.refresh = patch('google_contacts.provider.refresh', return_value='synthetic-access-token').start()
        self.list_people = patch('google_contacts.provider.list_people', return_value=[]).start()
        self.get_person = patch('google_contacts.provider.get_person').start()
        self.create = patch('google_contacts.provider.create_person', side_effect=lambda token, payload: self.person(payload)).start()
        self.update = patch('google_contacts.provider.update_person', side_effect=lambda token, name, payload, previous: self.person(payload, name)).start()
        self.addCleanup(patch.stopall)

    def person(self, payload=None, name='people/c123'):
        return {**copy.deepcopy(payload or services.payload_for(self.contact, self.conn)), 'resourceName': name,
            'etag': 'person-etag', 'metadata': {'sources': [{'type': 'CONTACT', 'id': 'c123', 'etag': 'source-etag'}]}}

    def sync_once(self):
        job = services.preview(self.admin)
        services.start_job(job, self.admin)
        services.process_queue()
        job.refresh_from_db()
        return job

    def test_preview_has_exact_values_and_does_not_write_to_google(self):
        create_lead(actor=self.manager, contact=self.contact, branch=self.a, owner=self.owner, title='Python')
        response = self.client.post(self.url+'preview/')
        self.assertEqual(response.status_code, 201, response.data)
        job = GoogleSyncJob.objects.get(pk=response.data['id'])
        self.assertEqual(job.status, 'preview')
        item = job.items.get()
        self.assertEqual(item.action, 'create')
        self.assertIn(self.contact.contact_id, item.payload['names'][0]['givenName'])
        self.assertIn('LMT-MT-L-', item.payload['biographies'][0]['value'])
        self.assertIn('First enquiry:', item.payload['biographies'][0]['value'])
        self.create.assert_not_called(); self.update.assert_not_called()

    def test_explicit_start_creates_once_and_next_sync_is_unchanged(self):
        job = self.sync_once()
        self.assertEqual(job.status, 'completed')
        self.assertEqual(self.create.call_count, 1)
        link = GoogleContactLink.objects.get()
        self.assertEqual(link.resource_name, 'people/c123')
        person = self.person()
        self.list_people.return_value = [person]; self.get_person.return_value = person
        job = self.sync_once()
        self.assertEqual(job.items.get().action, 'unchanged')
        self.assertEqual(self.create.call_count, 1)
        self.update.assert_not_called()

    def test_google_personal_match_is_reviewed_and_not_overwritten(self):
        person = {'resourceName': 'people/personal', 'names': [{'givenName': 'Personal name'}], 'phoneNumbers': [{'value': '+919876543210'}]}
        self.list_people.return_value = [person]
        job = self.sync_once()
        self.assertEqual(job.status, 'partial')
        self.assertEqual(job.items.get().status, 'review')
        self.create.assert_not_called(); self.update.assert_not_called()

    def test_link_approval_is_explicit_then_new_preview_updates_only_after_start(self):
        person = self.person({'names': [{'givenName': 'Personal name'}], 'phoneNumbers': [{'value': '+919876543210'}]})
        self.list_people.return_value = [person]; self.get_person.return_value = person
        job = services.preview(self.admin); item = job.items.get()
        url = f'/api/v1/integrations/google-contact-items/{item.pk}/approve-link/'
        response = self.client.post(url, {'resource_name': person['resourceName'], 'confirm_replace_managed_fields': False}, format='json')
        self.assertEqual(response.status_code, 400)
        response = self.client.post(url, {'resource_name': person['resourceName'], 'confirm_replace_managed_fields': True}, format='json')
        self.assertEqual(response.status_code, 200, response.data)
        self.update.assert_not_called()
        job = services.preview(self.admin)
        self.assertEqual(job.items.get().action, 'update')
        services.start_job(job, self.admin); services.process_queue()
        self.update.assert_called_once()

    def test_changed_google_record_requires_review(self):
        self.sync_once()
        person = self.person(); person['names'] = [{'givenName': 'Edited on mobile'}]
        self.list_people.return_value = [person]
        job = self.sync_once()
        self.assertEqual(job.items.get().action, 'review')
        self.update.assert_not_called()

    def test_changes_after_preview_are_not_overwritten(self):
        self.sync_once()
        person = self.person()
        self.list_people.return_value = [person]
        self.contact.full_name = 'Updated in CRM'; self.contact.save()
        job = services.preview(self.admin)
        self.assertEqual(job.items.get().action, 'update')
        edited = copy.deepcopy(person); edited['names'] = [{'givenName': 'Concurrent Google edit'}]
        self.get_person.return_value = edited
        services.start_job(job, self.admin); services.process_queue()
        self.assertEqual(job.items.get().status, 'review')
        self.update.assert_not_called()

    def test_new_google_match_after_preview_does_not_create_duplicate(self):
        job = services.preview(self.admin)
        self.list_people.return_value = [self.person({'names': [{'givenName': 'Added later'}], 'phoneNumbers': [{'value': '+919876543210'}]})]
        services.start_job(job, self.admin); services.process_queue()
        self.assertEqual(job.items.get().status, 'review')
        self.create.assert_not_called()

    def test_ambiguous_creation_is_never_blindly_retried_and_can_reconcile(self):
        self.create.side_effect = provider.GoogleError('google_transport_error', ambiguous=True)
        job = self.sync_once()
        self.assertEqual(job.items.get().status, 'unknown')
        self.assertEqual(GoogleContactLink.objects.get().state, 'uncertain')
        next_job = services.preview(self.admin)
        self.assertEqual(next_job.items.get().action, 'review')
        self.list_people.return_value = [self.person()]; self.get_person.return_value = self.person()
        next_job = self.sync_once()
        self.assertEqual(next_job.items.get().status, 'synced')
        self.assertEqual(self.create.call_count, 1)

    def test_shared_crm_phone_and_missing_identifiers_are_not_auto_created(self):
        from contacts.models import Contact
        second = Contact.objects.create(full_name='Shared phone', branch=self.a, created_by=self.owner)
        ContactIdentifier.objects.create(contact=second, kind='phone', value='+919876543210')
        Contact.objects.create(full_name='No identifiers', branch=self.a, created_by=self.owner)
        job = self.sync_once()
        self.assertEqual(job.items.filter(action='review').count(), 2)
        self.assertEqual(job.items.filter(action='skip').count(), 1)
        self.create.assert_not_called()

    def test_stale_preview_and_changed_crm_record_require_fresh_review(self):
        job = services.preview(self.admin)
        GoogleSyncJob.objects.filter(pk=job.pk).update(created_at=timezone.now()-timedelta(hours=1))
        with self.assertRaises(ValidationError):
            services.start_job(job, self.admin)
        job = services.preview(self.admin); services.start_job(job, self.admin)
        self.contact.full_name = 'New name'; self.contact.save()
        services.process_queue()
        self.assertEqual(job.items.get().status, 'review')
        self.create.assert_not_called()

    def test_permissions_csrf_and_secret_exclusion(self):
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 200)
        self.assertNotIn('synthetic-secret', str(response.data))
        self.assertNotIn('synthetic-refresh-token', str(response.data))
        self.assertNotIn(self.conn.refresh_token_encrypted, str(response.data))
        for user in [self.owner, self.manager, self.management]:
            self.client.force_authenticate(user)
            self.assertEqual(self.client.get(self.url).status_code, 403)
            self.assertEqual(self.client.post(self.url+'preview/').status_code, 403)
            self.assertEqual(self.client.get('/api/v1/integrations/google-contact-jobs/').status_code, 403)
        client = APIClient(enforce_csrf_checks=True); client.force_login(self.admin)
        self.assertEqual(client.post(self.url+'preview/').status_code, 403)

    def test_oauth_pkce_session_binding_consumption_and_encryption(self):
        self.client.force_authenticate(None); self.client.force_login(self.admin)
        response = self.client.post(self.url+'connect/')
        self.assertEqual(response.status_code, 200, response.data)
        params = parse_qs(urlsplit(response.data['authorization_url']).query)
        self.assertEqual(params['code_challenge_method'], ['S256'])
        self.assertEqual(params['access_type'], ['offline'])
        attempt = GoogleOAuthAttempt.objects.get()
        self.assertNotEqual(attempt.digest, params['state'][0])
        with patch('google_contacts.provider.exchange', return_value={'access_token': 'test-access', 'refresh_token': 'new-refresh', 'scope': provider.CONTACT_SCOPE}) as exchange, patch('google_contacts.provider.identity', return_value={'sub': 'account-1', 'email': 'shared@example.com', 'email_verified': True}):
            response = self.client.get(self.url+'callback/', {'state': params['state'][0], 'code': 'synthetic-code'})
            self.assertEqual(response.status_code, 302)
            self.assertIn('oauth=connected', response['Location'])
            self.assertNotIn('synthetic-code', response['Location'])
            response = self.client.get(self.url+'callback/', {'state': params['state'][0], 'code': 'synthetic-code'})
            self.assertIn('connection_failed', response['Location'])
            exchange.assert_called_once()
        self.conn.refresh_from_db()
        self.assertNotEqual(self.conn.refresh_token_encrypted, 'new-refresh')
        self.assertEqual(services.decrypt(self.conn.refresh_token_encrypted), 'new-refresh')
        self.assertEqual(GoogleOAuthAttempt.objects.get().verifier_encrypted, '')

    def test_wrong_browser_or_expired_oauth_attempt_cannot_connect(self):
        self.client.force_authenticate(None); self.client.force_login(self.admin)
        params = parse_qs(urlsplit(self.client.post(self.url+'connect/').data['authorization_url']).query)
        other = APIClient(); other.force_login(self.admin)
        with patch('google_contacts.provider.exchange') as exchange:
            response = other.get(self.url+'callback/', {'state': params['state'][0], 'code': 'synthetic'})
            self.assertIn('connection_failed', response['Location'])
            GoogleOAuthAttempt.objects.update(expires_at=timezone.now()-timedelta(minutes=1))
            self.client.get(self.url+'callback/', {'state': params['state'][0], 'code': 'synthetic'})
            exchange.assert_not_called()

    def test_unconfigured_connection_makes_no_external_calls(self):
        with override_settings(GOOGLE_CONTACTS_CLIENT_SECRET=''):
            self.assertFalse(self.client.get(self.url).data['configured'])
            self.assertEqual(self.client.post(self.url+'connect/').status_code, 400)
            self.assertEqual(self.client.post(self.url+'preview/').status_code, 400)
            self.assertEqual(services.process_queue()['status'], 'not_connected')
        self.refresh.assert_not_called()

    def test_disconnect_keeps_google_contacts_and_cancels_queue(self):
        job = services.preview(self.admin); services.start_job(job, self.admin)
        response = self.client.post(self.url+'disconnect/')
        self.assertEqual(response.status_code, 200)
        self.conn.refresh_from_db(); job.refresh_from_db()
        self.assertEqual(self.conn.refresh_token_encrypted, '')
        self.assertEqual(job.status, 'cancelled')
        self.create.assert_not_called(); self.update.assert_not_called()

    def test_worker_lease_and_demoted_admin_stop_writes(self):
        job = services.preview(self.admin); services.start_job(job, self.admin)
        conn, lease = services.acquire()
        self.assertEqual(services.process_queue()['status'], 'busy_or_disconnected')
        services.release(lease)
        self.admin.role, self.admin.branch = 'counsellor', self.a; self.admin.save()
        services.process_queue(); job.refresh_from_db()
        self.assertEqual(job.status, 'cancelled')
        self.create.assert_not_called()

    def test_explicit_schedule_creates_a_job_and_processes_new_contacts(self):
        response = self.client.post(self.url+'settings/', {'automatic': True, 'interval_minutes': 5}, format='json')
        self.assertEqual(response.status_code, 200)
        services.process_queue()
        self.assertEqual(GoogleSyncJob.objects.count(), 1)
        self.assertTrue(GoogleSyncJob.objects.get().automatic)
        self.create.assert_called_once()

    def test_provider_errors_are_redacted_and_callback_logs_hide_codes(self):
        from .logging import RedactGoogleCallback
        import logging
        record = logging.LogRecord('django.server', 20, '', 0, '%s', ('GET /api/v1/integrations/google-contacts/callback/?code=secret-code&state=secret-state HTTP/1.1',), None)
        RedactGoogleCallback().filter(record)
        self.assertNotIn('secret-code', record.getMessage()); self.assertNotIn('secret-state', record.getMessage())
        self.refresh.side_effect = provider.GoogleError('google_reconnect_required')
        self.assertEqual(self.client.post(self.url+'preview/').status_code, 400)
        self.conn.refresh_from_db()
        self.assertEqual(self.conn.state, 'reconnect_required')

    def test_successful_create_with_invalid_response_is_kept_uncertain(self):
        self.create.side_effect = None
        self.create.return_value = {}
        job = self.sync_once()
        self.assertEqual(job.items.get().status, 'unknown')
        self.assertEqual(GoogleContactLink.objects.get().state, 'uncertain')

    def test_transport_update_preserves_other_custom_fields_and_uses_contact_etag(self):
        previous = self.person()
        previous['userDefined'].append({'key': 'personal_reference', 'value': 'Keep this'})
        payload = services.payload_for(self.contact, self.conn)
        # Exercise the transport function itself, not the worker's mocked adapter.
        with patch('google_contacts.provider.request', return_value=self.person()) as request:
            TRANSPORT_UPDATE('synthetic-token', 'people/c123', payload, previous)
            args = request.call_args.args
            self.assertEqual(args[1], 'PATCH')
            self.assertIn('updatePersonFields=', args[0])
            self.assertEqual(args[2]['metadata']['sources'][0]['etag'], 'source-etag')
            self.assertIn({'key': 'personal_reference', 'value': 'Keep this'}, args[2]['userDefined'])
            self.assertNotIn('metadata', args[0].split('updatePersonFields=')[1].split('&')[0])
