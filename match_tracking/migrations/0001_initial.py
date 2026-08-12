# Generated manually for the Match Tracking session lifecycle feature.

import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):

    initial = True

    dependencies = [
        ("practice", "0010_practicestatistics_total_petit_carreaux"),
        ("teams", "0010_team_is_tournament_temp"),
    ]

    operations = [
        migrations.CreateModel(
            name="MatchTrackingSession",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("match_type", models.CharField(choices=[("match", "Tournament match"), ("game", "Friendly game")], max_length=8)),
                ("match_pk", models.PositiveIntegerField(db_index=True)),
                ("status", models.CharField(choices=[("active", "Active"), ("ended", "Ended")], db_index=True, default="active", max_length=10)),
                ("started_at", models.DateTimeField(auto_now_add=True)),
                ("ended_at", models.DateTimeField(blank=True, null=True)),
                ("ended_reason", models.CharField(blank=True, max_length=32)),
            ],
            options={"ordering": ["-started_at"]},
        ),
        migrations.CreateModel(
            name="TrackingAuthorization",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("codename", models.CharField(max_length=50)),
                ("authorized_at", models.DateTimeField(auto_now_add=True)),
                ("is_active", models.BooleanField(db_index=True, default=True)),
                ("player", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="match_tracking_authorizations", to="teams.player")),
                ("tracking_session", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="authorizations", to="match_tracking.matchtrackingsession")),
            ],
        ),
        migrations.CreateModel(
            name="TrackingPracticeSession",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("practice_type", models.CharField(choices=[("shooting", "Shooting"), ("pointing", "Pointing")], max_length=20)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("player", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="match_tracking_practice_sessions", to="teams.player")),
                ("practice_session", models.OneToOneField(on_delete=django.db.models.deletion.CASCADE, related_name="match_tracking_link", to="practice.practicesession")),
                ("tracking_session", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="practice_sessions", to="match_tracking.matchtrackingsession")),
            ],
        ),
        migrations.AddIndex(
            model_name="matchtrackingsession",
            index=models.Index(fields=["match_type", "match_pk", "status"], name="match_track_match_t_579c20_idx"),
        ),
        migrations.AddConstraint(
            model_name="trackingauthorization",
            constraint=models.UniqueConstraint(fields=("tracking_session", "player"), name="unique_tracking_player_authorization"),
        ),
        migrations.AddConstraint(
            model_name="trackingpracticesession",
            constraint=models.UniqueConstraint(fields=("tracking_session", "player", "practice_type"), name="unique_tracking_practice_type"),
        ),
    ]
