from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('teams', '0010_team_is_tournament_temp'),
    ]

    operations = [
        migrations.AddField(
            model_name='playerprofile',
            name='hide_public_statistics',
            field=models.BooleanField(
                default=False,
                help_text='Hide rating and statistical summaries from other users while preserving personal access.',
            ),
        ),
        migrations.AddField(
            model_name='playerprofile',
            name='boule_brand',
            field=models.CharField(blank=True, default='', max_length=80),
        ),
        migrations.AddField(
            model_name='playerprofile',
            name='boule_diameter_mm',
            field=models.PositiveSmallIntegerField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name='playerprofile',
            name='boule_weight_g',
            field=models.PositiveSmallIntegerField(blank=True, null=True),
        ),
    ]
