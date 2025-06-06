# Generated by Django 5.2 on 2025-04-23 16:30

import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):

    initial = True

    dependencies = [
        ('matches', '0001_initial'),
        ('teams', '0001_initial'),
        ('tournaments', '0001_initial'),
    ]

    operations = [
        migrations.CreateModel(
            name='Leaderboard',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('last_updated', models.DateTimeField(auto_now=True)),
                ('tournament', models.OneToOneField(on_delete=django.db.models.deletion.CASCADE, related_name='leaderboard', to='tournaments.tournament')),
            ],
        ),
        migrations.CreateModel(
            name='MatchStatistics',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('team1_points_by_round', models.JSONField(default=list)),
                ('team2_points_by_round', models.JSONField(default=list)),
                ('match_duration_minutes', models.PositiveIntegerField(blank=True, null=True)),
                ('notes', models.TextField(blank=True, null=True)),
                ('match', models.OneToOneField(on_delete=django.db.models.deletion.CASCADE, related_name='statistics', to='matches.match')),
            ],
        ),
        migrations.CreateModel(
            name='TeamStatistics',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('total_matches_played', models.PositiveIntegerField(default=0)),
                ('total_matches_won', models.PositiveIntegerField(default=0)),
                ('total_matches_lost', models.PositiveIntegerField(default=0)),
                ('total_points_scored', models.PositiveIntegerField(default=0)),
                ('total_points_conceded', models.PositiveIntegerField(default=0)),
                ('tournaments_participated', models.PositiveIntegerField(default=0)),
                ('tournaments_won', models.PositiveIntegerField(default=0)),
                ('last_updated', models.DateTimeField(auto_now=True)),
                ('team', models.OneToOneField(on_delete=django.db.models.deletion.CASCADE, related_name='statistics', to='teams.team')),
            ],
        ),
        migrations.CreateModel(
            name='LeaderboardEntry',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('position', models.PositiveIntegerField()),
                ('matches_played', models.PositiveIntegerField(default=0)),
                ('matches_won', models.PositiveIntegerField(default=0)),
                ('matches_lost', models.PositiveIntegerField(default=0)),
                ('points_scored', models.PositiveIntegerField(default=0)),
                ('points_conceded', models.PositiveIntegerField(default=0)),
                ('leaderboard', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='entries', to='leaderboards.leaderboard')),
                ('team', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='leaderboard_entries', to='teams.team')),
            ],
            options={
                'ordering': ['position'],
                'unique_together': {('leaderboard', 'team')},
            },
        ),
    ]
