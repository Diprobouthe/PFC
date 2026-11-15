#!/usr/bin/env python3
"""Isolated PFC Smart Router HTTP concurrency benchmark; never use production."""
import argparse
import concurrent.futures
import json
import os
import statistics
import time
from pathlib import Path
import requests

def percentile(values, p):
    s=sorted(values)
    return round(s[min(len(s)-1,int((len(s)-1)*p))],2) if s else None

def sample(pid):
    try:
        stat=Path(f"/proc/{pid}/stat").read_text().split()
        ticks=os.sysconf("SC_CLK_TCK")
        cpu=(int(stat[13])+int(stat[14]))/ticks
        rss=int(Path(f"/proc/{pid}/statm").read_text().split()[1])*os.sysconf("SC_PAGE_SIZE")/1048576
        return cpu,rss
    except (OSError,ValueError,IndexError):
        return None,None

def run_one(base,actor):
    with requests.Session() as session:
        session.cookies.set("sessionid",actor["session"],domain="127.0.0.1",path="/")
        start=time.perf_counter()
        try:
            response=session.get(base+"/my-matches/",allow_redirects=False,timeout=20)
            return {"ms":(time.perf_counter()-start)*1000,"status":response.status_code,
                    "location":response.headers.get("Location","")}
        except requests.RequestException as exc:
            return {"ms":(time.perf_counter()-start)*1000,"status":0,"error":type(exc).__name__}

def main():
    ap=argparse.ArgumentParser()
    ap.add_argument("--version",required=True)
    ap.add_argument("--base",default="http://127.0.0.1:8765")
    ap.add_argument("--input",default="/tmp/pfc_vtl_browser_sessions.json")
    ap.add_argument("--pid-file",default="/tmp/daphne.pid")
    ap.add_argument("--output",required=True)
    args=ap.parse_args()
    if args.base!="http://127.0.0.1:8765" or os.getenv("PFC_VTL_ISOLATED")!="1":
        raise SystemExit("Only isolated localhost test allowed")
    actors=json.loads(Path(args.input).read_text())["actors"]
    if len(actors)!=30: raise SystemExit("Exactly 30 synthetic actors required")
    pid=int(Path(args.pid_file).read_text())
    results={}
    for concurrency in (1,10,30):
        batch=actors[:concurrency]
        latencies=[];statuses={};errors=[]
        before_cpu,before_rss=sample(pid)
        start=time.perf_counter()
        # 10 sustained waves; each wave synchronizes all concurrent clients
        with concurrent.futures.ThreadPoolExecutor(max_workers=concurrency) as pool:
            for wave in range(10):
                futures=[pool.submit(run_one,args.base,a) for a in batch]
                for future in concurrent.futures.as_completed(futures):
                    result=future.result()
                    latencies.append(result["ms"])
                    status=str(result["status"])
                    statuses[status]=statuses.get(status,0)+1
                    if result["status"] not in (200,301,302,303):
                        errors.append(result)
        elapsed=time.perf_counter()-start
        after_cpu,after_rss=sample(pid)
        results[str(concurrency)]={
            "requests":len(latencies),"elapsed_s":round(elapsed,3),
            "requests_per_second":round(len(latencies)/elapsed,2),
            "p50_ms":percentile(latencies,.50),"p95_ms":percentile(latencies,.95),
            "mean_ms":round(statistics.mean(latencies),2),
            "statuses":statuses,"errors":errors[:10],
            "server_cpu_seconds_delta":round(after_cpu-before_cpu,3) if before_cpu is not None and after_cpu is not None else None,
            "server_rss_mb_before":round(before_rss,2) if before_rss is not None else None,
            "server_rss_mb_after":round(after_rss,2) if after_rss is not None else None,
        }
        print(args.version,concurrency,json.dumps(results[str(concurrency)]),flush=True)
        if errors: raise SystemExit("HTTP benchmark errors: "+str(errors[:2]))
    # Synchronized repeated presses: all 30 sessions, including overlapping
    # requests from the same player. Smart GET only, not mutating buttons.
    for presses in (2,5,10):
        batch=[a for a in actors for _ in range(presses)]
        latencies=[];statuses={};errors=[]
        before_cpu,before_rss=sample(pid)
        start=time.perf_counter()
        with concurrent.futures.ThreadPoolExecutor(max_workers=len(batch)) as pool:
            futures=[pool.submit(run_one,args.base,a) for a in batch]
            for future in concurrent.futures.as_completed(futures):
                result=future.result()
                latencies.append(result["ms"])
                status=str(result["status"])
                statuses[status]=statuses.get(status,0)+1
                if result["status"] not in (200,301,302,303):
                    errors.append(result)
        elapsed=time.perf_counter()-start
        after_cpu,after_rss=sample(pid)
        results[f"burst_{presses}"]={
            "players":30,"presses_per_player":presses,
            "requests":len(latencies),"elapsed_s":round(elapsed,3),
            "requests_per_second":round(len(latencies)/elapsed,2),
            "p50_ms":percentile(latencies,.50),
            "p95_ms":percentile(latencies,.95),
            "mean_ms":round(statistics.mean(latencies),2),
            "statuses":statuses,"errors":errors[:10],
            "server_cpu_seconds_delta":round(after_cpu-before_cpu,3) if before_cpu is not None and after_cpu is not None else None,
            "server_rss_mb_before":round(before_rss,2) if before_rss is not None else None,
            "server_rss_mb_after":round(after_rss,2) if after_rss is not None else None,
        }
        print(args.version,f"burst_{presses}",json.dumps(results[f"burst_{presses}"]),flush=True)
        if errors:raise SystemExit("Burst errors: "+str(errors[:2]))
    Path(args.output).write_text(json.dumps({"version":args.version,"results":results},indent=2))
if __name__=="__main__":main()
