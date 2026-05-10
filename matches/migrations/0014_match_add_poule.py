"""
matches/migrations/0014_match_add_poule.py
Add nullable poule FK to Match so poule matches can be identified
and their court pool can be constrained at activation time.
"""
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ('matches', '0013_add_timer_fields'),
        ('tournaments', '0020_poule_pouleteam'),
    ]

    operations = [
        migrations.AddField(
            model_name='match',
            name='poule',
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name='matches',
                to='tournaments.poule',
                help_text='Poule this match belongs to (only set for poule-format stages)',
            ),
        ),
    ]
