from io import StringIO
from unittest.mock import patch
from django.core.management import call_command, CommandError
from django.test import SimpleTestCase, override_settings


class LocalJobsTests(SimpleTestCase):
    @override_settings(DEBUG=False, WHATSAPP_MODE='mock')
    def test_refuses_production(self):
        with self.assertRaises(CommandError):
            call_command('run_local_jobs', once=True)

    @override_settings(DEBUG=True, WHATSAPP_MODE='live')
    def test_refuses_live_messaging(self):
        with self.assertRaises(CommandError):
            call_command('run_local_jobs', once=True)

    @override_settings(DEBUG=True, WHATSAPP_MODE='mock')
    def test_failed_stage_does_not_block_other_jobs(self):
        from common.management.commands import run_local_jobs
        with patch.multiple(run_local_jobs, run_cycle=lambda: None,
                            process_slas=lambda: None, retry_unassigned=lambda: None), \
                patch.object(run_local_jobs, 'process_webhooks', autospec=True, side_effect=RuntimeError), \
                patch.object(run_local_jobs, 'dispatch_outbox', autospec=True, return_value=0) as dispatch:
            errors = StringIO()
            call_command('run_local_jobs', once=True, stdout=StringIO(), stderr=errors)
            dispatch.assert_called_once()
            self.assertIn('RuntimeError; retry next cycle', errors.getvalue())
