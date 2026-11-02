from unittest.mock import patch
from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.core.exceptions import ValidationError as DjangoValidationError
from django.db import DatabaseError, connection, transaction
from django.test import TestCase
from rest_framework.exceptions import PermissionDenied, ValidationError
from rest_framework.test import APIClient
from common.test_utils import crm_fixtures
from contacts.models import Contact
from followups.models import FollowUpTask
from leads.models import Lead
from leads.services import create_lead, update_lead
from .models import CounsellorProfile, RoutingPolicy, AssignmentHistory
from .services import route_lead, manual_assign, transfer_lead, configure_profile, acknowledge, retry_unassigned


class RoutingTests(TestCase):
    def setUp(self):
        cache.clear()
        self.a, self.b, self.owner, self.manager, self.other, self.management, self.contact = crm_fixtures()
        self.client = APIClient()
        self.client.force_authenticate(self.manager)

    def enquiry(self, **extra):
        data = {'actor': self.manager, 'branch': self.a, 'title': 'New enquiry',
                'contact': Contact.objects.create(full_name='New student', branch=self.a)}
        data.update(extra)
        return create_lead(**data)

    def test_round_robin_persists_and_is_branch_local(self):
        leads = [self.enquiry() for _ in range(6)]
        self.assertEqual([lead.owner_id for lead in leads], [self.owner.pk, self.manager.pk] * 3)
        self.assertEqual(RoutingPolicy.objects.get(branch=self.a).last_position, self.manager.counsellor_profile.pk)
        self.assertFalse(any(lead.owner_id == self.other.pk for lead in leads))
        self.assertEqual(AssignmentHistory.objects.filter(status='assigned').count(), 6)

    def test_existing_owner_deadline_and_rotation_are_preserved(self):
        lead = self.enquiry()
        state = RoutingPolicy.objects.get(branch=self.a).last_position
        routed = route_lead(lead=lead, actor=self.manager)
        self.assertEqual(routed.owner_id, lead.owner_id)
        self.assertEqual(routed.acknowledgement_due_at, lead.acknowledgement_due_at)
        self.assertEqual(routed.assignment_version, 1)
        self.assertEqual(lead.assignment_history.count(), 1)
        self.assertEqual(RoutingPolicy.objects.get(branch=self.a).last_position, state)

    def test_new_enquiry_reuses_relevant_contact_owner(self):
        first = self.enquiry(contact=self.contact)
        second = self.enquiry(contact=self.contact)
        self.assertEqual(first.owner_id, second.owner_id)
        self.assertNotEqual(first.pk, second.pk)
        self.assertEqual(RoutingPolicy.objects.get(branch=self.a).last_position, self.owner.counsellor_profile.pk)
        with self.assertRaises(ValidationError):
            self.enquiry(contact=self.contact, owner=self.manager)

    def test_skips_unavailable_inactive_unauthorized_and_full_profiles(self):
        configure_profile(actor=self.manager, user=self.owner, is_available=False)
        lead = self.enquiry()
        self.assertEqual(lead.owner_id, self.manager.pk)
        configure_profile(actor=self.manager, user=self.owner, is_available=True, can_receive_leads=False)
        configure_profile(actor=self.manager, user=self.manager, max_active_leads=1)
        self.assertIsNone(self.enquiry().owner_id)
        configure_profile(actor=self.manager, user=self.owner, can_receive_leads=True)
        self.owner.is_active = False
        self.owner.save()
        self.assertIsNone(self.enquiry().owner_id)
        self.owner.is_active, self.owner.role = True, 'accounts'
        self.owner.save()
        self.assertIsNone(self.enquiry().owner_id)

    def test_over_capacity_owner_is_not_preserved(self):
        first = self.enquiry(contact=self.contact)
        configure_profile(actor=self.manager, user=self.owner, max_active_leads=0)
        routed = route_lead(lead=first, actor=self.manager)
        self.assertEqual(routed.owner_id, self.manager.pk)
        self.assertEqual(routed.assignment_history.first().previous_owner_id, self.owner.pk)

    def test_unassigned_fallback_has_one_durable_manager_alert_and_retries(self):
        CounsellorProfile.objects.filter(user__branch=self.a).update(is_available=False)
        lead = self.enquiry()
        self.assertIsNone(lead.owner_id)
        self.assertTrue(lead.unassigned_reason)
        self.assertEqual(lead.tasks.filter(kind='unassigned').count(), 1)
        for _ in range(3):
            route_lead(lead=lead, actor=self.manager)
        self.assertEqual(lead.assignment_history.count(), 1)
        self.assertEqual(lead.tasks.filter(kind='unassigned').count(), 1)
        self.assertEqual(retry_unassigned(), 0)
        configure_profile(actor=self.manager, user=self.owner, is_available=True)
        self.assertEqual(retry_unassigned(), 1)
        lead.refresh_from_db()
        self.assertEqual(lead.owner_id, self.owner.pk)
        self.assertEqual(lead.tasks.get(kind='unassigned').status, 'cancelled')

    def test_closed_leads_release_capacity_and_cancel_pending_tasks(self):
        configure_profile(actor=self.manager, user=self.owner, max_active_leads=1)
        configure_profile(actor=self.manager, user=self.manager, can_receive_leads=False)
        first = self.enquiry()
        queued = self.enquiry()
        self.assertIsNone(queued.owner_id)
        update_lead(actor=self.manager, lead=first, status='lost')
        self.assertFalse(first.tasks.filter(status='pending').exists())
        self.assertEqual(retry_unassigned(), 1)

    def test_manual_override_requires_manager_reason_and_eligible_target(self):
        lead = self.enquiry()
        with self.assertRaises(PermissionDenied):
            manual_assign(lead=lead, actor=self.owner, owner=self.manager, reason='Steal')
        with self.assertRaises(ValidationError):
            manual_assign(lead=lead, actor=self.manager, owner=self.manager, reason=' ')
        with self.assertRaises(ValidationError):
            manual_assign(lead=lead, actor=self.manager, owner=self.other, reason='Wrong branch')
        reassigned = manual_assign(lead=lead, actor=self.manager, owner=self.manager, reason='Approved coverage change')
        history = reassigned.assignment_history.first()
        self.assertEqual(history.previous_owner_id, self.owner.pk)
        self.assertEqual(history.new_owner_id, self.manager.pk)
        self.assertEqual(history.actor_id, self.manager.pk)
        self.assertEqual(history.reason, 'Approved coverage change')
        self.assertEqual(reassigned.assignment_version, 2)

    def test_branch_transfer_is_explicit_global_and_preserves_old_activity(self):
        lead = self.enquiry()
        with self.assertRaises(PermissionDenied):
            transfer_lead(lead=lead, actor=self.manager, branch=self.b, reason='Transfer')
        moved = transfer_lead(lead=lead, actor=self.management, branch=self.b, reason='Student requested BTM')
        history = moved.assignment_history.first()
        self.assertEqual(moved.owner_id, self.other.pk)
        self.assertEqual(history.previous_branch_id, self.a.pk)
        self.assertEqual(history.branch_id, self.b.pk)
        self.assertEqual(history.previous_owner_id, self.owner.pk)
        self.assertEqual(history.status, 'transferred')
        self.assertTrue(moved.activities.filter(branch=self.a).exists())
        self.assertTrue(moved.tasks.filter(branch=self.a, status='cancelled').exists())

    def test_acknowledgement_is_owner_only_and_idempotent(self):
        lead = self.enquiry()
        with self.assertRaises(PermissionDenied):
            acknowledge(lead=lead, actor=self.manager)
        acknowledged = acknowledge(lead=lead, actor=self.owner)
        acknowledge(lead=lead, actor=self.owner)
        self.assertIsNotNone(acknowledged.acknowledged_at)
        self.assertEqual(lead.assignment_history.filter(status='acknowledged').count(), 1)
        self.assertEqual(lead.tasks.get(kind='acknowledgement').status, 'completed')

    def test_profile_limits_and_authorization_cannot_be_changed_by_counsellor(self):
        configure_profile(actor=self.owner, user=self.owner, is_available=False)
        with self.assertRaises(PermissionDenied):
            configure_profile(actor=self.owner, user=self.owner, max_active_leads=999)
        with self.assertRaises(PermissionDenied):
            configure_profile(actor=self.owner, user=self.manager, is_available=False)

    def test_assignment_rollback_includes_rotation_tasks_and_history(self):
        with patch('routing.services.AssignmentHistory.objects.create', side_effect=RuntimeError('Storage failed')):
            with self.assertRaises(RuntimeError):
                self.enquiry()
        self.assertFalse(Lead.objects.exists())
        self.assertFalse(FollowUpTask.objects.exists())
        self.assertFalse(AssignmentHistory.objects.exists())
        self.assertFalse(RoutingPolicy.objects.exists())

    def test_history_is_immutable_in_model_api_and_postgres(self):
        lead = self.enquiry()
        history = lead.assignment_history.get()
        with self.assertRaises(DjangoValidationError):
            history.save()
        with self.assertRaises(DjangoValidationError):
            history.delete()
        url = '/api/v1/assignment-history/%s/' % history.pk
        self.assertEqual(self.client.patch(url, {'reason': 'Altered'}).status_code, 405)
        self.assertEqual(self.client.delete(url).status_code, 405)
        if connection.vendor == 'postgresql':
            for action in (lambda: AssignmentHistory.objects.filter(pk=history.pk).update(reason='Tampered'),
                           lambda: AssignmentHistory.objects.filter(pk=history.pk).delete()):
                with self.assertRaises(DatabaseError), transaction.atomic():
                    action()

    def test_routing_api_scope_profile_access_and_overrides(self):
        lead = self.enquiry()
        self.assertEqual(self.client.post('/api/v1/routing/route/', {'lead': str(lead.pk)}, format='json').status_code, 200)
        profile_url = '/api/v1/counsellor-profiles/%s/' % self.owner.counsellor_profile.pk
        self.client.force_authenticate(self.owner)
        self.assertEqual(self.client.patch(profile_url, {'is_available': False}, format='json').status_code, 200)
        self.assertEqual(self.client.patch(profile_url, {'max_active_leads': 999}, format='json').status_code, 403)
        self.assertEqual(self.client.post('/api/v1/routing/override/', {'lead': str(lead.pk), 'owner': str(self.manager.pk), 'reason': 'Steal'}, format='json').status_code, 403)
        self.client.force_authenticate(self.other)
        self.assertEqual(self.client.post('/api/v1/routing/route/', {'lead': str(lead.pk)}, format='json').status_code, 400)
        self.assertEqual(self.client.get('/api/v1/assignment-history/').data['count'], 0)
        self.client.force_authenticate(self.manager)
        self.assertEqual(self.client.post('/api/v1/routing-policies/', {'branch': str(self.a.pk), 'acknowledgement_minutes': 0}, format='json').status_code, 400)
        self.assertEqual(self.client.post('/api/v1/routing/route/', {'lead': str(lead.pk), 'branch': str(self.b.pk)}, format='json').status_code, 400)

    def test_new_users_need_explicit_routing_enablement_and_unassigned_api(self):
        CounsellorProfile.objects.filter(user__branch=self.a).update(can_receive_leads=False)
        get_user_model().objects.create_user(username='not-enabled', branch=self.a)
        lead = self.enquiry()
        self.assertIsNone(lead.owner_id)
        self.assertEqual(self.client.get('/api/v1/unassigned/').data['count'], 1)
        self.client.force_authenticate(self.other)
        self.assertEqual(self.client.get('/api/v1/unassigned/').data['count'], 0)
