from django.db import migrations


def seed_sequences(apps, schema_editor):
    sequence = apps.get_model('common', 'IdentifierSequence')
    for name in ('contact', 'lead'):
        sequence.objects.using(schema_editor.connection.alias).get_or_create(name=name)


class Migration(migrations.Migration):
    dependencies = [('common', '0001_initial')]
    operations = [migrations.RunPython(seed_sequences, migrations.RunPython.noop)]
