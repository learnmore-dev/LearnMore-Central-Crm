from django.test import TestCase
from rest_framework.test import APIClient
from common.test_utils import crm_fixtures
from contacts.models import Contact, ContactIdentifier, DuplicateReview
from education.models import Qualification
from leads.models import Lead
from leads.services import create_lead


class UnifiedEnquiryTests(TestCase):
    def setUp(self):
        self.a, self.b, self.owner, self.manager, self.other, self.management, self.contact = crm_fixtures()
        self.client = APIClient()
        self.client.force_authenticate(self.manager)
        self.payload = {
            'candidate': {'full_name': 'New candidate', 'mobile': '9876543210', 'email': 'new@example.com'},
            'branch': str(self.a.pk), 'source': 'whatsapp', 'title': 'Python',
            'qualification': {'course_interest': 'Python', 'course_interests': ['Python', 'Data Science'],
                'training_mode': 'classroom', 'city': 'Mysuru', 'preferred_branch': str(self.b.pk)},
        }

    def post(self, **changes):
        return self.client.post('/api/v1/leads/intake/', {**self.payload, **changes}, format='json')

    def test_atomic_intake_records_contact_interests_city_and_independent_branch_preference(self):
        response = self.post()
        self.assertEqual(response.status_code, 201, response.data)
        lead = Lead.objects.get(pk=response.data['id'])
        self.assertEqual(lead.contact.full_name, 'New candidate')
        self.assertEqual(lead.contact.identifiers.count(), 2)
        self.assertEqual(lead.branch, self.a)
        self.assertEqual(lead.owner.branch, self.a)
        self.assertEqual(lead.source, 'whatsapp')
        self.assertTrue(lead.next_action)
        qualification = Qualification.objects.get(lead=lead)
        self.assertEqual(qualification.city, 'Mysuru')
        self.assertEqual(qualification.preferred_branch, self.b)
        self.assertEqual(qualification.course_interests, ['Python', 'Data Science'])
        self.assertEqual(response.data['qualification']['preferred_branch_name'], self.b.name)

    def test_duplicate_requires_review_without_creating_a_contact_or_lead(self):
        ContactIdentifier.objects.create(contact=self.contact, kind='phone', value='9876543210')
        response = self.post()
        self.assertEqual(response.status_code, 409, response.data)
        self.assertEqual(Contact.objects.count(), 1)
        self.assertEqual(Lead.objects.count(), 0)
        self.assertEqual(Qualification.objects.count(), 0)
        self.assertEqual(DuplicateReview.objects.count(), 1)

    def test_bad_followup_rolls_back_new_contact_and_identifiers(self):
        response = self.post(next_action='Call candidate')
        self.assertEqual(response.status_code, 400)
        self.assertEqual(Contact.objects.count(), 1)
        self.assertEqual(ContactIdentifier.objects.count(), 0)
        self.assertEqual(Lead.objects.count(), 0)

    def test_course_validation_rejects_duplicates_missing_primary_and_inactive_preferences(self):
        for interests in (['Data Science'], ['Python', 'python'], ['Python'] * 21):
            with self.subTest(interests=interests):
                response = self.post(qualification={**self.payload['qualification'], 'course_interests': interests})
                self.assertEqual(response.status_code, 400, response.data)
        self.b.is_active = False
        self.b.save()
        self.assertEqual(self.post().status_code, 400)
        self.assertEqual(Contact.objects.count(), 1)
        self.assertEqual(Lead.objects.count(), 0)

    def test_existing_contact_path_and_primary_course_updates_stay_consistent(self):
        payload = {key: value for key, value in self.payload.items() if key != 'candidate'}
        payload['contact'] = str(self.contact.pk)
        response = self.client.post('/api/v1/leads/', payload, format='json')
        self.assertEqual(response.status_code, 201, response.data)
        lead = Lead.objects.get(pk=response.data['id'])
        path = f'/api/v1/education/qualifications/{lead.pk}/'
        updated = self.client.patch(path, {'course_interest': 'Data Science', 'course_interests': ['Python', 'Data Science']}, format='json')
        self.assertEqual(updated.status_code, 200, updated.data)
        lead.refresh_from_db()
        self.assertEqual(lead.title, 'Data Science')
        updated = self.client.patch(f'/api/v1/leads/{lead.pk}/', {'title': 'Java'}, format='json')
        self.assertEqual(updated.status_code, 200, updated.data)
        qualification = Qualification.objects.get(lead=lead)
        self.assertEqual(qualification.course_interest, 'Java')
        self.assertEqual(set(qualification.course_interests), {'Python', 'Java'})

    def test_scope_owner_permissions_and_qualification_privacy_are_preserved(self):
        response = self.post(owner=str(self.owner.pk))
        lead = Lead.objects.get(pk=response.data['id'])
        self.client.force_authenticate(self.other)
        self.assertEqual(self.client.get(f'/api/v1/leads/{lead.pk}/').status_code, 404)
        self.assertEqual(self.post().status_code, 400)  # Assigned branch is out of scope.
        self.client.force_authenticate(self.owner)
        another = create_lead(actor=self.manager, branch=self.a, contact=self.contact, title='Other', owner=self.manager)
        Qualification.objects.create(lead=another, notes='Private counselling', updated_by=self.manager)
        record = self.client.get(f'/api/v1/leads/{another.pk}/')
        self.assertEqual(record.status_code, 200)
        self.assertNotIn('qualification', record.data)
        self.assertEqual(self.client.patch(f'/api/v1/leads/{another.pk}/', {'qualification': {'city': 'Chennai'}}, format='json').status_code, 403)

    def test_legacy_enquiries_and_preference_metadata_remain_readable(self):
        lead = create_lead(actor=self.manager, branch=self.a, contact=self.contact, title='Legacy course')
        response = self.client.get(f'/api/v1/education/qualifications/{lead.pk}/')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data['course_interests'], ['Legacy course'])
        self.assertEqual(response.data['city'], '')
        branches = self.client.get('/api/v1/education/preferred-branches/')
        self.assertEqual(branches.status_code, 200)
        self.assertEqual({item['name'] for item in branches.data}, {self.a.name, self.b.name})
        self.assertTrue(all(set(item) == {'id', 'name'} for item in branches.data))

    def test_counsellor_can_capture_preferences_even_when_routing_selects_another_owner(self):
        self.client.force_authenticate(self.owner)
        from routing.models import CounsellorProfile
        CounsellorProfile.objects.filter(user=self.owner).update(is_available=False)
        response = self.post()
        self.assertEqual(response.status_code, 201, response.data)
        lead = Lead.objects.get(pk=response.data['id'])
        self.assertNotEqual(lead.owner, self.owner)
        self.assertEqual(Qualification.objects.get(lead=lead).city, 'Mysuru')

    def test_intake_rejects_ambiguous_candidate_and_contact(self):
        self.assertEqual(self.post(contact=str(self.contact.pk)).status_code, 400)
        self.assertEqual(self.post(candidate={'full_name': 'No identifiers'}).status_code, 400)
        self.assertEqual(Lead.objects.count(), 0)
