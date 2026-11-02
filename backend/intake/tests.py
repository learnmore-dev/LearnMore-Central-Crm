import hashlib
import hmac
import json
import time
from unittest.mock import patch
from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.test import TestCase, override_settings
from rest_framework.test import APIClient
from common.test_utils import crm_fixtures
from contacts.models import Contact, ContactIdentifier
from leads.models import Lead
from .models import WebsiteSource, WebsiteSubmission


@override_settings(WEBSITE_INTAKE_SECRETS={'learnmoretech': 'synthetic-tech-secret', 'learnmoretechnologies': 'synthetic-other-secret'})
class WebsiteIntakeTests(TestCase):
    def setUp(self):
        cache.clear()
        self.a, self.b, self.owner, self.manager, self.other, self.management, self.contact = crm_fixtures()
        self.source = WebsiteSource.objects.create(slug='learnmoretech', default_branch=self.a, actor=self.management)
        self.source.allowed_branches.add(self.a)
        self.client = APIClient()
        self.data = {'submission_id': 'submission-1', 'full_name': 'Website Student', 'phone': '9876543210',
            'email': 'student@example.com', 'course': 'Python Full Stack', 'message': 'Please call tomorrow',
            'page_url': 'https://learnmoretech.in/courses/python?utm_source=google', 'form_name': 'Free demo', 'utm': {'source': 'google'}}

    def send(self, data=None, *, timestamp=None, signature=None, site='learnmoretech'):
        timestamp = str(timestamp or int(time.time()))
        raw = json.dumps(data or self.data).encode()
        secret = 'synthetic-tech-secret' if site == 'learnmoretech' else 'synthetic-other-secret'
        signature = signature or 'sha256=' + hmac.new(secret.encode(), f'{site}.{timestamp}.'.encode() + raw, hashlib.sha256).hexdigest()
        return self.client.post(f'/api/v1/intake/websites/{site}/', raw, content_type='application/json',
            HTTP_X_WEBSITE_TIMESTAMP=timestamp, HTTP_X_WEBSITE_SIGNATURE=signature)

    def test_submission_creates_contact_routed_lead_and_timeline(self):
        response = self.send()
        self.assertEqual(response.status_code, 202)
        self.assertEqual(set(response.data), {'received', 'receipt_id'})
        submission = WebsiteSubmission.objects.get()
        self.assertEqual(submission.status, 'created')
        self.assertEqual(submission.phone, '+919876543210')
        self.assertNotIn('?', submission.page_url)
        self.assertEqual(submission.lead.source, 'website')
        self.assertEqual(submission.lead.title, 'Python Full Stack')
        self.assertEqual(submission.lead.owner, self.owner)
        self.assertTrue(submission.lead.activities.filter(body__contains='Please call tomorrow').exists())

    def test_signature_expiry_and_source_secrets_are_enforced(self):
        self.assertEqual(self.send(signature='sha256=wrong').status_code, 403)
        self.assertEqual(self.send(timestamp=int(time.time())-600).status_code, 403)
        self.assertEqual(WebsiteSubmission.objects.count(), 0)
        self.assertEqual(self.client.post('/api/v1/intake/websites/unknown/', {}, format='json').status_code, 503)

    def test_retries_are_idempotent_and_changed_payload_rejected(self):
        first = self.send()
        second = self.send()
        self.assertEqual(first.data, second.data)
        self.assertEqual(Lead.objects.count(), 1)
        self.assertEqual(WebsiteSubmission.objects.count(), 1)
        self.assertEqual(self.send({**self.data, 'course': 'Changed'}).status_code, 400)

    def test_branch_selection_cannot_expand_allowed_routes(self):
        data = {**self.data, 'branch_code': self.b.code}
        self.assertEqual(self.send(data).status_code, 400)
        self.source.allowed_branches.add(self.b)
        self.assertEqual(self.send(data).status_code, 202)
        self.assertEqual(WebsiteSubmission.objects.get().branch, self.b)

    def test_duplicate_is_visible_for_review_and_manager_can_create_its_enquiry(self):
        ContactIdentifier.objects.create(contact=self.contact, kind='phone', value='9876543210')
        self.assertEqual(self.send().status_code, 202)
        submission = WebsiteSubmission.objects.get()
        self.assertEqual(submission.status, 'review')
        self.assertIsNone(submission.lead_id)
        self.client.force_authenticate(self.manager)
        response = self.client.post(f'/api/v1/website-enquiries/{submission.pk}/resolve/', {
            'decision': 'linked', 'reason': 'Confirmed same student', 'contact': str(self.contact.pk)}, format='json')
        self.assertEqual(response.status_code, 200)
        submission.refresh_from_db()
        self.assertEqual(submission.lead.contact, self.contact)
        self.assertEqual(submission.status, 'created')
        self.assertEqual(self.client.post(f'/api/v1/website-enquiries/{submission.pk}/resolve/', {
            'decision': 'linked', 'reason': 'Again', 'contact': str(self.contact.pk)}, format='json').status_code, 400)
        self.assertEqual(Lead.objects.count(), 1)

    def test_scope_redaction_and_counsellor_cannot_resolve(self):
        hidden = Contact.objects.create(full_name='Private Person', branch=self.b)
        ContactIdentifier.objects.create(contact=hidden, kind='phone', value='9876543210')
        self.send()
        submission = WebsiteSubmission.objects.get()
        self.client.force_authenticate(self.owner)
        response = self.client.get('/api/v1/website-enquiries/')
        self.assertEqual(response.data['count'], 1)
        self.assertEqual(response.data['results'][0]['candidates'], [])
        self.assertNotIn('Private Person', str(response.data))
        self.assertEqual(self.client.post(f'/api/v1/website-enquiries/{submission.pk}/resolve/', {
            'decision': 'separate', 'reason': 'Shared number'}, format='json').status_code, 403)
        self.client.force_authenticate(self.other)
        self.assertEqual(self.client.get('/api/v1/website-enquiries/').data['count'], 0)

    def test_strict_validation_and_no_contact_enumeration(self):
        for change in [{'phone': 'invalid'}, {'phone': '', 'email': ''}, {'owner': str(self.owner.pk)},
                       {'page_url': 'https://attacker.example/'}, {'utm': {'unexpected': 'data'}}]:
            self.assertEqual(self.send({**self.data, **change}).status_code, 400)
        self.assertEqual(Lead.objects.count(), 0)

    def test_atomic_rollback_on_routing_failure(self):
        with patch('intake.services.create_lead', side_effect=RuntimeError('unavailable')):
            with self.assertRaises(RuntimeError):
                self.send()
        self.assertFalse(WebsiteSubmission.objects.exists())
        self.assertFalse(Contact.objects.filter(full_name='Website Student').exists())

    def test_both_domains_are_isolated_and_unavailable_actor_rejected(self):
        WebsiteSource.objects.create(slug='learnmoretechnologies', default_branch=self.b, actor=self.management)
        data = {**self.data, 'page_url': 'https://learnmoretechnologies.in/contact-us'}
        self.assertEqual(self.send(data, site='learnmoretechnologies').status_code, 202)
        self.assertEqual(WebsiteSubmission.objects.get().branch, self.b)
        self.management.is_active = False
        self.management.save()
        self.assertEqual(self.send().status_code, 403)

    def test_configure_creates_non_login_actor_and_is_idempotent(self):
        from django.core.management import call_command
        call_command('configure_website', 'learnmoretech', branch=self.a.code, verbosity=0)
        call_command('configure_website', 'learnmoretech', branch=self.a.code, verbosity=0)
        source = WebsiteSource.objects.get(slug='learnmoretech')
        self.assertFalse(source.actor.has_usable_password())
        self.assertFalse(source.actor.is_staff)
        self.assertFalse(source.actor.is_superuser)
