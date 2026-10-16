from django.db import migrations, models

class Migration(migrations.Migration):
    dependencies = [("leaderboards", "0004_tournament_lifecycle_guards")]
    operations = [
        migrations.AddField(
            model_name="leaderboardentry",
            name="official_place",
            field=models.PositiveIntegerField(blank=True, null=True, help_text="Official rank; two semifinal losers can share third place."),
        ),
    ]
