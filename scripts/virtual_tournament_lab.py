#!/usr/bin/env python3
"""PFC Virtual Tournament Laboratory, phase 1: real HTTP + WebSocket clients.

Runs ONLY against an isolated CI PostgreSQL database on loopback. Never points
at production. No test cookies or codenames are written to the report artifact.

Stage 1 measures the transport/auth/Smart discovery path with 5 then 30
independent browser sessions, not complete browser UI or tournament gameplay.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import statistics
import time
import urllib.request
from datetime import timedelta
from pathlib import Path
from urllib.parse import urlsplit


def setup_isolated_django():
    if os.environ.get("PFC_VTL_ISOLATED") != "1":
        raise SystemExit("Refusing to run: PFC_VTL_ISOLATED=1 is required")
    db_url = urlsplit(os.environ.get("DATABASE_URL", ""))
    if db_url.hostname not in ("127.0.0.1", "localhost") or db_url.path != "/pfc_vtl_test":
        raise SystemExit("Refusing to run: expected localhost/pfc_vtl_test database")
    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "pfc_core.settings")
    import django
    django.setup()


def seed(players: int, output: str):
    from django.contrib.sessions.backends.db import SessionStore
    from django.utils import timezone
    from friendly_games.models import PlayerCodename
    from matches.models import Match, MatchPlayer
    from teams.models import Player, Team
    from tournaments.models import (
        MeleePlayer, MeleeRoundAssignment, Round, Stage, Tournament, TournamentTeam,
    )

    if not 4 <= players <= 60:
        raise SystemExit("players must be between 4 and 60")
    now = timezone.now()
    tournament = Tournament.objects.create(
        name="VTL isolated Super Melee",
        format="multi_stage",
        play_format="doublets",
        is_melee=True,
        melee_format="doublets",
        shuffle_players_after_round=True,
        start_date=now,
        end_date=now + timedelta(hours=3),
    )
    stage = Stage.objects.create(
        tournament=tournament,
        stage_number=1,
        format="swiss",
        num_qualifiers=1,
        num_rounds_in_stage=3,
    )
    round_obj = Round.objects.create(
        tournament=tournament, stage=stage, number=1, number_in_stage=1,
        lineup_deadline_at=now + timedelta(minutes=20),
    )
    actors = []
    match_count = players // 4
    for match_index in range(match_count):
        sides = []
        for side_index in range(2):
            side = Team.objects.create(
                name=f"VTL temporary side {match_index}-{side_index}",
                is_tournament_temp=True,
            )
            TournamentTeam.objects.create(tournament=tournament, team=side)
            sides.append(side)
        match = Match.objects.create(
            tournament=tournament, stage=stage, round=round_obj,
            team1=sides[0], team2=sides[1], status="pending",
        )
        for side_index, side in enumerate(sides):
            for slot in range(2):
                index = match_index * 4 + side_index * 2 + slot
                home_team = Team.objects.create(name=f"VTL home {index}")
                player = Player.objects.create(name=f"Virtual player {index:02d}", team=home_team)
                codename = f"VT{index:04d}"
                PlayerCodename.objects.create(player=player, codename=codename)
                MeleePlayer.objects.create(
                    tournament=tournament, player=player, original_team=home_team,
                )
                MeleeRoundAssignment.objects.create(
                    tournament=tournament, round=round_obj, player=player,
                    team=side, state=MeleeRoundAssignment.ASSIGNED,
                )
                MatchPlayer.objects.create(match=match, player=player, team=side)
                session = SessionStore()
                session["player_codename"] = codename
                session["session_active"] = True
                session["codename_login_time"] = now.isoformat()
                session.save()
                actors.append({
                    "player_id": player.id,
                    "match_id": match.id,
                    "session": session.session_key,
                    "has_match": True,
                })
    for index in range(match_count * 4, players):
        home_team = Team.objects.create(name=f"VTL bye home {index}")
        player = Player.objects.create(name=f"Virtual player {index:02d}", team=home_team)
        codename = f"VT{index:04d}"
        PlayerCodename.objects.create(player=player, codename=codename)
        MeleePlayer.objects.create(
            tournament=tournament, player=player, original_team=home_team,
        )
        session = SessionStore()
        session["player_codename"] = codename
        session["session_active"] = True
        session["codename_login_time"] = now.isoformat()
        session.save()
        actors.append({
            "player_id": player.id, "match_id": None,
            "session": session.session_key, "has_match": False,
        })
    Path(output).write_text(json.dumps({
        "tournament_id": tournament.id,
        "round_id": round_obj.id,
        "matches": match_count,
        "actors": actors,
    }), encoding="utf-8")
    os.chmod(output, 0o600)
    print(f"Seeded isolated tournament: {players} players; {match_count} doublettes; {players-4*match_count} byes")


def quantile_ms(values, fraction):
    if not values:
        return None
    ordered = sorted(values)
    return round(ordered[min(len(ordered) - 1, int((len(ordered) - 1) * fraction))], 1)


def smart_get(base: str, actor: dict):
    started = time.perf_counter()
    request = urllib.request.Request(
        base + "/my-matches/next-url/",
        headers={"Cookie": "sessionid=" + actor["session"], "User-Agent": "PFC-VTL/1.0"},
    )
    with urllib.request.urlopen(request, timeout=18) as response:
        status = response.status
        payload = json.loads(response.read())
    latency = (time.perf_counter() - started) * 1000
    ok = bool(status == 200 and payload.get("authenticated") is True
              and bool(payload.get("next_url")) == bool(actor["has_match"]))
    return {"ok": ok, "latency_ms": round(latency, 1),
            "http": status, "has_next_url": bool(payload.get("next_url"))}


async def run(args):
    import websockets
    from channels.layers import get_channel_layer

    payload = json.loads(Path(args.input).read_text(encoding="utf-8"))
    actors = payload["actors"][:args.players]
    base = args.base.rstrip("/")
    if urlsplit(base).hostname not in ("127.0.0.1", "localhost"):
        raise SystemExit("Only loopback Daphne is allowed")
    ws_base = "ws://" + urlsplit(base).netloc
    layer = get_channel_layer()
    sockets = []
    connect_ms = []
    errors = []
    connects = 0
    reconnects = 0
    notifications_received = 0
    match_state_received = 0
    http_results = []

    async def open_socket(actor, endpoint):
        nonlocal connects
        started = time.perf_counter()
        socket = await websockets.connect(
            ws_base + endpoint,
            extra_headers={"Cookie": "sessionid=" + actor["session"]},
            origin=base,
            open_timeout=12,
            close_timeout=4,
            ping_interval=None,
        )
        connects += 1
        connect_ms.append((time.perf_counter() - started) * 1000)
        return socket

    try:
        # Open all clients as concurrently as possible. Each session is unique.
        async def connect_actor(actor):
            invite = None
            match = None
            if not args.without_invites:
                invite = await open_socket(actor, f"/ws/invites/{actor['player_id']}/")
            if actor["has_match"]:
                match = await open_socket(actor, f"/ws/match/{actor['match_id']}/")
            return {"actor": actor, "invite": invite, "match": match}

        responses = await asyncio.gather(*(connect_actor(a) for a in actors), return_exceptions=True)
        for i, response in enumerate(responses):
            if isinstance(response, BaseException):
                errors.append(f"connect player_index={i}: {type(response).__name__}: {response}")
            else:
                sockets.append(response)

        # Real HTTP calls against real Daphne; not Django test Client or mocks.
        async def probe(actor):
            try:
                return await asyncio.to_thread(smart_get, base, actor)
            except Exception as exc:
                return {"ok": False, "error": f"{type(exc).__name__}: {exc}"}

        http_results = await asyncio.gather(*(probe(a) for a in actors))
        for index, result in enumerate(http_results):
            if not result["ok"]:
                errors.append(f"Smart player_index={index}: {result}")

        # Deliver actual channel-layer events across Redis to live Daphne.
        for entry in sockets:
            if entry["invite"] is not None:
                actor = entry["actor"]
                await layer.group_send(
                    f"player_{actor['player_id']}",
                    {"type": "match.action_required", "event_kind": "new_match",
                     "object_type": "match", "object_id": actor["match_id"] or 0},
                )
        async def receive_invite(entry):
            if entry["invite"] is None:
                return False
            message = json.loads(await asyncio.wait_for(entry["invite"].recv(), timeout=12))
            return message.get("type") == "match.action_required"

        invite_responses = await asyncio.gather(
            *(receive_invite(e) for e in sockets if e["invite"] is not None),
            return_exceptions=True,
        )
        notifications_received = sum(x is True for x in invite_responses)
        for result in invite_responses:
            if result is not True:
                errors.append("Missing invite notification: " + str(result)[:100])

        # One event per match reaches all subscribed player match pages.
        for match_id in {e["actor"]["match_id"] for e in sockets if e["match"] is not None}:
            await layer.group_send(
                f"match_{match_id}",
                {"type": "match.state_changed", "match_type": "match",
                 "match_id": match_id, "new_status": "pending", "next_url": None},
            )
        async def receive_match(entry):
            if entry["match"] is None:
                return False
            message = json.loads(await asyncio.wait_for(entry["match"].recv(), timeout=12))
            return message.get("type") == "match.state_changed"

        match_responses = await asyncio.gather(
            *(receive_match(e) for e in sockets if e["match"] is not None),
            return_exceptions=True,
        )
        match_state_received = sum(x is True for x in match_responses)
        for result in match_responses:
            if result is not True:
                errors.append("Missing match state notification: " + str(result)[:100])

        # Force clean closes and real reconnects; test both transports.
        for _ in range(args.reconnects):
            async def cycle(entry):
                nonlocal reconnects
                for key in ("invite", "match"):
                    if entry[key] is not None:
                        await entry[key].close()
                        entry[key] = await open_socket(
                            entry["actor"],
                            (f"/ws/invites/{entry['actor']['player_id']}/"
                             if key == "invite" else
                             f"/ws/match/{entry['actor']['match_id']}/"),
                        )
                        reconnects += 1
            cycle_results = await asyncio.gather(
                *(cycle(e) for e in sockets), return_exceptions=True,
            )
            for result in cycle_results:
                if isinstance(result, BaseException):
                    errors.append("reconnect: " + str(result)[:200])
    finally:
        await asyncio.gather(
            *(socket.close() for e in sockets for socket in
              (e.get("invite"), e.get("match")) if socket is not None),
            return_exceptions=True,
        )

    expected_invites = 0 if args.without_invites else len(sockets)
    expected_matches = sum(bool(e["actor"]["has_match"]) for e in sockets)
    if len(sockets) != len(actors):
        errors.append(f"Expected {len(actors)} connected player sessions, got {len(sockets)}")
    if notifications_received != expected_invites:
        errors.append(f"Invites delivery: {notifications_received}/{expected_invites}")
    if match_state_received != expected_matches:
        errors.append(f"Match delivery: {match_state_received}/{expected_matches}")
    report = {
        "phase": "transport-and-smart-smoke-not-full-tournament",
        "player_sessions": len(actors),
        "matches_in_fixture": payload["matches"],
        "players_with_match": sum(a["has_match"] for a in actors),
        "invites_enabled": not args.without_invites,
        "http_smart_attempted": len(http_results),
        "http_smart_ok": sum(bool(r["ok"]) for r in http_results),
        "http_smart_p50_ms": quantile_ms([r["latency_ms"] for r in http_results if r["ok"]], 0.5),
        "http_smart_p95_ms": quantile_ms([r["latency_ms"] for r in http_results if r["ok"]], 0.95),
        "websocket_handshakes": connects,
        "websocket_reconnections": reconnects,
        "ws_handshake_p95_ms": quantile_ms(connect_ms, 0.95),
        "invites_notifications_received": notifications_received,
        "match_notifications_received": match_state_received,
        "errors": errors[:30],
        "passed": not errors,
    }
    Path(args.output).write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, indent=2))
    if errors:
        raise SystemExit(1)


def main():
    parser = argparse.ArgumentParser()
    modes = parser.add_subparsers(dest="command", required=True)
    seed_parser = modes.add_parser("seed")
    seed_parser.add_argument("--players", type=int, default=30)
    seed_parser.add_argument("--output", default="/tmp/pfc_vtl_sessions.json")
    run_parser = modes.add_parser("run")
    run_parser.add_argument("--input", default="/tmp/pfc_vtl_sessions.json")
    run_parser.add_argument("--output", default="/tmp/pfc_vtl_report.json")
    run_parser.add_argument("--players", type=int, default=5)
    run_parser.add_argument("--base", default="http://127.0.0.1:8765")
    run_parser.add_argument("--reconnects", type=int, default=1)
    run_parser.add_argument("--without-invites", action="store_true")
    args = parser.parse_args()
    setup_isolated_django()
    if args.command == "seed":
        seed(args.players, args.output)
    else:
        asyncio.run(run(args))


if __name__ == "__main__":
    main()
