# Generated manually for the PFC persistent Friendly availability preference.
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('billboard', '0010_presence_prefs_anon_community_report'),
    ]

    operations = [
        migrations.AddField(
            model_name='userpresenceprefs',
            name='available_for_friendly',
            field=models.BooleanField(
                default=False,
                help_text='Allow Friendly creators to select this player whenever they are currently present at the same Court Complex.',
            ),
        ),
    ]
