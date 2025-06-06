# Generated by Django 5.2 on 2025-05-01 15:50

import django.db.models.deletion
import django.utils.timezone
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('teams', '0001_initial'),
        ('tournaments', '0004_alter_tournamentteam_options_and_more'),
    ]

    operations = [
        migrations.AlterModelOptions(
            name='tournamentteam',
            options={'ordering': ['-swiss_points', '-buchholz_score', 'seeding_position', 'id']},
        ),
        migrations.RenameField(
            model_name='round',
            old_name='is_complete',
            new_name='is_completed',
        ),
        migrations.RemoveField(
            model_name='round',
            name='end_time',
        ),
        migrations.RemoveField(
            model_name='round',
            name='start_time',
        ),
        migrations.AddField(
            model_name='round',
            name='created_at',
            field=models.DateTimeField(auto_now_add=True, default=django.utils.timezone.now),
            preserve_default=False,
        ),
        migrations.AddField(
            model_name='tournament',
            name='automation_status',
            field=models.CharField(choices=[('idle', 'Idle'), ('processing', 'Processing'), ('error', 'Error'), ('completed', 'Completed')], default='idle', help_text='Status of the automated round generation', max_length=20),
        ),
        migrations.AddField(
            model_name='tournament',
            name='current_round_number',
            field=models.PositiveIntegerField(blank=True, default=0, help_text='Current round being played or 0 if not started', null=True),
        ),
        migrations.AddField(
            model_name='tournamentteam',
            name='buchholz_score',
            field=models.FloatField(default=0.0, help_text='Sum of opponents scores (Buchholz tie-breaker)'),
        ),
        migrations.AddField(
            model_name='tournamentteam',
            name='created_at',
            field=models.DateTimeField(auto_now_add=True, default=django.utils.timezone.now),
            preserve_default=False,
        ),
        migrations.AddField(
            model_name='tournamentteam',
            name='opponents_played',
            field=models.ManyToManyField(blank=True, related_name='played_against_in_tournament', to='teams.team'),
        ),
        migrations.AddField(
            model_name='tournamentteam',
            name='received_bye_in_round',
            field=models.PositiveIntegerField(blank=True, help_text='Round number in which the team received a bye', null=True),
        ),
        migrations.AddField(
            model_name='tournamentteam',
            name='swiss_points',
            field=models.IntegerField(default=0, help_text='Points accumulated in Swiss format'),
        ),
        migrations.AddField(
            model_name='tournamentteam',
            name='updated_at',
            field=models.DateTimeField(auto_now=True),
        ),
        migrations.AlterField(
            model_name='bracket',
            name='round',
            field=models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, to='tournaments.round'),
        ),
        migrations.AlterField(
            model_name='bracket',
            name='tournament',
            field=models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, to='tournaments.tournament'),
        ),
        migrations.AlterField(
            model_name='round',
            name='number_in_stage',
            field=models.PositiveIntegerField(blank=True, help_text='Round number within the current stage (if multi-stage)', null=True),
        ),
        migrations.AlterField(
            model_name='tournamentteam',
            name='current_stage_number',
            field=models.PositiveIntegerField(default=1, help_text='The stage number the team is currently in (for multi-stage)'),
        ),
        migrations.AlterField(
            model_name='tournamentteam',
            name='is_active',
            field=models.BooleanField(default=True, help_text='Whether the team is currently active in the tournament'),
        ),
    ]
