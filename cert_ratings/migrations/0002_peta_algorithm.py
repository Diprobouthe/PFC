"""PETA Certified Entity models; safe on an isolated test branch."""
from decimal import Decimal
from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    dependencies = [
        ("cert_ratings", "0001_initial"),
        ("tournaments", "0001_initial"),
    ]

    operations = [
        migrations.AlterField(
            model_name="certifyingentity", name="rating_system",
            field=models.CharField(
                max_length=30, default="classic_elo",
                choices=[("classic_elo", "Classic Elo"), ("peta_algorithm", "PETA Algorithm")],
            ),
        ),
        migrations.CreateModel(
            name="PetaSeries",
            fields=[
                ("id", models.BigAutoField(primary_key=True, serialize=False)),
                ("name", models.CharField(max_length=120)),
                ("rules_commitment", models.CharField(max_length=64, blank=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("entity", models.OneToOneField(
                    to="cert_ratings.certifyingentity",
                    on_delete=django.db.models.deletion.PROTECT,
                    related_name="peta_series")),
            ],
        ),
        migrations.CreateModel(
            name="PetaEvent",
            fields=[
                ("id", models.BigAutoField(primary_key=True, serialize=False)),
                ("ordinal", models.PositiveSmallIntegerField(
                    validators=[MinValueValidator(1), MaxValueValidator(8)])),
                ("include_podium", models.BooleanField(default=False)),
                ("require_task", models.BooleanField(default=False)),
                ("settled_at", models.DateTimeField(null=True, blank=True)),
                ("settlement_audit", models.JSONField(default=dict, blank=True)),
                ("series", models.ForeignKey(
                    to="cert_ratings.petaseries", related_name="events",
                    on_delete=django.db.models.deletion.PROTECT)),
                ("tournament", models.OneToOneField(
                    to="tournaments.tournament", related_name="peta_event",
                    on_delete=django.db.models.deletion.PROTECT)),
            ],
            options={"ordering": ["series_id", "ordinal"]},
        ),
        migrations.CreateModel(
            name="PetaCompetitor",
            fields=[
                ("id", models.BigAutoField(primary_key=True, serialize=False)),
                ("travel_points", models.DecimalField(
                    max_digits=18, decimal_places=4, default=Decimal("0.0000"))),
                ("last_end_rating", models.FloatField(null=True, blank=True)),
                ("exception_used", models.BooleanField(default=False)),
                ("dividend_suspended", models.BooleanField(
                    default=False, help_text="Confirmed violation only; a rating drop alone does not prove intent.")),
                ("player", models.ForeignKey(
                    to="teams.player", on_delete=django.db.models.deletion.PROTECT)),
                ("series", models.ForeignKey(
                    to="cert_ratings.petaseries", related_name="competitors",
                    on_delete=django.db.models.deletion.PROTECT)),
            ],
        ),
        migrations.CreateModel(
            name="PetaEventEntry",
            fields=[
                ("id", models.BigAutoField(primary_key=True, serialize=False)),
                ("entry_rating", models.FloatField()),
                ("end_rating", models.FloatField(null=True, blank=True)),
                ("use_exception", models.BooleanField(default=False)),
                ("task_passed", models.BooleanField(null=True, blank=True)),
                ("eligible_for_dividend", models.BooleanField(null=True, blank=True)),
                ("personal_earnings", models.DecimalField(
                    max_digits=18, decimal_places=4, default=Decimal("0.0000"))),
                ("dividend", models.DecimalField(
                    max_digits=18, decimal_places=4, default=Decimal("0.0000"))),
                ("event", models.ForeignKey(
                    to="cert_ratings.petaevent", related_name="entries",
                    on_delete=django.db.models.deletion.PROTECT)),
                ("player", models.ForeignKey(
                    to="teams.player", on_delete=django.db.models.deletion.PROTECT)),
            ],
        ),
        migrations.AddConstraint(
            model_name="petaevent",
            constraint=models.UniqueConstraint(fields=["series", "ordinal"], name="peta_unique_series_ordinal"),
        ),
        migrations.AddConstraint(
            model_name="petacompetitor",
            constraint=models.UniqueConstraint(fields=["series", "player"], name="peta_unique_competitor"),
        ),
        migrations.AddConstraint(
            model_name="petaevententry",
            constraint=models.UniqueConstraint(fields=["event", "player"], name="peta_unique_event_entry"),
        ),
    ]
