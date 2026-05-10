from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('teams', '0007_update_position_choices'),
    ]

    operations = [
        migrations.AddField(
            model_name='team',
            name='is_archived',
            field=models.BooleanField(
                default=False,
                help_text='Archived teams are hidden from all dropdowns and selection fields. History is preserved.'
            ),
        ),
    ]
