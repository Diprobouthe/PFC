from django.db import migrations, models

class Migration(migrations.Migration):
    dependencies = [("simple_creator", "0018_tournamentscenario_lineup_selection_seconds")]
    operations = [
        migrations.AddField(
            model_name="scenariostage",
            name="third_place_playoff",
            field=models.BooleanField(default=False, help_text="Optional bronze match in a final Knockout Stage; otherwise two shared third places."),
        ),
    ]
