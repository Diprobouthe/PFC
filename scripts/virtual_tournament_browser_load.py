#!/usr/bin/env python3
"""PFC browser-driven workload: real Chromium clicks with 30 isolated sessions.

ONLY disposable Actions PostgreSQL pfc_vtl_test and loopback Daphne.
This is a targeted, authenticated Super Melee UI workload, NOT every admin
button, complete multiround engine, or an exact Android simulation.
"""
from __future__ import annotations

import argparse
import asyncio
import collections
import json
import os
import time
from datetime import timedelta
from pathlib import Path
from urllib.parse import urlsplit

from virtual_tournament_lab import setup_isolated_django


def prepare(source, destination, courts=6):
    from courts.models import Court, CourtComplex
    from django.utils import timezone
    from matches.models import Match, LiveScoreboard
    from tournaments.lineup_lifecycle import finalize_round_lineups
    from tournaments.models import Round, Tournament

    original=json.loads(Path(source).read_text())
    if len(original["actors"])!=30 or original["matches"]!=7:
        raise AssertionError("Expected 30 distinct sessions and seven Matches")
    tournament=Tournament.objects.get(pk=original["tournament_id"])
    round_obj=Round.objects.get(pk=original["round_id"])
    complex_obj=CourtComplex.objects.create(
        name="PFC laboratory 6 Courts",description="Disposable Playwright study"
    )
    for i in range(courts):
        court=Court.objects.create(number=92000+i,is_available=True)
        tournament.courts.add(court)
        complex_obj.courts.add(court)

    Round.objects.filter(pk=round_obj.id).update(
        lineup_deadline_at=timezone.now()-timedelta(seconds=2)
    )
    outcome=finalize_round_lineups(round_obj.id)
    if not outcome.frozen:
        raise AssertionError(f"Round failed to freeze: {outcome}")
    # A five-minute-old start time stands in for waiting through the normal
    # pre-game countdown. It does NOT bypass Match state or score permissions.
    Match.objects.filter(round_id=round_obj.id,status="active").update(
        start_time=timezone.now()-timedelta(minutes=5)
    )
    details={}
    for m in Match.objects.filter(round=round_obj).order_by("pk"):
        try:
            scoreboard_id=m.live_scoreboard.id
        except LiveScoreboard.DoesNotExist:
            scoreboard_id=None
        details[m.id]={
            "status":m.status,"court_id":m.court_id,
            "scoreboard_id":scoreboard_id,
            "team1_id":m.team1_id,"team2_id":m.team2_id,
        }
    for a in original["actors"]:
        if a["match_id"] is not None:
            a.update(details[a["match_id"]])
    active=sum(x["status"]=="active" for x in details.values())
    waiting=sum(x["status"]=="pending_verification" for x in details.values())
    if active!=courts or waiting!=7-courts:
        raise AssertionError(f"Expected {courts} active, {7-courts} waiting; got {active}, {waiting}")
    if any(x["scoreboard_id"] is None for x in details.values()):
        raise AssertionError("Missing real tournament LiveScoreboard")
    Path(destination).write_text(json.dumps(original),encoding="utf-8")
    os.chmod(destination,0o600)
    print(f"Browser fixture ready: {len(original['actors'])} sessions, 7 matches, {active} active, {waiting} waiting, {courts} courts")


def percentile_ms(values,ratio):
    if not values:return None
    a=sorted(values)
    return round(a[min(len(a)-1,int((len(a)-1)*ratio))],1)


async def run_browser(args):
    from playwright.async_api import async_playwright

    origin=args.base.rstrip("/")
    if urlsplit(origin).hostname not in ("localhost","127.0.0.1"):
        raise SystemExit("Browser test only permits a localhost Daphne origin")
    original=json.loads(Path(args.input).read_text())
    actors=original["actors"]
    counters=collections.Counter()
    phases={}
    errors=[]
    contexts=[]
    pages={}
    latencies=collections.defaultdict(list)
    http_errors=[]
    open_sockets=collections.Counter()
    started=time.monotonic()

    async def route_handler(route):
        # Prevent real production/external contacts and keep the benchmark
        # limited to the local server. External fonts/CDNs are nonessential
        # to the tested page controls; their absence is a lab limitation.
        target=urlsplit(route.request.url)
        if target.hostname not in ("127.0.0.1","localhost"):
            return await route.abort()
        return await route.continue_()

    def log_http(resp):
        if resp.status>=400 and "/static/" not in resp.url and "/favicon" not in resp.url:
            http_errors.append({"status":resp.status,"path":urlsplit(resp.url).path})

    def ws_created(ws):
        path=urlsplit(ws.url).path
        counters["ws_open_"+(path.split("/")[2] if path.startswith("/ws/") else "unknown")]+=1
        open_sockets[path]+=1
        def closed(*_):
            counters["ws_close"]+=1
            open_sockets[path]-=1
        ws.on("close", closed)

    async def make_actor(actor):
        context=await browser.new_context(
            viewport={"width":390,"height":844},
            is_mobile=True,has_touch=True,
            service_workers="block",
            ignore_https_errors=False,
        )
        await context.add_cookies([{
            "name":"sessionid","value":actor["session"],
            "domain":"127.0.0.1","path":"/",
            "httpOnly":True,"sameSite":"Lax",
        }])
        await context.route("**/*",route_handler)
        contexts.append(context)
        page=await context.new_page()
        page.set_default_timeout(16000)
        page.on("websocket",ws_created)
        page.on("response",log_http)
        start=time.monotonic()
        await page.goto(origin+"/",wait_until="domcontentloaded",timeout=30000)
        latencies["home"].append((time.monotonic()-start)*1000)
        counters["home"]+=1
        start=time.monotonic()
        await page.locator("a.pfc-cta-btn").click(timeout=18000)
        await page.wait_for_load_state("domcontentloaded",timeout=30000)
        latencies["smart"].append((time.monotonic()-start)*1000)
        counters["smart"]+=1
        path=urlsplit(page.url).path
        if actor["has_match"]:
            if actor["status"]=="active":
                expected=f"/matches/scoreboard/{actor['scoreboard_id']}/"
                if path!=expected:
                    raise AssertionError(f"Smart destination {path} != {expected}")
                await page.locator("#team1-score").wait_for(timeout=15000)
            elif path.startswith("/matches/"):
                counters["waiting_smart"]+=1
            else:
                raise AssertionError(f"Pending court actor routed unexpectedly: {path}")
        elif path!="/my-matches/":
            raise AssertionError(f"BYE actor routed unexpectedly: {path}")
        pages[actor["player_id"]]=page
        return True

    async def per_actor(actor):
        try:
            await make_actor(actor)
        except Exception as e:
            errors.append(f"player index={actors.index(actor)} Smart: {type(e).__name__}: {str(e)[:210]}")

    async def score_once(actor,score):
        page=pages.get(actor["player_id"])
        if page is None:return
        try:
            if "/scoreboard/" not in page.url:
                await page.goto(origin+f"/matches/scoreboard/{actor['scoreboard_id']}/",wait_until="domcontentloaded")
            await page.locator("#team1-score-select").select_option(str(score))
            await page.locator("#team2-score-select").select_option("0")
            start=time.monotonic()
            async with page.expect_response(lambda r: "/scoreboard/" in r.url and "/update/" in r.url and r.request.method=="POST",timeout=16000) as action:
                await page.locator("#score-update-form button[type=submit]").click()
            resp=await action.value
            data=await resp.json()
            latencies["score_update"].append((time.monotonic()-start)*1000)
            if resp.status!=200 or data.get("success") is not True:
                raise AssertionError(f"HTTP {resp.status} {str(data)[:200]}")
            counters["score_update"]+=1
        except Exception as e:
            errors.append(f"player index={actors.index(actor)} score: {type(e).__name__}: {str(e)[:210]}")

    async def track_and_shoot(actor):
        page=pages.get(actor["player_id"])
        if page is None:return
        try:
            await page.goto(origin+f"/track/match/{actor['match_id']}/",wait_until="domcontentloaded",timeout=30000)
            counters["track_page"]+=1
            await page.locator(f"#pcard-{actor['player_id']}").click(timeout=15000)
            await page.locator("#shot-hit").wait_for(state="visible")
            await page.locator("#shot-hit").click(timeout=15000)
            async with page.expect_response(lambda r: "/shot/" in r.url and r.request.method=="POST",timeout=16000) as action:
                await page.locator("#shot-miss").click(timeout=15000)
            data=await (await action.value).json()
            if data.get("ok") is not True:
                raise AssertionError(f"tracking shot was rejected {str(data)[:150]}")
            counters["shot_buttons"]+=2
            await page.locator("#mode-btn-pointing").click()
            await page.locator("#shot-good").click()
            counters["pointing_button"]+=1
            await page.locator("#btn-undo").click()
            counters["undo_button"]+=1
            await page.locator("#history-header").click()
            counters["history_button"]+=1
        except Exception as e:
            errors.append(f"player index={actors.index(actor)} tracking: {type(e).__name__}: {str(e)[:230]}")

    async def open_invites(actor):
        page=pages.get(actor["player_id"])
        if page is None:return
        try:
            await page.goto(origin+"/",wait_until="domcontentloaded")
            await page.locator("#pfc-invite-btn").click(timeout=15000)
            await page.wait_for_load_state("domcontentloaded")
            counters["invite_hub_click"]+=1
            if "/invites/" not in page.url:
                raise AssertionError("Invite Hub did not open")
            await page.locator("a.pfc-cta-btn").click()
            counters["smart_return"]+=1
        except Exception as e:
            errors.append(f"player index={actors.index(actor)} invites: {type(e).__name__}: {str(e)[:210]}")

    try:
        async with async_playwright() as p:
            browser=await p.chromium.launch(
                headless=True,args=["--no-sandbox","--disable-dev-shm-usage"]
            )
            try:
                # Multiple progressively larger synchronized connection bursts.
                for total in (5,15,30):
                    cohort=actors[0:total]
                    new=cohort[len(pages):] if len(pages)==total-5 else [
                        actor for actor in cohort if actor["player_id"] not in pages
                    ]
                    t0=time.monotonic()
                    await asyncio.gather(*(per_actor(actor) for actor in new))
                    phases[f"browser_cohort_{total}"]={
                        "elapsed_ms":round((time.monotonic()-t0)*1000),
                        "contexts_created":len(pages),
                        "errors_so_far":len(errors),
                    }
                # Each of six active matches submits three independent live
                # score events, in synchronized waves. Others receive WS pushes.
                owners={}
                for actor in actors:
                    if actor.get("status")=="active" and actor["match_id"] not in owners:
                        owners[actor["match_id"]]=actor
                if len(owners)!=6:
                    raise AssertionError(f"Expected 6 active matches, found {len(owners)}")
                for score in (1,2,3):
                    await asyncio.gather(*(score_once(a,score) for a in owners.values()))
                # Track authorized players by using the real logged-in identity;
                # no fake QR proof or permission bypass is injected.
                tracking_players=[a for a in actors if a.get("status")=="active" and a["player_id"] in pages]
                unique_matches={}
                for actor in tracking_players:
                    unique_matches.setdefault(actor["match_id"],actor)
                await asyncio.gather(*(track_and_shoot(a) for a in unique_matches.values()))
                counters["distinct_match_trackers"]=len(unique_matches)
                # Deliberate same-Match contention, which differs from the
                # six-independent-Match baseline. Store separate markers so a
                # failure is not misdiagnosed as ordinary single-user latency.
                contested_id=next(iter(unique_matches))
                contested=[a for a in tracking_players if a["match_id"]==contested_id]
                counters["same_match_trackers_targeted"]=len(contested)
                await asyncio.gather(*(track_and_shoot(a) for a in contested))
                await asyncio.gather(*(open_invites(a) for a in actors[-4:]))
                await asyncio.sleep(1)
            finally:
                await asyncio.gather(*(ctx.close() for ctx in contexts),return_exceptions=True)
                await browser.close()
    except Exception as e:
        errors.append(f"browser run: {type(e).__name__}: {str(e)[:400]}")

    expected={
        "home":30,"smart":30,"score_update":18,
        "track_page":10,"shot_buttons":20,
        "pointing_button":10,"undo_button":10,
        "history_button":10,"invite_hub_click":4,"smart_return":4,
    }
    for name,value in expected.items():
        if counters[name]!=value:
            errors.append(f"Expected {value} {name} actions, got {counters[name]}")
    metrics={k:{"n":len(v),"p50_ms":percentile_ms(v,0.5),"p95_ms":percentile_ms(v,0.95),"max_ms":round(max(v),1) if v else None} for k,v in latencies.items()}
    report={
        "phase":"real-Chromium-mobile-viewport-30-browser-contexts",
        "courts":6,"players":30,"matches":7,
        "phases":phases,"actions":dict(counters),"timings":metrics,
        "websocket_max_channels_observed":len(open_sockets),
        "http_status_ge400":dict(collections.Counter(str(v["status"]) for v in http_errors)),
        "http_error_examples":http_errors[:12],
        "elapsed_seconds":round(time.monotonic()-started,1),
        "errors":errors[:50],"passed":not errors,
        "limitations":"UI clicks and real scoring/tracking, but excludes official results, court promotion, QR delegation and full multi-round timing. CDN resources blocked.",
    }
    Path(args.output).parent.mkdir(parents=True,exist_ok=True)
    Path(args.output).write_text(json.dumps(report,indent=2)+"\n")
    print(json.dumps(report,indent=2))
    if errors:raise SystemExit(1)


def main():
    parser=argparse.ArgumentParser()
    sub=parser.add_subparsers(dest="cmd",required=True)
    preparser=sub.add_parser("prepare")
    preparser.add_argument("--input",default="/tmp/pfc_vtl_sessions.json")
    preparser.add_argument("--output",default="/tmp/pfc_vtl_browser_sessions.json")
    runner=sub.add_parser("run")
    runner.add_argument("--input",default="/tmp/pfc_vtl_browser_sessions.json")
    runner.add_argument("--output",default="browser-reports/ui-load.json")
    runner.add_argument("--base",default="http://127.0.0.1:8765")
    args=parser.parse_args()
    setup_isolated_django()
    if args.cmd=="prepare":
        prepare(args.input,args.output)
    else:
        asyncio.run(run_browser(args))


if __name__=="__main__":
    main()
