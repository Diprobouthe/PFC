from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('billboard', '0008_billboardentry_expires_at_post_game'),
    ]

    operations = [
        migrations.AddField(
            model_name='billboardentry',
            name='is_anonymous',
            field=models.BooleanField(
                default=False,
                help_text='If True, the player is counted as verified-present but their name is not shown publicly.',
            ),
        ),
    ]
