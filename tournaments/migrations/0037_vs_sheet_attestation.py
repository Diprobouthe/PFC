from django.db import migrations, models
import django.db.models.deletion
import django.utils.timezone


class Migration(migrations.Migration):
    dependencies = [
        ("tournaments", "0036_tournament_report_notes"),
        ("teams", "0001_initial"),
    ]

    operations = [
        migrations.CreateModel(
            name="VSSheetAttestation",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("role", models.CharField(choices=[
                    ("team1", "Team 1 representative"),
                    ("team2", "Team 2 representative"),
                    ("referee", "Voluntary referee (not certified)"),
                ], max_length=10)),
                ("player_name", models.CharField(max_length=100)),
                ("team_name", models.CharField(blank=True, max_length=100)),
                ("sheet_digest", models.CharField(max_length=64)),
                ("attested_at", models.DateTimeField(default=django.utils.timezone.now)),
                ("encounter", models.ForeignKey(
                    on_delete=django.db.models.deletion.CASCADE,
                    related_name="sheet_attestations", to="tournaments.vsencounter",
                )),
                ("player", models.ForeignKey(
                    blank=True, null=True,
                    on_delete=django.db.models.deletion.SET_NULL,
                    related_name="vs_sheet_attestations", to="teams.player",
                )),
            ],
        ),
        migrations.AddConstraint(
            model_name="vssheetattestation",
            constraint=models.UniqueConstraint(
                fields=("encounter", "role"),
                name="unique_vs_sheet_attestation_role",
            ),
        ),
    ]
