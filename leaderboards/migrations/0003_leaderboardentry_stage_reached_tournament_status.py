"""
Migration: add stage_reached and tournament_status to LeaderboardEntry.

These fields support the global multi-stage leaderboard so that ALL teams
(including those eliminated in earlier stages) are always shown with their
correct status and the highest stage they reached.
"""
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('leaderboards', '0002_leaderboardentry_buchholz_score_and_more'),
    ]

    operations = [
        migrations.AddField(
            model_name='leaderboardentry',
            name='stage_reached',
            field=models.PositiveIntegerField(
                default=1,
                help_text='Highest stage number this team reached in the tournament',
            ),
        ),
        migrations.AddField(
            model_name='leaderboardentry',
            name='tournament_status',
            field=models.CharField(
                max_length=30,
                default='active',
                help_text='Team status: active, eliminated, champion, finalist, semi-finalist',
            ),
        ),
    ]
