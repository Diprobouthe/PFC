#!/usr/bin/env python3
"""Read-only profiling of actual PFC Smart decision + target pages in isolated CI.

Uses Django's full middleware test Client with existing synthetic sessions. All
SQL summaries are aggregate; SQL text, cookies and player IDs stay private.
The single location-context scenario may execute Smart's own stale-friendly
UPDATE statements against the disposable database, never production.
"""
from __future__ import annotations

import collections
import json
import re
import time
from contextlib import contextmanager
from pathlib import Path

from virtual_tournament_lab import setup_isolated_django


class QueryProfile:
    def __init__(self):
        self.entries=[]

    def __call__(self, execute, sql, params, many, context):
        start=time.perf_counter()
        try:
            return execute(sql, params, many, context)
        finally:
            self.entries.append({
                "verb":sql.lstrip().split()[0].upper() if sql.strip() else "UNKNOWN",
                "table":(re.findall(r'\b(?:FROM|JOIN|UPDATE|INTO)\s+"?([a-zA-Z0-9_]+)',sql,re.I) or ["unknown"])[0],
                "elapsed_ms":round((time.perf_counter()-start)*1000,3)
            })

    def summary(self):
        stats=collections.defaultdict(lambda:{"count":0,"sql_ms":0})
        for q in self.entries:
            key=q["verb"]+" "+q["table"]
            stats[key]["count"]+=1
            stats[key]["sql_ms"]+=q["elapsed_ms"]
        return {
            "query_count":len(self.entries),
            "sql_execution_ms":round(sum(x["elapsed_ms"] for x in self.entries),2),
            "writes":sum(x["verb"] in ("UPDATE","INSERT","DELETE") for x in self.entries),
            "top_tables":[{"operation":name,"count":x["count"],"sql_ms":round(x["sql_ms"],2)}
                          for name,x in sorted(stats.items(),key=lambda z:z[1]["sql_ms"],reverse=True)[:12]]
        }


def run():
    from django.db import connection
    from django.test import Client
    from django.contrib.sessions.backends.db import SessionStore
    from courts.models import CourtComplex
    from friendly_games.court_utils import SESSION_PREF_COMPLEX_KEY

    source=json.loads(Path("/tmp/pfc_vtl_browser_sessions.json").read_text())
    actors=source["actors"]
    examples={}
    for actor in actors:
        name=("active" if actor.get("status")=="active"
              else "waiting" if actor.get("has_match") else "bye")
        examples.setdefault(name,actor)
    complex_obj=CourtComplex.objects.order_by("id").first()
    if set(examples)!={"active","waiting","bye"} or complex_obj is None:
        raise AssertionError(f"Missing test fixture: examples={list(examples)}, complex={complex_obj}")

    out=[]
    for context_mode in ("without_location","with_location"):
        for role,actor in examples.items():
            if context_mode=="with_location":
                session=SessionStore(session_key=actor["session"])
                session[SESSION_PREF_COMPLEX_KEY]=complex_obj.id
                session.save()
            client=Client(HTTP_HOST="127.0.0.1")
            client.cookies["sessionid"]=actor["session"]
            for iteration in range(2):
                tracker=QueryProfile()
                started=time.perf_counter()
                with connection.execute_wrapper(tracker):
                    response=client.get("/my-matches/",follow=False)
                decision_ms=(time.perf_counter()-started)*1000
                entry={
                    "context":context_mode,"role":role,"iteration":iteration+1,
                    "step":"smart_decision","status":response.status_code,
                    "wall_ms":round(decision_ms,2),**tracker.summary()
                }
                out.append(entry)
                location=response.get("Location") or ""
                if response.status_code in (301,302) and location.startswith("/"):
                    tracker2=QueryProfile()
                    started=time.perf_counter()
                    with connection.execute_wrapper(tracker2):
                        target=client.get(location,follow=False)
                    entry2={
                        "context":context_mode,"role":role,"iteration":iteration+1,
                        "step":"target_page","status":target.status_code,
                        "wall_ms":round((time.perf_counter()-started)*1000,2),
                        **tracker2.summary()
                    }
                    out.append(entry2)
    for entry in out:
        if entry["status"]>=500:
            raise AssertionError("Unexpected server-side 500 in SQL profiling "+str(entry))
    report={
        "scope":"12 Smart resolver requests plus redirected pages; sequential test Client, not loaded real browser",
        "metrics":out
    }
    Path("browser-reports").mkdir(exist_ok=True)
    Path("browser-reports/sql-profile.json").write_text(json.dumps(report,indent=2)+"\n")
    for e in out:
        print(f"{e['context']:16} {e['role']:8} {e['step']:14} "
              f"HTTP {e['status']:3} wall={e['wall_ms']:6.1f}ms "
              f"SQL={e['query_count']:3} ops, {e['sql_execution_ms']:6.1f}ms "
              f"writes={e['writes']}")
    print("SQL summary saved in browser-reports/sql-profile.json")


if __name__=="__main__":
    setup_isolated_django()
    run()
