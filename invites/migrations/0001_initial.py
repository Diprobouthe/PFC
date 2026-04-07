import uuid
import django.db.models.deletion
import django.utils.timezone
from django.db import migrations, models


class Migration(migrations.Migration):

    initial = True

    dependencies = [
        ("courts", "0001_initial"),
        ("teams", "0001_initial"),
        ("tournaments", "0001_initial"),
    ]

    operations = [
        migrations.CreateModel(
            name="TeamBuildSession",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("token", models.UUIDField(default=uuid.uuid4, editable=False, unique=True)),
                ("build_type", models.CharField(
                    choices=[("normal", "Normal Team"), ("tournament", "Tournament Team (temporary)")],
                    default="normal",
                    max_length=20,
                )),
                ("status", models.CharField(
                    choices=[("open", "Open"), ("complete", "Complete — team created"), ("cancelled", "Cancelled")],
                    default="open",
                    max_length=20,
                )),
                ("target_size", models.PositiveSmallIntegerField(default=3)),
                ("proposed_team_name", models.CharField(blank=True, default="", max_length=100)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("completed_at", models.DateTimeField(blank=True, null=True)),
                ("creator", models.ForeignKey(
                    on_delete=django.db.models.deletion.CASCADE,
                    related_name="created_build_sessions",
                    to="teams.player",
                )),
                ("accepted_players", models.ManyToManyField(
                    blank=True,
                    related_name="accepted_build_sessions",
                    to="teams.player",
                )),
                ("tournament", models.ForeignKey(
                    blank=True,
                    null=True,
                    on_delete=django.db.models.deletion.SET_NULL,
                    related_name="team_build_sessions",
                    to="tournaments.tournament",
                )),
                ("created_team", models.OneToOneField(
                    blank=True,
                    null=True,
                    on_delete=django.db.models.deletion.SET_NULL,
                    related_name="build_session",
                    to="teams.team",
                )),
            ],
            options={"ordering": ["-created_at"], "verbose_name": "Team Build Session", "verbose_name_plural": "Team Build Sessions"},
        ),
        migrations.CreateModel(
            name="Invitation",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("token", models.UUIDField(default=uuid.uuid4, editable=False, unique=True)),
                ("invite_type", models.CharField(
                    choices=[("play", "Play Invite"), ("team_build", "Team Build Invite")],
                    default="play",
                    max_length=20,
                )),
                ("status", models.CharField(
                    choices=[("pending", "Pending"), ("accepted", "Accepted"), ("rejected", "Rejected"), ("expired", "Expired")],
                    default="pending",
                    max_length=20,
                )),
                ("message", models.CharField(blank=True, default="", max_length=200)),
                ("play_time", models.DateTimeField(blank=True, null=True)),
                ("play_notes", models.CharField(blank=True, default="", max_length=200)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("responded_at", models.DateTimeField(blank=True, null=True)),
                ("expires_at", models.DateTimeField(blank=True, null=True)),
                ("sender", models.ForeignKey(
                    on_delete=django.db.models.deletion.CASCADE,
                    related_name="sent_invitations",
                    to="teams.player",
                )),
                ("recipient", models.ForeignKey(
                    on_delete=django.db.models.deletion.CASCADE,
                    related_name="received_invitations",
                    to="teams.player",
                )),
                ("play_court", models.ForeignKey(
                    blank=True,
                    null=True,
                    on_delete=django.db.models.deletion.SET_NULL,
                    related_name="play_invitations",
                    to="courts.courtcomplex",
                )),
                ("session", models.ForeignKey(
                    blank=True,
                    null=True,
                    on_delete=django.db.models.deletion.CASCADE,
                    related_name="invitations",
                    to="invites.teambuildsession",
                )),
            ],
            options={"ordering": ["-created_at"], "verbose_name": "Invitation", "verbose_name_plural": "Invitations"},
        ),
    ]
