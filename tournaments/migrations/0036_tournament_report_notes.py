from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("tournaments", "0035_stage_third_place_playoff")]

    operations = [
        migrations.AddField(
            model_name="tournament",
            name="report_notes",
            field=models.TextField(
                blank=True, default="",
                help_text="Organizer observations printed on the tournament PDF report.",
            ),
        ),
    ]
