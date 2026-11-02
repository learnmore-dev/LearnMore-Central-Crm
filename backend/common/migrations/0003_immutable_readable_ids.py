from django.db import migrations


def install(apps, schema_editor):
    if schema_editor.connection.vendor == 'postgresql':
        schema_editor.execute('''
            CREATE FUNCTION crm_protect_readable_id() RETURNS trigger LANGUAGE plpgsql AS $$
            BEGIN
                IF to_jsonb(OLD)->>TG_ARGV[0] IS DISTINCT FROM to_jsonb(NEW)->>TG_ARGV[0] THEN
                    RAISE EXCEPTION 'Readable CRM IDs cannot be changed';
                END IF;
                RETURN NEW;
            END; $$;
            CREATE TRIGGER crm_contact_id_immutable BEFORE UPDATE ON contacts_contact
            FOR EACH ROW EXECUTE FUNCTION crm_protect_readable_id('contact_id');
            CREATE TRIGGER crm_lead_id_immutable BEFORE UPDATE ON leads_lead
            FOR EACH ROW EXECUTE FUNCTION crm_protect_readable_id('lead_id');
        ''')


def uninstall(apps, schema_editor):
    if schema_editor.connection.vendor == 'postgresql':
        schema_editor.execute('''
            DROP TRIGGER IF EXISTS crm_contact_id_immutable ON contacts_contact;
            DROP TRIGGER IF EXISTS crm_lead_id_immutable ON leads_lead;
            DROP FUNCTION IF EXISTS crm_protect_readable_id();
        ''')


class Migration(migrations.Migration):
    dependencies = [('common', '0002_seed_sequences'), ('contacts', '0001_initial'), ('leads', '0001_initial')]
    operations = [migrations.RunPython(install, uninstall)]
