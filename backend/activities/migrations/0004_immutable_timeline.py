from django.db import migrations


def install(apps, schema_editor):
    if schema_editor.connection.vendor == 'postgresql':
        schema_editor.execute('''
            CREATE FUNCTION crm_reject_activity_mutation() RETURNS trigger LANGUAGE plpgsql AS $$
            BEGIN
                RAISE EXCEPTION 'Timeline entries are immutable';
            END; $$;
            CREATE TRIGGER crm_activity_immutable BEFORE UPDATE OR DELETE ON activities_activity
            FOR EACH ROW EXECUTE FUNCTION crm_reject_activity_mutation();
        ''')


def uninstall(apps, schema_editor):
    if schema_editor.connection.vendor == 'postgresql':
        schema_editor.execute('''
            DROP TRIGGER IF EXISTS crm_activity_immutable ON activities_activity;
            DROP FUNCTION IF EXISTS crm_reject_activity_mutation();
        ''')


class Migration(migrations.Migration):
    dependencies = [('activities', '0003_initial')]
    operations = [migrations.RunPython(install, uninstall)]
