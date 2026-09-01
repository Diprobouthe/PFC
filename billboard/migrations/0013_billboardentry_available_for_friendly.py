# Generated manually for the PFC session-scoped Friendly availability feature.
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('billboard', '0010_presence_prefs_anon_community_report'),
    ]

    operations = [
        migrations.AddField(
            model_name='billboardentry',
            name='available_for_friendly',
            field=models.BooleanField(
                default=False,
                help_text='Allow Friendly creators at this Court Complex to add this present player during pre-start setup.',
            ),
        ),
    ]
