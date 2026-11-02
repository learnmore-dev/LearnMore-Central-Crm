from unittest.mock import patch
from django.core.cache import cache
from django.core.exceptions import ValidationError as DjangoValidationError
from django.db import IntegrityError, transaction
from django.test import SimpleTestCase, TestCase
from rest_framework.exceptions import ValidationError
from rest_framework.test import APIClient
from activities.models import Activity
from common.test_utils import crm_fixtures
from .models import Contact, ContactIdentifier, DuplicateReview
from .normalization import normalize_identifier, normalize_phone
from .services import add_identifier, create_contact, resolve_review


class NormalizationTests(SimpleTestCase):
    def test_indian_and_international_formats(self):
        for value in ['9876543210', '+91 98765-43210', '09876543210', '0091 9876543210', '91 9876543210']:
            with self.subTest(value=value):
                self.assertEqual(normalize_phone(value), '+919876543210')
        self.assertEqual(normalize_phone('080 2345 6789'), '+918023456789')
        self.assertEqual(normalize_phone('+1 (650) 253-0000'), '+16502530000')

    def test_invalid_numbers_and_extensions(self):
        for value in ['', '123', '+91 0000000000', '9876543210 ext 5', '+16502530000;ext=5', 'call 9876543210', '９８７６５４３２１０']:
            with self.subTest(value=value), self.assertRaises(DjangoValidationError):
                normalize_phone(value)

    def test_email_and_external_normalization(self):
        self.assertEqual(normalize_identifier('email', ' Person@EXAMPLE.COM '), ('person@example.com', ''))
        self.assertEqual(normalize_identifier('external', ' AbC ', ' GOOGLE '), ('AbC', 'google'))
        for kind, value, namespace in [('email', 'broken', ''), ('phone', '9876543210', 'meta'), ('external', 'abc', ''), ('bogus', 'x', '')]:
            with self.subTest(kind=kind), self.assertRaises(DjangoValidationError):
                normalize_identifier(kind, value, namespace)


class ContactServiceTests(TestCase):
    def setUp(self):
        self.a, self.b, self.owner, self.manager, self.other, self.management, self.contact = crm_fixtures()

    def intake(self, **extra):
        data = {'actor': self.owner, 'full_name': 'Another Person', 'branch': self.a,
                'identifiers': [{'kind': 'phone', 'value': '9876543210'}]}
        data.update(extra)
        return create_contact(**data)

    def test_multiple_identifiers_and_timeline(self):
        contact = self.intake(identifiers=[{'kind': 'phone', 'value': '9876543210'}, {'kind': 'phone', 'value': '9123456789'},
            {'kind': 'email', 'value': 'PERSON@example.com'}, {'kind': 'email', 'value': 'second@example.com'},
            {'kind': 'external', 'value': 'people/ABC', 'namespace': 'google'}])
        self.assertRegex(contact.contact_id, r'^LMT-C-\d{6,}$')
        self.assertEqual(contact.identifiers.count(), 5)
        self.assertEqual(contact.activities.get().kind, Activity.Kind.CONTACT_CREATED)

    def test_one_shared_phone_never_auto_merges(self):
        first = self.intake()
        review = self.intake(full_name='Family Member')
        self.assertIsInstance(review, DuplicateReview)
        self.assertEqual(list(review.candidates.all()), [first])
        self.assertEqual(Contact.objects.count(), 2)  # fixture plus first intake
        resolved = resolve_review(actor=self.manager, review=review, decision='separate', reason='Verified shared family phone')
        self.assertNotEqual(resolved.resolved_contact.pk, first.pk)
        self.assertEqual(ContactIdentifier.objects.filter(normalized_value='+919876543210').count(), 2)
        self.assertTrue(Contact.objects.filter(pk=first.pk).exists())

    def test_email_and_conflicting_identifiers_produce_all_candidates(self):
        first = self.intake()
        second = self.intake(identifiers=[{'kind': 'email', 'value': 'other@example.com'}])
        review = self.intake(identifiers=[{'kind': 'phone', 'value': '+91 9876543210'}, {'kind': 'email', 'value': 'OTHER@example.com'}])
        self.assertSetEqual(set(review.candidates.values_list('pk', flat=True)), {first.pk, second.pk})

    def test_explicit_link_preserves_existing_identity_and_history(self):
        contact = self.intake()
        review = self.intake(full_name='Alternate Name')
        resolve_review(actor=self.manager, review=review, decision='linked', reason='Confirmed same person', contact=contact)
        contact.refresh_from_db()
        self.assertEqual(contact.full_name, 'Another Person')
        self.assertEqual(contact.activities.count(), 2)
        self.assertEqual(Contact.objects.count(), 2)
        with self.assertRaises(ValidationError):
            resolve_review(actor=self.manager, review=review, decision='rejected', reason='Already done')

    def test_provider_identity_cannot_be_confirmed_separate(self):
        identifiers = [{'kind': 'external', 'value': 'people/123', 'namespace': 'google'}]
        self.intake(identifiers=identifiers)
        review = self.intake(identifiers=identifiers)
        with self.assertRaises(ValidationError):
            resolve_review(actor=self.manager, review=review, decision='separate', reason='Would duplicate provider ID')
        self.assertEqual(ContactIdentifier.objects.filter(kind='external').count(), 1)
        review.refresh_from_db()
        self.assertEqual(review.status, 'pending')

    def test_identifiers_normalized_unique_and_provider_constraints(self):
        ContactIdentifier.objects.create(contact=self.contact, kind='phone', value='9876543210')
        with self.assertRaises(IntegrityError), transaction.atomic():
            ContactIdentifier.objects.create(contact=self.contact, kind='phone', value='+919876543210')
        ContactIdentifier.objects.create(contact=self.contact, kind='external', value='abc', namespace='meta')
        second = Contact.objects.create(full_name='Second', branch=self.a)
        with self.assertRaises(IntegrityError), transaction.atomic():
            ContactIdentifier.objects.create(contact=second, kind='external', value='abc', namespace='meta')
        ContactIdentifier.objects.create(contact=second, kind='external', value='abc', namespace='google')

    def test_duplicate_input_and_invalid_phone_rejected(self):
        for identifiers in [[{'kind': 'phone', 'value': 'bad'}],
            [{'kind': 'phone', 'value': '9876543210'}, {'kind': 'phone', 'value': '+919876543210'}]]:
            with self.assertRaises(ValidationError):
                self.intake(identifiers=identifiers)
        self.assertEqual(Contact.objects.count(), 1)

    def test_identifier_addition_is_idempotent_and_conflicts_are_reviewed(self):
        contact = self.intake()
        first = add_identifier(actor=self.owner, contact=contact, kind='phone', value='+919876543210')
        self.assertEqual(first.pk, contact.identifiers.get().pk)
        review = add_identifier(actor=self.owner, contact=self.contact, kind='phone', value='9876543210')
        self.assertEqual(review.target_contact, self.contact)
        resolve_review(actor=self.manager, review=review, decision='separate', reason='Confirmed family phone')
        self.assertEqual(self.contact.identifiers.get().normalized_value, '+919876543210')

    def test_contact_and_identifiers_rollback_if_activity_fails(self):
        with patch('contacts.services.Activity.objects.create', side_effect=RuntimeError('storage failed')):
            with self.assertRaises(RuntimeError):
                self.intake()
        self.assertEqual(Contact.objects.count(), 1)
        self.assertFalse(ContactIdentifier.objects.exists())

    def test_contact_id_does_not_use_record_count_or_allow_override(self):
        second = Contact.objects.create(full_name='Second', branch=self.a)
        old = second.contact_id
        second.delete()  # no activities on this direct-model fixture
        third = Contact.objects.create(full_name='Third', branch=self.a)
        self.assertGreater(third.contact_id, old)
        third.contact_id = 'LMT-C-000001'
        with self.assertRaises(DjangoValidationError):
            third.save()

    def test_rejected_review_preserves_all_existing_records(self):
        contact = self.intake()
        review = self.intake()
        resolved = resolve_review(actor=self.manager, review=review, decision='rejected', reason='Incorrect enquiry')
        self.assertEqual(resolved.status, 'rejected')
        self.assertIsNone(resolved.resolved_contact)
        self.assertEqual(Contact.objects.count(), 2)
        self.assertEqual(contact.activities.count(), 1)


class ContactAPITests(TestCase):
    def setUp(self):
        cache.clear()
        self.a, self.b, self.owner, self.manager, self.other, self.management, self.contact = crm_fixtures()
        self.client = APIClient()
        self.client.force_authenticate(self.owner)

    def payload(self):
        return {'full_name': 'API Person', 'identifiers': [{'kind': 'phone', 'value': '9876543210'}]}

    def test_create_read_update_and_no_delete(self):
        response = self.client.post('/api/v1/contacts/', self.payload(), format='json')
        self.assertEqual(response.status_code, 201, response.data)
        self.assertEqual(response.data['identifier_records'][0]['normalized_value'], '+919876543210')
        url = '/api/v1/contacts/%s/' % response.data['id']
        self.assertEqual(self.client.patch(url, {'full_name': 'Updated'}, format='json').status_code, 200)
        for spoof in ({'branch': str(self.b.pk)}, {'contact_id': 'LMT-C-999999'}, {'created_by': str(self.manager.pk)}, {'identifiers': []}):
            self.assertEqual(self.client.patch(url, spoof, format='json').status_code, 400)
        self.assertEqual(self.client.delete(url).status_code, 405)
        self.assertEqual(self.client.get('/api/v1/contacts/?search=Updated').data['count'], 1)

    def test_match_and_intake_review_without_overwriting(self):
        self.client.post('/api/v1/contacts/', self.payload(), format='json')
        match = self.client.post('/api/v1/contacts/match/', {'identifiers': self.payload()['identifiers']}, format='json')
        self.assertTrue(match.data['needs_review'])
        response = self.client.post('/api/v1/contacts/', self.payload(), format='json')
        self.assertEqual(response.status_code, 409)
        self.assertEqual(len(response.data['candidate_contacts']), 1)
        self.assertEqual(response.data['status'], 'pending')
        url = '/api/v1/duplicate-reviews/%s/resolve/' % response.data['id']
        self.assertEqual(self.client.post(url, {'decision': 'separate', 'reason': 'Reviewed'}, format='json').status_code, 403)
        self.client.force_authenticate(self.manager)
        self.assertEqual(self.client.post(url, {'decision': 'separate', 'reason': ''}, format='json').status_code, 400)
        self.assertEqual(self.client.post(url, {'decision': 'separate', 'reason': 'Verified distinct person'}, format='json').status_code, 200)

    def test_cross_branch_candidates_and_identifiers_are_not_exposed(self):
        hidden = create_contact(actor=self.other, full_name='Hidden Person', branch=self.b,
                                identifiers=[{'kind': 'phone', 'value': '9876543210'}])
        self.assertEqual(self.client.get('/api/v1/contacts/%s/' % hidden.pk).status_code, 404)
        self.assertEqual(self.client.get('/api/v1/contact-identifiers/').data['count'], 0)
        response = self.client.post('/api/v1/contacts/', self.payload(), format='json')
        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.data['candidate_contacts'], [])
        self.assertNotIn(str(hidden.pk), str(response.data))
        self.client.force_authenticate(self.other)
        self.assertEqual(self.client.get('/api/v1/duplicate-reviews/%s/' % response.data['id']).status_code, 404)

    def test_invalid_input_and_cross_branch_writes(self):
        for extra in ({'branch': str(self.b.pk)}, {'contact_id': 'LMT-C-123456'}, {'identifiers': [{'kind': 'phone', 'value': 'bad'}]}, {'unexpected': True}):
            data = self.payload()
            data.update(extra)
            self.assertEqual(self.client.post('/api/v1/contacts/', data, format='json').status_code, 400)

    def test_identifier_endpoint_is_immutable_and_scoped(self):
        payload = {'contact': str(self.contact.pk), 'kind': 'email', 'value': 'API@example.com'}
        response = self.client.post('/api/v1/contact-identifiers/', payload, format='json')
        self.assertEqual(response.status_code, 201, response.data)
        identifier = response.data['id']
        self.assertEqual(self.client.post('/api/v1/contact-identifiers/', payload, format='json').data['id'], identifier)
        self.assertEqual(self.client.patch('/api/v1/contact-identifiers/%s/' % identifier, {'value': 'changed@example.com'}).status_code, 405)
        self.client.force_authenticate(self.other)
        self.assertEqual(self.client.get('/api/v1/contact-identifiers/%s/' % identifier).status_code, 404)

    def test_global_resolution_does_not_disclose_a_hidden_contact_uuid(self):
        hidden = create_contact(actor=self.other, branch=self.b, full_name='Hidden Person',
                                identifiers=[{'kind': 'phone', 'value': '9876543210'}])
        review = self.client.post('/api/v1/contacts/', self.payload(), format='json')
        url = '/api/v1/duplicate-reviews/%s/resolve/' % review.data['id']
        self.client.force_authenticate(self.manager)
        self.assertEqual(self.client.post(url, {'decision': 'linked', 'reason': 'Try hidden candidate', 'contact': str(hidden.pk)}, format='json').status_code, 400)
        self.client.force_authenticate(self.management)
        response = self.client.post(url, {'decision': 'linked', 'reason': 'Confirmed centrally', 'contact': str(hidden.pk)}, format='json')
        self.assertEqual(response.status_code, 200, response.data)
        self.client.force_authenticate(self.owner)
        response = self.client.get('/api/v1/duplicate-reviews/%s/' % review.data['id'])
        self.assertIsNone(response.data['resolved_contact'])
        self.assertEqual(response.data['candidate_contacts'], [])
        self.assertNotIn(str(hidden.pk), str(response.data))
