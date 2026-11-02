from django.db import migrations


def install(apps, schema_editor):
    if schema_editor.connection.vendor == 'postgresql':
        schema_editor.execute('''
            CREATE FUNCTION crm_reject_assignment_mutation() RETURNS trigger LANGUAGE plpgsql AS $$
            BEGIN
                RAISE EXCEPTION 'Assignment history is immutable';
            END; $$;
            CREATE TRIGGER crm_assignment_immutable BEFORE UPDATE OR DELETE ON routing_assignmenthistory
            FOR EACH ROW EXECUTE FUNCTION crm_reject_assignment_mutation();
        ''')


def uninstall(apps, schema_editor):
    if schema_editor.connection.vendor == 'postgresql':
        schema_editor.execute('''
            DROP TRIGGER IF EXISTS crm_assignment_immutable ON routing_assignmenthistory;
            DROP FUNCTION IF EXISTS crm_reject_assignment_mutation();
        ''')


class Migration(migrations.Migration):
    dependencies = [('routing', '0001_initial')]
    operations = [migrations.RunPython(install, uninstall)]
