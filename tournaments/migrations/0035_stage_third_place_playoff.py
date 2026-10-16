from django.db import migrations, models

class Migration(migrations.Migration):
    dependencies = [("tournaments", "0034_round_lineup_lifecycle")]
    operations = [
        migrations.AddField(
            model_name="stage",
            name="third_place_playoff",
            field=models.BooleanField(default=False, help_text="Optional bronze Match after Knockout semifinals; off means shared third place."),
        ),
    ]
