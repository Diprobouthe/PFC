#!/usr/bin/env python3
"""Isolated per-stage Smart Router profiling, 30 synthetic actors, 4 passes."""
import argparse, collections, json, os, statistics, time
from pathlib import Path
from unittest.mock import patch

PHASES=("_session_player","_resolve_tournament_matches","_resolve_friendly_games","_resolve_nearby_friendly_games")
def pct(a,p):
    s=sorted(a)
    return round(s[min(len(s)-1,int((len(s)-1)*p))],3)
def summary(a):
    return {"mean":round(statistics.mean(a),3),"p50":pct(a,.5),"p95":pct(a,.95)}
def main():
    ap=argparse.ArgumentParser()
    ap.add_argument("--version",required=True)
    ap.add_argument("--output",required=True)
    ap.add_argument("--input",default="/tmp/pfc_vtl_browser_sessions.json")
    args=ap.parse_args()
    if os.getenv("PFC_VTL_ISOLATED")!="1":raise SystemExit("Isolated only")
    from virtual_tournament_lab import setup_isolated_django
    setup_isolated_django()
    from django.test import Client
    from django.db import connection
    import pfc_core.smart_router as router
    actors=json.loads(Path(args.input).read_text())["actors"]
    assert len(actors)==30
    observations=collections.defaultdict(list)
    decisions=[]
    # The baseline router resolves identity inline; _session_player exists only\n    # in the optimized router. Profile shared phases on both variants, and\n    # measure identity cost as part of the full request for both.\n    available_phases=tuple(name for name in PHASES if hasattr(router,name))\n    original={name:getattr(router,name) for name in available_phases}
    current={}
    def wrapped(name):
        def call(*a,**kw):
            before=time.perf_counter()
            cpu=time.process_time()
            try:return original[name](*a,**kw)
            finally:
                current[name+"_wall_ms"]=(time.perf_counter()-before)*1000
                current[name+"_cpu_ms"]=(time.process_time()-cpu)*1000
        return call
    patches=[patch.object(router,name,wrapped(name)) for name in available_phases]
    for p in patches:p.start()
    try:
        for wave in range(4):
            for i,actor in enumerate(actors):
                current={}
                c=Client(HTTP_HOST="127.0.0.1")
                c.cookies["sessionid"]=actor["session"]
                sql_count=0;sql_ms=0;writes=0
                def recorder(execute,sql,params,many,context):
                    nonlocal sql_count,sql_ms,writes
                    t=time.perf_counter()
                    try:return execute(sql,params,many,context)
                    finally:
                        sql_ms+=(time.perf_counter()-t)*1000
                        sql_count+=1
                        writes+=int(sql.lstrip().upper().startswith(("UPDATE ","INSERT ","DELETE ")))
                wall=time.perf_counter();cpu=time.process_time()
                with connection.execute_wrapper(recorder):
                    response=c.get("/my-matches/")
                wall=(time.perf_counter()-wall)*1000
                cpu=(time.process_time()-cpu)*1000
                if response.status_code>=500:raise RuntimeError(f"HTTP {response.status_code}")
                if wave==0:decisions.append([response.status_code,response.get("Location","")])
                for name in available_phases:
                    for suffix in ("wall_ms","cpu_ms"):
                        key=name+"_"+suffix
                        observations[key].append(current.get(key,0))
                for key,value in {"request_wall_ms":wall,"request_cpu_ms":cpu,"sql_ms":sql_ms,"sql_queries":sql_count,"sql_writes":writes}.items():
                    observations[key].append(value)
    finally:
        for p in reversed(patches):p.stop()
    report={"version":args.version,"requests":len(actors)*4,"instrumented_phases":available_phases,"phases":{k:summary(v) for k,v in observations.items()},"decisions":decisions}
    Path(args.output).write_text(json.dumps(report,indent=2))
    print("PHASE_PROFILE",args.version,json.dumps(report["phases"]),flush=True)
if __name__=="__main__":main()
