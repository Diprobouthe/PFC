#!/usr/bin/env python3
"""Authenticated Chromium SMART CTA load, distinct players and five rapid taps each."""
import asyncio
import json
import os
import time
from pathlib import Path
from urllib.parse import urlsplit
from playwright.async_api import async_playwright

ORIGIN = "http://127.0.0.1:8765"

async def main():
    actors=json.loads(Path('/tmp/pfc_vtl_sessions.json').read_text())['actors']
    assert len(actors)==100
    async with async_playwright() as p:
        browser=await p.chromium.launch(headless=True,args=['--disable-dev-shm-usage'])
        for n in (20,30,50,100):
            contexts=[]
            errors=[]
            counts=[]
            durations=[]
            request_start_delays=[]
            server_response_times=[]
            navigation_after_response=[]
            ready=[]
            gate=asyncio.Event()
            async def actor_task(actor):
                context=None
                try:
                    context=await browser.new_context(service_workers='block')
                    contexts.append(context)
                    await context.add_cookies([{'name':'sessionid','value':actor['session'],
                        'domain':'127.0.0.1','path':'/','httpOnly':True,'sameSite':'Lax'}])
                    async def route_handler(route):
                        if urlsplit(route.request.url).hostname not in ('127.0.0.1','localhost'):
                            await route.abort()
                        else:
                            await route.continue_()
                    await context.route('**/*',route_handler)
                    page=await context.new_page()
                    page.set_default_timeout(30000)
                    await page.goto(ORIGIN+'/',wait_until='domcontentloaded',timeout=45000)
                    await page.locator('#pfc-smart-cta').wait_for()
                    seen=[]
                    timing={'request':None,'response':None}
                    def on_request(req):
                        if urlsplit(req.url).path=='/my-matches/':
                            seen.append(req.url)
                            timing['request']=time.monotonic()
                    def on_response(resp):
                        if urlsplit(resp.url).path=='/my-matches/':
                            timing['response']=time.monotonic()
                    page.on('request',on_request)
                    page.on('response',on_response)
                    ready.append(actor['player_id'])
                    await gate.wait()
                    t0=time.monotonic()
                    await page.evaluate("""() => {
                        const a=document.getElementById('pfc-smart-cta');
                        for(let i=0;i<5;i++) a.click();
                    }""")
                    await page.wait_for_url(lambda url: urlsplit(str(url)).path!='/',
                                            timeout=45000)
                    finished=time.monotonic()
                    durations.append(round((finished-t0)*1000,1))
                    if timing['request'] is not None:
                        request_start_delays.append(round((timing['request']-t0)*1000,1))
                    if timing['response'] is not None and timing['request'] is not None:
                        server_response_times.append(round((timing['response']-timing['request'])*1000,1))
                        navigation_after_response.append(round((finished-timing['response'])*1000,1))
                    counts.append(len(seen))
                    if len(seen)!=1:
                        errors.append('player %s made %s SMART requests'%(actor['player_id'],len(seen)))
                except Exception as e:
                    errors.append('player %s: %s: %s'%(actor['player_id'],type(e).__name__,str(e)[:160]))
            tasks=[asyncio.create_task(actor_task(a)) for a in actors[:n]]
            deadline=time.monotonic()+90
            while len(ready)+len(errors)<n and time.monotonic()<deadline:
                await asyncio.sleep(.1)
            gate.set()
            await asyncio.gather(*tasks)
            for c in contexts:
                await c.close()
            def p95(values):
                return sorted(values)[int((len(values)-1)*.95)] if values else None
            result={'players':n,'attempted_taps':5*n,'ready':len(ready),
                    'completed':len(counts),'smart_requests':sum(counts),
                    'one_request_per_player':all(x==1 for x in counts),
                    'p95_ms':p95(durations),
                    'p95_click_to_request_ms':p95(request_start_delays),
                    'p95_request_to_response_ms':p95(server_response_times),
                    'p95_response_to_navigation_ms':p95(navigation_after_response),
                    'timing_samples':{'request':len(request_start_delays),'response':len(server_response_times)},
                    'errors':errors[:12]}
            print('SMART_CTA_SCALE',json.dumps(result),flush=True)
            assert not errors and len(counts)==n and sum(counts)==n, 'SMART CTA scale failure at %s'%n
        await browser.close()

if __name__=='__main__':
    asyncio.run(main())
