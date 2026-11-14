from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    dependencies = [("cert_ratings", "0002_peta_algorithm")]

    operations = [
        migrations.CreateModel(
            name="PetaKeepAllChoice",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("enabled", models.BooleanField(default=False)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("event", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="keep_all_choices", to="cert_ratings.petaevent")),
                ("player", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, to="teams.player")),
            ],
        ),
        migrations.AddConstraint(
            model_name="petakeepallchoice",
            constraint=models.UniqueConstraint(fields=("event", "player"), name="peta_unique_keep_all_choice"),
        ),
    ]
