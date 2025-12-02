# Generated migration for TeamMatchParticipant model

from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ('matches', '0009_alter_matchplayer_role'),
        ('teams', '0005_teamprofile'),
    ]

    operations = [
        migrations.CreateModel(
            name='TeamMatchParticipant',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('position', models.CharField(choices=[('pointer', 'Pointer'), ('milieu', 'Milieu'), ('shooter', 'Shooter/Tireur'), ('flex', 'Flex'), ('substitute', 'Substitute')], default='flex', help_text="Player's position/role in the match", max_length=20)),
                ('played', models.BooleanField(default=True, help_text='Whether the player actually played (True) or was DNP (False)')),
                ('is_substitute', models.BooleanField(default=False, help_text='Whether this player was a substitute who came in during the match')),
                ('minutes_played', models.PositiveIntegerField(blank=True, help_text='Minutes played (optional, for future use)', null=True)),
                ('sets_played', models.PositiveIntegerField(blank=True, help_text='Number of sets played (optional, for future use)', null=True)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
                ('match', models.ForeignKey(help_text='The match this participation record belongs to', on_delete=django.db.models.deletion.CASCADE, related_name='participants', to='matches.match')),
                ('player', models.ForeignKey(help_text='The player who participated', on_delete=django.db.models.deletion.CASCADE, related_name='team_match_participations', to='teams.player')),
                ('team', models.ForeignKey(help_text='The team this player participated for', on_delete=django.db.models.deletion.CASCADE, related_name='match_participations', to='teams.team')),
            ],
            options={
                'verbose_name': 'Team Match Participant',
                'verbose_name_plural': 'Team Match Participants',
                'ordering': ['match', 'team', 'position'],
            },
        ),
        migrations.AlterUniqueTogether(
            name='teammatchparticipant',
            unique_together={('match', 'player')},
        ),
    ]

