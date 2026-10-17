"""Final VS sheet attestation, independent of individual Match validation.

All authority comes from the HMAC-verified existing PFC QR card resolved on
the server. Player.team determines A/B. A neutral PFC player may acknowledge
as the optional, unlicensed referee when the organizer enabled that role.
"""
from hashlib import sha256
import json

from django.utils import timezone

from matches.models import Match
from tournaments.models import VSEncounter, VSSheetAttestation
from tournaments.pdf_reports import vs_sheet_ready


def ready_for_sheet(encounter):
    """V1 issues one final encounter sheet for the two VS teams."""
    return (
        VSEncounter.objects.filter(tournament_id=encounter.tournament_id).count() == 1
        and vs_sheet_ready(encounter.tournament)
    )


def current_sheet_digest(encounter):
    """Hash exactly the match outcomes, lineups and printable metadata."""
    games = (
        Match.objects.filter(vs_encounter=encounter)
        .prefetch_related("vs_lineups__players", "match_players__player")
        .order_by("pk")
    )
    content = {
        "tournament": [encounter.tournament_id, encounter.tournament.name,
                       encounter.tournament.report_notes],
        "encounter": [encounter.pk, encounter.team1_id, encounter.team1.name,
                      encounter.team2_id, encounter.team2.name,
                      encounter.sheet_referee_required],
        "games": [],
    }
    for game in games:
        content["games"].append({
            "id": game.pk,
            "team_ids": [game.team1_id, game.team2_id],
            "status": game.status,
            "format": game.match_type,
            "score": [game.team1_score, game.team2_score],
            "winner": game.winner_id,
            "vs_points": game.vs_points_value,
            "lineups": sorted([
                [row.team_id, sorted(
                    [[p.pk, p.name] for p in row.players.all()],
                    key=lambda item: item[0],
                )]
                for row in game.vs_lineups.all()
            ], key=lambda item: item[0]),
            "historic_roster": sorted([
                [r.team_id, r.player_id, r.player.name]
                for r in game.match_players.all()
            ]),
        })
    payload = json.dumps(content, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    return sha256(payload.encode("utf-8")).hexdigest()


def required_sheet_roles(encounter):
    roles = [VSSheetAttestation.ROLE_TEAM1, VSSheetAttestation.ROLE_TEAM2]
    if encounter.sheet_referee_required:
        roles.append(VSSheetAttestation.ROLE_REFEREE)
    return roles


def sheet_status(encounter):
    digest = current_sheet_digest(encounter) if ready_for_sheet(encounter) else None
    records = {}
    if digest:
        records = {
            attestation.role: attestation
            for attestation in encounter.sheet_attestations.all()
            if attestation.sheet_digest == digest
        }
    required = required_sheet_roles(encounter)
    complete = bool(digest and all(role in records for role in required))
    locked = bool(
        complete and encounter.sheet_pdf is not None
        and encounter.sheet_issued_at is not None
        and encounter.sheet_digest == digest
    )
    return {"ready": bool(digest), "digest": digest, "required": required,
            "records": records, "complete": complete, "locked": locked}


def qr_role(encounter, player):
    """Role is computed at write time; never trust a browser role or team ID."""
    if player.team_id == encounter.team1_id:
        return VSSheetAttestation.ROLE_TEAM1
    if player.team_id == encounter.team2_id:
        return VSSheetAttestation.ROLE_TEAM2
    if encounter.sheet_referee_required:
        return VSSheetAttestation.ROLE_REFEREE
    return None


def attest_and_maybe_freeze(encounter, player):
    """Call while holding a select_for_update lock on the encounter row.

    Returns role and whether this operation issued the immutable PDF.
    Duplicate cards, stale approvals and unauthorized teams fail closed.
    """
    status = sheet_status(encounter)
    if not status["ready"]:
        raise ValueError("Δεν έχουν ολοκληρωθεί και επικυρωθεί όλα τα παιχνίδια VS.")
    if encounter.sheet_pdf is not None:
        raise ValueError("Το φύλλο αγώνα έχει ήδη εκδοθεί και κλειδώσει.")
    role = qr_role(encounter, player)
    if not role:
        raise ValueError("Η κάρτα δεν ανήκει σε καμία από τις δύο ομάδες.")
    # If any match/lineup/notes changed before issue, require fresh approvals.
    encounter.sheet_attestations.exclude(sheet_digest=status["digest"]).delete()
    if encounter.sheet_attestations.filter(role=role).exists():
        raise ValueError("Η συγκεκριμένη πλευρά έχει ήδη επικυρώσει το φύλλο.")

    VSSheetAttestation.objects.create(
        encounter=encounter, role=role, player=player,
        player_name=player.name,
        team_name=player.team.name if player.team_id else "",
        sheet_digest=status["digest"],
        attested_at=timezone.now(),
    )
    required = required_sheet_roles(encounter)
    signed = set(encounter.sheet_attestations.values_list("role", flat=True))
    if not set(required).issubset(signed):
        return role, False

    # Frozen PDF is generated only once, from the accepted DB state, inside
    # the same transaction. Store bytes durably in Postgres.
    from tournaments.pdf_reports import render_vs_tournament_report
    report = render_vs_tournament_report(encounter.tournament)
    encounter.sheet_pdf = report.content
    encounter.sheet_digest = status["digest"]
    encounter.sheet_issued_at = timezone.now()
    encounter.save(update_fields=[
        "sheet_pdf", "sheet_digest", "sheet_issued_at", "updated_at",
    ])
    return role, True
