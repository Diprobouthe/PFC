from django.db import migrations, models

class Migration(migrations.Migration):
    dependencies = [("matches", "0017_tournament_lifecycle_guards")]
    operations = [
        migrations.AddField(
            model_name="match",
            name="placement_role",
            field=models.CharField(max_length=24, default="normal", choices=[("normal","Regular Match"),("championship_final","Championship Final"),("third_place_playoff","Third-place Playoff")], help_text="Finals purpose; separate from doubles/triples Match format."),
        ),
    ]
