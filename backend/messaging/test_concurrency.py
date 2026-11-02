from concurrent.futures import ThreadPoolExecutor
from threading import Barrier, Lock
from unittest.mock import patch
from django.db import close_old_connections, connection, connections
from django.test import TransactionTestCase, override_settings
from django.utils import timezone
from common.test_utils import crm_fixtures
from .models import Channel, Conversation, Message, WebhookDelivery
from .services import enqueue, dispatch_message, process_delivery


@override_settings(WHATSAPP_MODE='mock', WHATSAPP_LIVE_SENDS_ENABLED=False)
class MessagingConcurrencyTests(TransactionTestCase):
    def setUp(self):
        if connection.vendor != 'postgresql':
            self.skipTest('Messaging concurrency requires PostgreSQL row locks.')
        a, _, self.owner, _, _, _, _ = crm_fixtures()
        self.channel = Channel.objects.create(branch=a, name='Inbox', phone_number_id='123', waba_id='456')
        self.conversation = Conversation.objects.create(channel=self.channel, wa_id='919876543210', last_inbound_at=timezone.now())

    def workers(self, function):
        barrier = Barrier(4)
        def run(_):
            close_old_connections()
            try:
                barrier.wait(timeout=20)
                return function()
            finally:
                connections.close_all()
        with ThreadPoolExecutor(max_workers=4) as pool:
            return list(pool.map(run, range(4)))

    def test_same_request_concurrently_creates_one_outbound_message(self):
        results = self.workers(lambda: enqueue(actor=self.owner, conversation=self.conversation, client_key='same-key', text='Hello').pk)
        self.assertEqual(len(set(results)), 1)
        self.assertEqual(Message.objects.count(), 1)

    def test_concurrent_dispatch_claims_send_once(self):
        message = enqueue(actor=self.owner, conversation=self.conversation, client_key='key', text='Hello')
        calls, lock = [], Lock()
        def send(row):
            with lock:
                calls.append(row.pk)
            return 'mock.' + str(row.pk)
        with patch('messaging.services.send_message', side_effect=send):
            self.workers(lambda: dispatch_message(message.pk))
        self.assertEqual(len(calls), 1)
        message.refresh_from_db()
        self.assertEqual(message.queue_status, 'sent')

    def test_concurrent_duplicate_receipt_processes_inbound_once(self):
        payload = {'entry': [{'id': '456', 'changes': [{'field': 'messages', 'value': {'metadata': {'phone_number_id': '123'},
            'messages': [{'id': 'wamid.one', 'from': '919876543210', 'timestamp': str(int(timezone.now().timestamp())), 'type': 'text', 'text': {'body': 'Hello'}}]}}]}]}
        receipt = WebhookDelivery.objects.create(digest='one', payload=payload)
        self.workers(lambda: process_delivery(receipt.pk))
        self.assertEqual(Message.objects.filter(direction='inbound').count(), 1)
