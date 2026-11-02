from django.db import migrations


def branch_code(branch):
    return {'kalyan-nagar': 'KN', 'marathahalli': 'MT', 'btm-layout': 'BTM'}.get(
        branch.code, ''.join(c for c in branch.code.upper() if c.isalnum())[:8])


def forwards(apps, schema_editor):
    Lead = apps.get_model('leads', 'Lead')
    History = apps.get_model('routing', 'AssignmentHistory')
    Branch = apps.get_model('branches', 'Branch')
    pg = schema_editor.connection.vendor == 'postgresql'
    if pg:
        schema_editor.execute('LOCK TABLE leads_lead IN ACCESS EXCLUSIVE MODE')
    branches = {b.pk: b for b in Branch.objects.all()}
    changes = []
    for lead in Lead.objects.all().iterator():
        first = History.objects.filter(lead_id=lead.pk).order_by('version', 'created_at', 'pk').first()
        origin_id = first.previous_branch_id if first else lead.branch_id
        code = branch_code(branches[origin_id])
        identifier = f'LMT-{code}-L-{lead.lead_id.rsplit("-", 1)[-1]}'
        if Lead.objects.filter(lead_id=identifier).exclude(pk=lead.pk).exists():
            raise RuntimeError('Branch ID migration stopped: identifier collision.')
        changes.append((lead.pk, dict(lead_id=identifier, legacy_lead_id=lead.lead_id,
            origin_branch_id=origin_id, origin_branch_code=code, origin_branch_verified=first is not None)))
    if pg:
        schema_editor.execute('DROP TRIGGER crm_lead_id_immutable ON leads_lead')
    for pk, values in changes:
        Lead.objects.filter(pk=pk).update(**values)
    if pg:
        schema_editor.execute("CREATE TRIGGER crm_lead_id_immutable BEFORE UPDATE ON leads_lead FOR EACH ROW EXECUTE FUNCTION crm_protect_readable_id('lead_id')")
        schema_editor.execute("CREATE TRIGGER crm_lead_origin_immutable BEFORE UPDATE ON leads_lead FOR EACH ROW EXECUTE FUNCTION crm_protect_readable_id('origin_branch_id')")
        schema_editor.execute("CREATE TRIGGER crm_lead_origin_code_immutable BEFORE UPDATE ON leads_lead FOR EACH ROW EXECUTE FUNCTION crm_protect_readable_id('origin_branch_code')")


def backwards(apps, schema_editor):
    Lead = apps.get_model('leads', 'Lead')
    pg = schema_editor.connection.vendor == 'postgresql'
    if pg:
        schema_editor.execute('LOCK TABLE leads_lead IN ACCESS EXCLUSIVE MODE')
        for trigger in ['crm_lead_id_immutable', 'crm_lead_origin_immutable', 'crm_lead_origin_code_immutable']:
            schema_editor.execute(f'DROP TRIGGER {trigger} ON leads_lead')
    for lead in Lead.objects.all().iterator():
        Lead.objects.filter(pk=lead.pk).update(lead_id=lead.legacy_lead_id or 'LMT-L-'+lead.lead_id.rsplit('-', 1)[-1])
    if pg:
        schema_editor.execute("CREATE TRIGGER crm_lead_id_immutable BEFORE UPDATE ON leads_lead FOR EACH ROW EXECUTE FUNCTION crm_protect_readable_id('lead_id')")


class Migration(migrations.Migration):
    atomic = True
    dependencies = [('common', '0004_lmt_ids_and_received_dates'), ('leads', '0004_lead_legacy_lead_id_lead_origin_branch_and_more'), ('routing', '0002_immutable_assignment_history')]
    operations = [migrations.RunPython(forwards, backwards)]
