"""
tournaments/migrations/0020_poule_pouleteam.py
Create Poule and PouleTeam models.
"""
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ('tournaments', '0019_pregame_countdown_minutes'),
        ('courts', '0010_courtcomplex_timezone_name'),
        ('teams', '0007_update_position_choices'),
    ]

    operations = [
        migrations.CreateModel(
            name='Poule',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('name', models.CharField(help_text="Display name, e.g. 'Group A' or 'Poule 1'", max_length=100)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
                ('stage', models.ForeignKey(
                    help_text="The stage this poule belongs to (must have format='poule')",
                    on_delete=django.db.models.deletion.CASCADE,
                    related_name='poules',
                    to='tournaments.stage',
                )),
                ('courts', models.ManyToManyField(
                    blank=True,
                    help_text='Courts assigned to this poule. Matches within this poule use ONLY these courts.',
                    related_name='poules',
                    to='courts.court',
                )),
            ],
            options={
                'verbose_name': 'Poule / Group',
                'verbose_name_plural': 'Poules / Groups',
                'ordering': ['stage', 'name'],
            },
        ),
        migrations.AddConstraint(
            model_name='poule',
            constraint=models.UniqueConstraint(fields=['stage', 'name'], name='unique_poule_name_per_stage'),
        ),
        migrations.CreateModel(
            name='PouleTeam',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('position', models.PositiveSmallIntegerField(
                    default=0,
                    help_text='Seeding position within the poule (lower = higher seed)',
                )),
                ('poule', models.ForeignKey(
                    on_delete=django.db.models.deletion.CASCADE,
                    related_name='pouleteam_set',
                    to='tournaments.poule',
                )),
                ('team', models.ForeignKey(
                    on_delete=django.db.models.deletion.CASCADE,
                    related_name='poule_assignments',
                    to='teams.team',
                )),
            ],
            options={
                'verbose_name': 'Poule Team Assignment',
                'verbose_name_plural': 'Poule Team Assignments',
                'ordering': ['poule', 'position', 'team__name'],
            },
        ),
        migrations.AddConstraint(
            model_name='pouleteam',
            constraint=models.UniqueConstraint(fields=['poule', 'team'], name='unique_team_per_poule'),
        ),
    ]
