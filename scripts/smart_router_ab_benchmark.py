#!/usr/bin/env python3
"""A/B benchmark for PFC Smart. Use only with the isolated VTL test DB.

This script assumes the VTL 30-player / six-Court fixture exists.
It measures (1) per-player Django Smart SQL queries and decision equivalence,
(2) 30 genuine Chromium contexts clicking the visible Smart button.
Never contacts production, mutates prod, or exposes session cookies in reports.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import statistics
import time
from pathlib import Path
from urllib.parse import urlsplit


def percentile(samples, f):
    if not samples:
        return None
    x=sorted(samples)
    return round(x[min(len(x)-1, int((len(x)-1)*f))],2)


def stats(xs):
    return {"count":len(xs),"p50":percentile(xs,.5),"p95":percentile(xs,.95),
            "max":round(max(xs),2) if xs else None,
            "mean":round(statistics.mean(xs),2) if xs else None}


def profile_sql(actors):
    from django.db import connection
    from django.test import Client

    values=[]; decisions=[]; n_5xx=0
    for run in range(4):
        for i, actor in enumerate(actors):
            client=Client(HTTP_HOST="127.0.0.1")
            client.cookies["sessionid"]=actor["session"]
            sql_count=0
            sql_writes=0
            sql_ms=0.

            def recorder(execute, sql, params, many, context):
                nonlocal sql_count, sql_writes, sql_ms
                started=time.perf_counter()
                try:
                    return execute(sql,params,many,context)
                finally:
                    sql_ms+=(time.perf_counter()-started)*1000
                    sql_count+=1
                    sql_writes+=sql.lstrip().upper().startswith(("UPDATE ","INSERT ","DELETE "))
            began=time.perf_counter()
            with connection.execute_wrapper(recorder):
                response=client.get("/my-matches/")
            wall=(time.perf_counter()-began)*1000
            if response.status_code>=500:n_5xx+=1
            if run==0:
                decisions.append({
                    "index":i,
                    "status":response.status_code,
                    "redirect":response.get("Location") if response.status_code in (301,302) else None,
                })
            values.append({"wall_ms":wall,"sql_count":sql_count,
                           "sql_ms":sql_ms,"sql_writes":sql_writes,
                           "role":"active" if actor.get("status")=="active" else
                             ("waiting" if actor["has_match"] else "bye")})
    if n_5xx:raise AssertionError(f"SQL profiling generated {n_5xx} HTTP 5xx")
    grouped={}
    for role in ("active","waiting","bye"):
        subset=[x for x in values if x["role"]==role]
        grouped[role]={
            "wall_ms":stats([x["wall_ms"] for x in subset]),
            "sql_count":stats([x["sql_count"] for x in subset]),
            "sql_time_ms":stats([x["sql_ms"] for x in subset]),
            "write_count":stats([x["sql_writes"] for x in subset]),
        }
    return {"requests":len(values),"by_role":grouped,
            "all_sql_count":stats([x["sql_count"] for x in values]),
            "all_wall_ms":stats([x["wall_ms"] for x in values]),
            "decisions":decisions}


async def profile_browser(actors, base):
    from playwright.async_api import async_playwright
    if urlsplit(base).hostname not in ("127.0.0.1","localhost"):
        raise AssertionError("Smart browser test limited to localhost")
    errors=[]; timings=[]
    async with async_playwright() as p:
        browser=await p.chromium.launch(
            headless=True,args=["--no-sandbox","--disable-dev-shm-usage"]
        )
        contexts=[];pages=[]
        try:
            for actor in actors:
                ctx=await browser.new_context(viewport={"width":390,"height":844},
                                              is_mobile=True,has_touch=True,
                                              service_workers="block")
                await ctx.add_cookies([{"name":"sessionid","value":actor["session"],
                                       "domain":"127.0.0.1","path":"/",
                                       "httpOnly":True,"sameSite":"Lax"}])
                await ctx.route("**/*",lambda route:route.continue_() if
                    urlsplit(route.request.url).hostname in ("localhost","127.0.0.1")
                    else route.abort())
                page=await ctx.new_page()
                contexts.append(ctx)
                pages.append(page)
            for wave in range(3):
                await asyncio.gather(*(page.goto(base+"/",wait_until="domcontentloaded",
                                                  timeout=30000) for page in pages))

                async def click(i,actor,page):
                    began=time.perf_counter()
                    await page.locator("a.pfc-cta-btn").click(timeout=30000)
                    await page.wait_for_load_state("domcontentloaded",timeout=30000)
                    duration=(time.perf_counter()-began)*1000
                    path=urlsplit(page.url).path
                    if actor.get("status")=="active":
                        if path!=f"/matches/scoreboard/{actor['scoreboard_id']}/":
                            raise AssertionError(f"Unexpected active Smart path {path}")
                    if not actor["has_match"] and path!="/my-matches/":
                        raise AssertionError(f"BYE went to {path}")
                    timings.append(duration)
                outcomes=await asyncio.gather(
                    *(click(i,a,page) for i,(a,page) in enumerate(zip(actors,pages))),
                    return_exceptions=True,
                )
                for i,outcome in enumerate(outcomes):
                    if isinstance(outcome,BaseException):
                        errors.append(f"wave={wave} client={i}: {type(outcome).__name__}: {str(outcome)[:140]}")
                if errors:break
        finally:
            await asyncio.gather(*(c.close() for c in contexts),return_exceptions=True)
            await browser.close()
    return {"requested_clicks":len(actors)*3,"measured_clicks":len(timings),
            "click_to_target_ms":stats(timings),"errors":errors}


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument("--version",choices=("baseline","optimized"),required=True)
    parser.add_argument("--base",default="http://127.0.0.1:8765")
    parser.add_argument("--input",default="/tmp/pfc_vtl_browser_sessions.json")
    parser.add_argument("--output",required=True)
    args=parser.parse_args()
    os.environ["PFC_VTL_ISOLATED"]="1"
    from virtual_tournament_lab import setup_isolated_django
    setup_isolated_django()
    actors=json.loads(Path(args.input).read_text())["actors"]
    if len(actors)!=30:raise AssertionError("Expected 30 synthetic player sessions")
    sql=profile_sql(actors)
    browser=asyncio.run(profile_browser(actors,args.base))
    report={"version":args.version,"courts":6,"matches":7,"actors":30,
            "sql":sql,"browser":browser,
            "scope":"isolated 6-court 30-Chromium click comparison; not Render resource equivalent"}
    dest=Path(args.output)
    dest.parent.mkdir(exist_ok=True,parents=True)
    dest.write_text(json.dumps(report,indent=2)+"\n")
    print(json.dumps({
        "version":args.version,
        "sql_queries":sql["all_sql_count"],
        "sql_wall_ms":sql["all_wall_ms"],
        "browser_click_ms":browser["click_to_target_ms"],
        "error_count":len(browser["errors"]),
    },indent=2))
    if browser["errors"] or browser["measured_clicks"]!=90:
        raise SystemExit("Browser Smart A/B case failed: inspect JSON report")


if __name__=="__main__":
    main()
