#!/usr/bin/env python3
"""Exercise PFC's real Mêlée Court allocator with 4/6/8 Courts and 7 Matches.

This is not a browser or round-generator benchmark. PostgreSQL transactions,
Court claims, lineup freeze, official score validation, and queued handoff
are real. Uses only disposable localhost GitHub Actions services.
"""
from __future__ import annotations

import argparse
import json
import statistics
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from pathlib import Path

from virtual_tournament_lab import setup_isolated_django


def percentile(samples, p):
    if not samples:
        return None
    samples = sorted(samples)
    return round(samples[min(len(samples) - 1, int((len(samples) - 1) * p))] * 1000, 2)


def concurrent_calls(identifiers, callback, label):
    from django.db import connections
    barrier = threading.Barrier(len(identifiers))
    times = []
    results = []
    errors = []
    lock = threading.Lock()

    def worker(identifier):
        connections.close_all()
        try:
            barrier.wait(timeout=25)
            started = time.perf_counter()
            outcome = callback(identifier)
            elapsed = time.perf_counter() - started
            with lock:
                results.append((identifier, outcome))
                times.append(elapsed)
        except Exception as exc:
            with lock:
                errors.append(f"{label} id={identifier}: {type(exc).__name__}: {exc}")
        finally:
            connections.close_all()

    with ThreadPoolExecutor(max_workers=len(identifiers)) as pool:
        futures = [pool.submit(worker, ident) for ident in identifiers]
        for future in futures:
            future.result(timeout=90)
    return {
        "results": results, "errors": errors,
        "p50_ms": percentile(times, 0.5),
        "p95_ms": percentile(times, 0.95),
        "max_ms": round(max(times) * 1000, 2) if times else None,
    }


def prepare(input_file, count):
    from courts.models import Court, CourtComplex
    from tournaments.models import Tournament
    if count not in (4, 6, 8):
        raise SystemExit("Court count must be 4, 6 or 8")
    seed = json.loads(Path(input_file).read_text())
    tournament = Tournament.objects.get(pk=seed["tournament_id"])
    assert seed["matches"] == 7, f"Expected 7 doublettes Matches, got {seed['matches']}"
    complex_obj = CourtComplex.objects.create(
        name=f"VTL {count}-Court complex",
        description="Disposable isolated court saturation test",
    )
    for i in range(count):
        court = Court.objects.create(number=89000+i, is_available=True)
        tournament.courts.add(court)
        complex_obj.courts.add(court)
    return seed, tournament, complex_obj


def examine_state(tournament, complex_obj):
    from courts.models import Court
    from matches.models import Match
    qs = Match.objects.filter(tournament=tournament).order_by("id")
    live = list(qs.filter(status__in=("active", "waiting_validation")).values_list("court_id", flat=True))
    queued = list(qs.filter(status="pending_verification", waiting_for_court=True).values_list("id", flat=True))
    occupied = list(complex_obj.courts.filter(is_available=False).values_list("id", flat=True))
    return {
        "active": len(live),
        "queued": len(queued),
        "completed": qs.filter(status="completed").count(),
        "occupied": len(occupied),
        "unique_live_courts": len(set(live)),
        "null_live_court_ids": sum(cid is None for cid in live),
        "court_ids": live,
        "queued_ids": queued,
        "occupied_ids": occupied,
        "total_matches": qs.count(),
    }


def completed_handoff(tournament, complex_obj, previous_state):
    from matches.lifecycle import submit_official_result, validate_official_result
    from matches.models import Match
    if previous_state["queued"] == 0:
        return {"tested": False, "reason": "All matches fit within available Courts"}
    before_ids = set(previous_state["queued_ids"])
    first = Match.objects.filter(tournament=tournament, status="active").order_by("id").first()
    if first is None:
        raise AssertionError("No active Match exists for a Court handoff")
    original_court = first.court_id
    started = time.perf_counter()
    submit = submit_official_result(
        first.pk, submitted_by_id=first.team1_id,
        team1_score=13, team2_score=7,
    )
    valid = validate_official_result(first.pk, validating_team_id=first.team2_id, agree=True)
    duration = round((time.perf_counter() - started) * 1000, 2)
    first.refresh_from_db()
    after = examine_state(tournament, complex_obj)
    promoted = list(
        Match.objects.filter(pk__in=before_ids, status="active").values_list("id", "court_id")
    )
    assert submit.state in ("submitted", "already_submitted"), submit
    assert valid.state == "completed", valid
    assert first.status == "completed"
    assert len(promoted) == 1, f"Expected exactly one queued Match promoted, got {promoted}"
    assert promoted[0][1] == original_court, (
        f"Handoff used unexpected Court: {promoted[0][1]} not {original_court}"
    )
    assert after["active"] == previous_state["active"], (
        f"Live Match count should remain {previous_state['active']}: {after}"
    )
    assert after["queued"] == previous_state["queued"] - 1
    assert after["unique_live_courts"] == after["active"]
    return {
        "tested": True,
        "elapsed_ms": duration,
        "released_match": first.id,
        "released_court": original_court,
        "promoted_match": promoted[0][0],
        "after": {k:v for k,v in after.items() if k not in ("court_ids","queued_ids","occupied_ids")},
    }


def run_case(args):
    from django.db import connection
    from django.utils import timezone
    from matches.lifecycle import activate_verified_match
    from matches.models import Match
    from tournaments.lineup_lifecycle import finalize_round_lineups
    from tournaments.models import Round

    seed,tournament,complex_obj = prepare(args.input, args.courts)
    round_obj=Round.objects.get(pk=seed["round_id"])
    errors = []
    times = {}
    if args.mode == "batch":
        # Real timed Round freeze, two schedulers racing to finalize at deadline.
        Round.objects.filter(pk=round_obj.pk).update(
            lineup_deadline_at=timezone.now()-timedelta(seconds=2)
        )
        result = concurrent_calls([round_obj.id, round_obj.id],
                                  finalize_round_lineups, "round-finalize")
        times = {key: result[key] for key in ("p50_ms","p95_ms","max_ms")}
        errors.extend(result["errors"])
        # Idempotent second caller may report no ready IDs, but cannot deadlock.
        freezes = [outcome.frozen for _,outcome in result["results"]]
        if len(freezes)!=2 or not all(freezes):
            errors.append("Concurrent Round finalization did not freeze both calls")
    else:
        # Isolate Court row contention from the Round's one-shot batch transition.
        # The real production activation service is called in seven parallel
        # independent PostgreSQL connections; don't simulate Court claims.
        Match.objects.filter(tournament=tournament).update(status="pending_verification")
        ids=list(Match.objects.filter(tournament=tournament).order_by("id").values_list("id",flat=True))
        result = concurrent_calls(ids, activate_verified_match, "claim-court")
        times = {key: result[key] for key in ("p50_ms","p95_ms","max_ms")}
        errors.extend(result["errors"])
        outcomes={r.state:0 for _,r in result["results"]}
        for _,r in result["results"]:
            outcomes[r.state]=outcomes.get(r.state,0)+1
    state=examine_state(tournament,complex_obj)
    expected_active=min(7,args.courts)
    expected_queue=max(0,7-args.courts)
    if state["active"]!=expected_active or state["queued"]!=expected_queue:
        errors.append(f"Wrong allocation: expected {expected_active} active, {expected_queue} queued; got {state['active']}, {state['queued']}")
    if state["unique_live_courts"]!=state["active"] or state["null_live_court_ids"]:
        errors.append("Duplicate or missing Court for a live Match")
    if state["occupied"]!=state["active"]:
        errors.append("Court availability flag disagrees with active Match count")
    handoff=None
    if not errors:
        try:
            handoff=completed_handoff(tournament,complex_obj,state)
        except Exception as exc:
            errors.append(f"Official completion/Court handoff: {type(exc).__name__}: {exc}")
    report={
        "type":"isolated-real-postgresql-court-allocator",
        "mode":args.mode,
        "courts":args.courts,
        "players":len(seed["actors"]),
        "matches":seed["matches"],
        "concurrent_invocations":2 if args.mode=="batch" else 7,
        "timing":times,
        "state_after_allocation":{k:v for k,v in state.items()
                                   if k not in ("court_ids","queued_ids","occupied_ids")},
        "handoff":handoff,
        "errors":errors,
        "passed":not errors,
    }
    Path(args.output).parent.mkdir(parents=True,exist_ok=True)
    Path(args.output).write_text(json.dumps(report,indent=2)+"\n")
    print(json.dumps(report,indent=2))
    if errors:
        raise SystemExit(1)


if __name__=="__main__":
    parser=argparse.ArgumentParser()
    parser.add_argument("--courts",type=int,choices=(4,6,8),required=True)
    parser.add_argument("--mode",choices=("batch","concurrent"),required=True)
    parser.add_argument("--input",default="/tmp/pfc_vtl_sessions.json")
    parser.add_argument("--output",required=True)
    options=parser.parse_args()
    setup_isolated_django()
    run_case(options)
