from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('courts', '0009_add_user_presence_prefs'),
    ]

    operations = [
        migrations.AddField(
            model_name='courtcomplex',
            name='timezone_name',
            field=models.CharField(
                default='Europe/Athens',
                help_text="IANA timezone name for this court complex (e.g. 'Europe/Athens', 'America/New_York')",
                max_length=100,
            ),
        ),
    ]
