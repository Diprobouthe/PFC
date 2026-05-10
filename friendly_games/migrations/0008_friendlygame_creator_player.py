from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ('friendly_games', '0007_add_court_and_timed_fields'),
        ('teams', '0008_team_is_archived'),
    ]

    operations = [
        migrations.AddField(
            model_name='friendlygame',
            name='creator_player',
            field=models.ForeignKey(
                blank=True,
                help_text='Player who created this game (only they can start it)',
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name='created_friendly_games',
                to='teams.player',
            ),
        ),
    ]
