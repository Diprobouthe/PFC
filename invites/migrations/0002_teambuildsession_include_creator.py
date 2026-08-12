from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("invites", "0001_initial"),
    ]

    operations = [
        migrations.AddField(
            model_name="teambuildsession",
            name="include_creator",
            field=models.BooleanField(
                default=True,
                help_text="Whether the session creator is counted and added to the final team roster.",
            ),
        ),
    ]
