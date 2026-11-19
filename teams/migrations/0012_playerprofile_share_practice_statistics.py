from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('teams', '0011_playerprofile_privacy_boules'),
    ]

    operations = [
        migrations.AddField(
            model_name='playerprofile',
            name='share_practice_statistics',
            field=models.BooleanField(
                default=False,
                help_text=(
                    'Opt in to showing aggregated shooting and pointing practice progress '
                    'on the public player profile; individual sessions remain private.'
                ),
            ),
        ),
    ]
