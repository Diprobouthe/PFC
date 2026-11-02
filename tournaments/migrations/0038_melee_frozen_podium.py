from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("tournaments", "0037_vs_sheet_attestation"),
    ]

    operations = [
        migrations.AddField(
            model_name="playertournamenthistory",
            name="melee_final_rank",
            field=models.PositiveIntegerField(
                blank=True, null=True,
                help_text="Official frozen individual Mêlée place at finalization.",
            ),
        ),
        migrations.AddField(
            model_name="playertournamenthistory",
            name="melee_final_rating",
            field=models.DecimalField(
                blank=True, null=True, decimal_places=2, max_digits=9,
                help_text="Tournament-only finish rating, frozen with placement.",
            ),
        ),
    ]
