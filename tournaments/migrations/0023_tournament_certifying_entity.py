from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ("cert_ratings", "0001_initial"),
        ("tournaments", "0022_tournamentteam_vs_points_vsencounter_vslineup"),
    ]

    operations = [
        migrations.AddField(
            model_name="tournament",
            name="certifying_entity",
            field=models.ForeignKey(
                blank=True,
                help_text="Optional: Certifying Entity whose Elo ratings are updated when this tournament's matches complete.",
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name="tournaments",
                to="cert_ratings.certifyingentity",
            ),
        ),
    ]
