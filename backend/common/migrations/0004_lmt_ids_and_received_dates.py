"""Controlled rebranding; numeric sequences and UUID relationships are preserved."""
from django.db import migrations
from django.db.models import F


def rename_ids(apps, schema_editor, old, new):
    pairs = [(apps.get_model('contacts', 'Contact'), 'contact_id', 'C'), (apps.get_model('leads', 'Lead'), 'lead_id', 'L')]
    if schema_editor.connection.vendor == 'postgresql':
        schema_editor.execute('LOCK TABLE contacts_contact, leads_lead IN ACCESS EXCLUSIVE MODE')
    changes = []
    for model, field, kind in pairs:
        rows = list(model.objects.filter(**{field+'__startswith': f'{old}-{kind}-'}).values_list('pk', field))
        for pk, value in rows:
            replacement = new + value[len(old):]
            if model.objects.filter(**{field: replacement}).exclude(pk=pk).exists():
                raise RuntimeError('LMT ID migration stopped: identifier collision; no IDs were changed.')
            changes.append((model, field, pk, replacement))
    if schema_editor.connection.vendor == 'postgresql':
        schema_editor.execute('DROP TRIGGER crm_contact_id_immutable ON contacts_contact')
        schema_editor.execute('DROP TRIGGER crm_lead_id_immutable ON leads_lead')
    for model, field, pk, replacement in changes:
        model.objects.filter(pk=pk).update(**{field: replacement})
    if schema_editor.connection.vendor == 'postgresql':
        schema_editor.execute("CREATE TRIGGER crm_contact_id_immutable BEFORE UPDATE ON contacts_contact FOR EACH ROW EXECUTE FUNCTION crm_protect_readable_id('contact_id')")
        schema_editor.execute("CREATE TRIGGER crm_lead_id_immutable BEFORE UPDATE ON leads_lead FOR EACH ROW EXECUTE FUNCTION crm_protect_readable_id('lead_id')")


def forwards(apps, schema_editor):
    rename_ids(apps, schema_editor, 'LM', 'LMT')
    Lead = apps.get_model('leads', 'Lead')
    Lead.objects.all().update(received_at=F('created_at'), received_via='crm_recorded')
    for call in apps.get_model('calls', 'CallLog').objects.exclude(lead_id=None).iterator():
        Lead.objects.filter(pk=call.lead_id, source='call').update(received_at=call.started_at, received_via='call_started')
    for submission in apps.get_model('intake', 'WebsiteSubmission').objects.exclude(lead_id=None).iterator():
        Lead.objects.filter(pk=submission.lead_id, source='website').update(received_at=submission.created_at, received_via='website_received')


def backwards(apps, schema_editor):
    rename_ids(apps, schema_editor, 'LMT', 'LM')


class Migration(migrations.Migration):
    atomic = True
    dependencies = [('common', '0003_immutable_readable_ids'), ('leads', '0003_lead_received_at_lead_received_via'),
        ('calls', '0001_initial'), ('intake', '0001_initial'), ('messaging', '0003_channel_auto_intake_channel_intake_actor_and_more')]
    operations = [migrations.RunPython(forwards, backwards)]
