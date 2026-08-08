from django.db import migrations, models
import django.db.models.deletion
import django.utils.timezone


class Migration(migrations.Migration):

    dependencies = [
        ('billboard', '0009_billboardentry_is_anonymous'),
        ('courts', '0001_initial'),
    ]

    operations = [
        # Add last_anonymous_choice to UserPresencePrefs
        migrations.AddField(
            model_name='userpresenceprefs',
            name='last_anonymous_choice',
            field=models.BooleanField(
                default=False,
                help_text='True if the player last declared presence as anonymous.',
            ),
        ),
        # Create CommunityPresenceReport table
        migrations.CreateModel(
            name='CommunityPresenceReport',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('reported_count', models.PositiveIntegerField(
                    help_text='Estimated total number of people physically present.'
                )),
                ('confirmation_count', models.PositiveIntegerField(
                    default=1,
                    help_text='Number of players who confirmed this count.',
                )),
                ('last_reporter_codename', models.CharField(
                    max_length=6,
                    help_text='Codename of the player who last reported/updated (internal).',
                )),
                ('confirming_codenames', models.TextField(
                    blank=True,
                    default='',
                    help_text='Comma-separated codenames of confirming players (internal).',
                )),
                ('last_updated', models.DateTimeField(default=django.utils.timezone.now)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('court_complex', models.OneToOneField(
                    on_delete=django.db.models.deletion.CASCADE,
                    related_name='community_presence_report',
                    to='courts.courtcomplex',
                    help_text='One active report per court complex.',
                )),
            ],
            options={
                'verbose_name': 'Community Presence Report',
                'verbose_name_plural': 'Community Presence Reports',
            },
        ),
    ]
