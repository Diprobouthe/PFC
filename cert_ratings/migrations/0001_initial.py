from django.db import migrations, models
import django.db.models.deletion
import django.utils.timezone


class Migration(migrations.Migration):

    initial = True

    dependencies = [
        ("matches", "0001_initial"),
        ("teams", "0001_initial"),
    ]

    operations = [
        migrations.CreateModel(
            name="CertifyingEntity",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("name", models.CharField(max_length=100, unique=True)),
                ("is_active", models.BooleanField(default=True)),
                ("rating_system", models.CharField(
                    choices=[("classic_elo", "Classic Elo")],
                    default="classic_elo",
                    max_length=30,
                )),
                ("elo_starting_rating", models.IntegerField(
                    default=1000,
                    help_text="Starting Elo rating for new players (default 1000).",
                )),
                ("elo_k_factor", models.IntegerField(
                    default=20,
                    help_text="K-factor for Elo calculation (default 20).",
                )),
                ("elo_scale", models.IntegerField(
                    default=400,
                    help_text="Rating scale divisor for Elo calculation (default 400).",
                )),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
            ],
            options={
                "verbose_name": "Certifying Entity",
                "verbose_name_plural": "Certifying Entities",
                "ordering": ["name"],
            },
        ),
        migrations.CreateModel(
            name="PlayerCertRating",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("current_rating", models.FloatField(default=1000)),
                ("matches_played", models.PositiveIntegerField(default=0)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("entity", models.ForeignKey(
                    on_delete=django.db.models.deletion.CASCADE,
                    related_name="player_ratings",
                    to="cert_ratings.certifyingentity",
                )),
                ("player", models.ForeignKey(
                    on_delete=django.db.models.deletion.CASCADE,
                    related_name="cert_ratings",
                    to="teams.player",
                )),
            ],
            options={
                "verbose_name": "Player Certifying Entity Rating",
                "verbose_name_plural": "Player Certifying Entity Ratings",
                "ordering": ["-current_rating"],
                "unique_together": {("player", "entity")},
            },
        ),
        migrations.CreateModel(
            name="CertRatingHistory",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("rating_before", models.FloatField()),
                ("rating_after", models.FloatField()),
                ("rating_change", models.FloatField()),
                ("timestamp", models.DateTimeField(default=django.utils.timezone.now)),
                ("entity", models.ForeignKey(
                    on_delete=django.db.models.deletion.CASCADE,
                    related_name="rating_history",
                    to="cert_ratings.certifyingentity",
                )),
                ("match", models.ForeignKey(
                    on_delete=django.db.models.deletion.CASCADE,
                    related_name="cert_rating_history",
                    to="matches.match",
                )),
                ("player", models.ForeignKey(
                    on_delete=django.db.models.deletion.CASCADE,
                    related_name="cert_rating_history",
                    to="teams.player",
                )),
            ],
            options={
                "verbose_name": "Cert Rating History Entry",
                "verbose_name_plural": "Cert Rating History Entries",
                "ordering": ["-timestamp"],
                "unique_together": {("player", "entity", "match")},
            },
        ),
    ]
