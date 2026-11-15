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
import threading
import psycopg2

class ConnectionMonitor:
    def __init__(self):
        self.samples=[]
        self.db_limits={}
        self.stop=threading.Event()
        self.thread=None
    def start(self):
        def watch():
            try:
                conn=psycopg2.connect(os.environ['DATABASE_URL'],connect_timeout=3)
                conn.autocommit=True
                with conn.cursor() as cur:
                    cur.execute("SELECT current_setting('max_connections')::int, current_setting('superuser_reserved_connections')::int")
                    limit,reserved=cur.fetchone()
                    self.db_limits={'max_connections':limit,'superuser_reserved_connections':reserved,'ordinary_connection_capacity':limit-reserved}
                    while not self.stop.is_set():
                        cur.execute("SELECT count(*),count(*) FILTER (WHERE state='active'),count(*) FILTER (WHERE state='idle') FROM pg_stat_activity WHERE datname=current_database()")
                        self.samples.append(cur.fetchone())
                        self.stop.wait(.05)
                conn.close()
            except Exception as exc:
                self.samples.append({'monitor_error':str(exc)})
        self.thread=threading.Thread(target=watch,daemon=True)
        self.thread.start()
    def finish(self):
        self.stop.set()
        if self.thread:self.thread.join(timeout=5)
        valid=[x for x in self.samples if isinstance(x,tuple)]
        return {'limits':self.db_limits,'samples':len(valid),'peak_total':max((x[0] for x in valid),default=None),'peak_active':max((x[1] for x in valid),default=None),'peak_idle':max((x[2] for x in valid),default=None),'error':next((x['monitor_error'] for x in self.samples if isinstance(x,dict)),None)}

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
    any_errors=False
    for concurrency in (1,10,30):
        batch=actors[:concurrency]
        latencies=[];statuses={};errors=[]
        before_cpu,before_rss=sample(pid)
        monitor=ConnectionMonitor();monitor.start()
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
        db_connections=monitor.finish()
        after_cpu,after_rss=sample(pid)
        results[str(concurrency)]={
            "requests":len(latencies),"elapsed_s":round(elapsed,3),
            "requests_per_second":round(len(latencies)/elapsed,2),
            "p50_ms":percentile(latencies,.50),"p95_ms":percentile(latencies,.95),
            "mean_ms":round(statistics.mean(latencies),2),
            "statuses":statuses,"errors":errors[:10],"error_count":len(errors),"db_connections":db_connections,"error_count":len(errors),"db_connections":db_connections,
            "server_cpu_seconds_delta":round(after_cpu-before_cpu,3) if before_cpu is not None and after_cpu is not None else None,
            "server_rss_mb_before":round(before_rss,2) if before_rss is not None else None,
            "server_rss_mb_after":round(after_rss,2) if after_rss is not None else None,
        }
        print(args.version,concurrency,json.dumps(results[str(concurrency)]),flush=True)
        if errors:any_errors=True
    # Synchronized repeated presses: all 30 sessions, including overlapping
    # requests from the same player. Smart GET only, not mutating buttons.
    for presses in (2,5,10):
        batch=[a for a in actors for _ in range(presses)]
        latencies=[];statuses={};errors=[]
        before_cpu,before_rss=sample(pid)
        monitor=ConnectionMonitor();monitor.start()
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
        db_connections=monitor.finish()
        after_cpu,after_rss=sample(pid)
        results[f"burst_{presses}"]={
            "players":30,"presses_per_player":presses,
            "requests":len(latencies),"elapsed_s":round(elapsed,3),
            "requests_per_second":round(len(latencies)/elapsed,2),
            "p50_ms":percentile(latencies,.50),
            "p95_ms":percentile(latencies,.95),
            "mean_ms":round(statistics.mean(latencies),2),
            "statuses":statuses,"errors":errors[:10],"error_count":len(errors),
            "db_connections":db_connections,
            "server_cpu_seconds_delta":round(after_cpu-before_cpu,3) if before_cpu is not None and after_cpu is not None else None,
            "server_rss_mb_before":round(before_rss,2) if before_rss is not None else None,
            "server_rss_mb_after":round(after_rss,2) if after_rss is not None else None,
        }
        print(args.version,f"burst_{presses}",json.dumps(results[f"burst_{presses}"]),flush=True)
        if errors:any_errors=True
    Path(args.output).write_text(json.dumps({"version":args.version,"results":results},indent=2))
    if any_errors:raise SystemExit("HTTP benchmark completed with errors; all loads recorded")
if __name__=="__main__":main()
