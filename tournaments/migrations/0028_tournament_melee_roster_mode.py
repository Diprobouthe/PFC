# Generated for PFC Mêlée P4 on 2026-09-18

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("tournaments", "0027_meleeroundassignment"),
    ]

    operations = [
        migrations.AddField(
            model_name="tournament",
            name="melee_roster_mode",
            field=models.CharField(
                choices=[
                    ("legacy_transferred", "Legacy temporary Player.team transfer"),
                    ("assignment_based", "Round-assignment roster"),
                ],
                default="legacy_transferred",
                help_text=(
                    "Persisted Mêlée roster implementation. Existing tournaments remain "
                    "legacy-compatible; P4 generation sets assignment_based."
                ),
                max_length=32,
            ),
        ),
    ]
