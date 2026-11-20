#!/usr/bin/env python3
"""20 genuine Chromium sessions against the CURRENT PR Smart button.

Usage (isolated CI database only):
  python scripts/great_journey_smart_chromium.py seed
  python scripts/great_journey_smart_chromium.py browser
"""
import asyncio
import json
import os
import sys
from datetime import timedelta
from pathlib import Path
from statistics import median
from time import perf_counter
from urllib.parse import urljoin, urlsplit

ACTORS = Path("/tmp/great_journey_smart_actors.json")
ORIGIN = "http://127.0.0.1:8765"


def seed():
    if os.environ.get("JOURNEY_SMART_ISOLATED") != "1":
        raise SystemExit("Refusing to seed outside the isolated CI database")
    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "pfc_core.settings")
    import django
    django.setup()
    from django.conf import settings
    from importlib import import_module
    from django.urls import reverse
    from django.utils import timezone
    from teams.models import Player, Team
    from matches.models import Match, MatchPlayer
    from friendly_games.models import PlayerCodename
    from practice.models import PracticeSession
    from tournaments.models import (
        Tournament, Stage, Round, MeleePlayer, MeleeRoundAssignment,
    )

    now = timezone.now()
    tournament = Tournament.objects.create(
        name="CI CURRENT-HEAD Great Journey Smart synthetic",
        format="multi_stage", play_format="doublets", is_melee=True,
        melee_format="doublets", shuffle_players_after_round=True,
        start_date=now, end_date=now + timedelta(days=1),
    )
    stage = Stage.objects.create(
        tournament=tournament, stage_number=1, format="swiss",
        num_qualifiers=1, num_rounds_in_stage=5,
    )
    round_one = Round.objects.create(
        tournament=tournament, stage=stage, number=1, number_in_stage=1,
    )
    SessionStore = import_module(settings.SESSION_ENGINE).SessionStore
    actors = []
    for court in range(5):
        teams = [
            Team.objects.create(name=f"CI Browser court {court} side {side}",
                                is_tournament_temp=True)
            for side in range(2)
        ]
        match = Match.objects.create(
            tournament=tournament, stage=stage, round=round_one,
            team1=teams[0], team2=teams[1], status="active", start_time=None,
        )
        for pos in range(4):
            idx = court * 4 + pos
            home = Team.objects.create(name=f"CI browser home {idx}")
            player = Player.objects.create(name=f"CI browser player {idx}",
                                           team=home)
            codename = f"CBJ{idx:03d}"
            PlayerCodename.objects.create(player=player, codename=codename)
            MeleePlayer.objects.create(
                tournament=tournament, player=player, original_team=home)
            MeleeRoundAssignment.objects.create(
                tournament=tournament, round=round_one, player=player,
                team=teams[pos // 2], state=MeleeRoundAssignment.ASSIGNED,
            )
            MatchPlayer.objects.create(
                match=match, player=player, team=teams[pos // 2])
            if idx % 2 == 0:
                PracticeSession.objects.create(
                    player_codename=codename, practice_type="shooting")
            session = SessionStore()
            session["player_codename"] = codename
            session["session_active"] = True
            session.save()
            actors.append({
                "session": session.session_key,
                "codename": codename,
                "expected": reverse("match_detail", args=[match.id]),
            })
    ACTORS.write_text(json.dumps(actors))
    print(f"CURRENT_HEAD_CHROMIUM_SEED actors={len(actors)} courts=5 "
          f"with_lingering_practice=10", flush=True)


async def browser():
    from playwright.async_api import async_playwright

    actors = json.loads(ACTORS.read_text())
    assert len(actors) == 20
    ready = []
    failures = []
    measurements = []
    gate = asyncio.Event()
    contexts = []

    async with async_playwright() as p:
        chromium = await p.chromium.launch(
            headless=True, args=["--no-sandbox", "--disable-dev-shm-usage"])
        async def actor_task(actor):
            try:
                context = await chromium.new_context(service_workers="block")
                contexts.append(context)
                await context.add_cookies([{
                    "name": "sessionid", "value": actor["session"],
                    "domain": "127.0.0.1", "path": "/", "httpOnly": True,
                    "sameSite": "Lax",
                }])
                async def restrict(route):
                    if urlsplit(route.request.url).hostname not in (
                            "127.0.0.1", "localhost"):
                        await route.abort()
                    else:
                        await route.continue_()
                await context.route("**/*", restrict)
                page = await context.new_page()
                page.set_default_timeout(35000)
                await page.goto(ORIGIN + "/", wait_until="domcontentloaded",
                                timeout=45000)
                await page.locator("#pfc-smart-cta").wait_for()
                requests = []
                page.on("request", lambda req: requests.append(req.url)
                        if urlsplit(req.url).path == "/my-matches/" else None)
                ready.append(actor["codename"])
                await gate.wait()
                before = perf_counter()
                async with page.expect_response(
                    lambda res: urlsplit(res.url).path == "/my-matches/",
                    timeout=45000,
                ) as response_info:
                    await page.evaluate("""() => {
                      let button = document.querySelector('#pfc-smart-cta');
                      for (let i = 0; i < 5; ++i) button.click();
                    }""")
                response = await response_info.value
                elapsed = (perf_counter() - before) * 1000
                target = urlsplit(urljoin(ORIGIN, response.headers.get(
                    "location", ""))).path
                measurements.append(round(elapsed, 1))
                if response.status != 302 or target != actor["expected"]:
                    failures.append({
                        "codename": actor["codename"], "status": response.status,
                        "got": target, "expected": actor["expected"],
                    })
                await asyncio.sleep(.2)
                if len(requests) != 1:
                    failures.append({
                        "codename": actor["codename"],
                        "smart_requests_from_five_taps": len(requests),
                    })
            except Exception as exc:
                failures.append({"codename": actor["codename"],
                                 "error": str(exc)[:250]})

        tasks = [asyncio.create_task(actor_task(a)) for a in actors]
        for _ in range(600):
            if len(ready) + len(failures) == 20:
                break
            await asyncio.sleep(.1)
        gate.set()
        await asyncio.gather(*tasks)
        for ctx in contexts:
            await ctx.close()
        await chromium.close()
    values = sorted(measurements)
    p95 = values[int((len(values) - 1) * .95)] if values else None
    print("CURRENT_HEAD_CHROMIUM_20", json.dumps({
        "players": 20, "ready": len(ready), "completed": len(values),
        "attempted_taps": 100, "expected_smart_requests": 20,
        "median_ms": round(median(values), 1) if values else None,
        "p95_ms": p95, "errors": failures[:20],
    }), flush=True)
    assert not failures and len(values) == 20, "Current PR Smart Chromium gate failed"


if __name__ == "__main__":
    if len(sys.argv) != 2:
        raise SystemExit("Usage: seed|browser")
    if sys.argv[1] == "seed":
        seed()
    elif sys.argv[1] == "browser":
        asyncio.run(browser())
    else:
        raise SystemExit("Usage: seed|browser")
