# Generated for PFC Super Mêlée Snake Draft continuity on 2026-09-19

from django.db import migrations, models


def preserve_simple_creator_draft_algorithm(apps, schema_editor):
    """Backfill known Simple Creator Scenario choices for existing tournaments."""
    Tournament = apps.get_model("tournaments", "Tournament")
    SimpleTournament = apps.get_model("simple_creator", "SimpleTournament")

    algorithm_by_draft_type = {
        "snake": "snake_draft",
        "balance": "balanced",
        "random": "random",
    }
    for simple_tournament in SimpleTournament.objects.select_related("scenario").filter(
        tournament__is_melee=True,
    ):
        algorithm = algorithm_by_draft_type.get(simple_tournament.scenario.draft_type)
        if algorithm:
            Tournament.objects.filter(pk=simple_tournament.tournament_id).update(
                melee_team_algorithm=algorithm,
            )


class Migration(migrations.Migration):

    dependencies = [
        ("simple_creator", "0010_add_singles_format_and_max_singles_players"),
        ("tournaments", "0029_p4_melee_roster_history"),
    ]

    operations = [
        migrations.AddField(
            model_name="tournament",
            name="melee_team_algorithm",
            field=models.CharField(
                choices=[
                    ("random", "Random"),
                    ("balanced", "Balanced"),
                    ("snake_draft", "Snake Draft"),
                ],
                default="random",
                help_text=(
                    "Canonical Mêlée team-generation algorithm. Snake Draft is retained "
                    "for Super Mêlée doubles round transitions."
                ),
                max_length=20,
            ),
        ),
        migrations.RunPython(
            preserve_simple_creator_draft_algorithm,
            migrations.RunPython.noop,
        ),
    ]
