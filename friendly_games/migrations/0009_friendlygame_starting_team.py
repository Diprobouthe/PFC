from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('friendly_games', '0008_friendlygame_creator_player'),
    ]

    operations = [
        migrations.AddField(
            model_name='friendlygame',
            name='starting_team',
            field=models.CharField(
                blank=True,
                choices=[('BLACK', 'Black Team'), ('WHITE', 'White Team')],
                default='',
                help_text='Side selected at random to start the Friendly Game',
                max_length=10,
            ),
        ),
    ]
