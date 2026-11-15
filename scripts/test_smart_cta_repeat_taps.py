#!/usr/bin/env python3
"""Real Chromium regression: five immediate SMART taps must start one navigation."""
import asyncio
import json
from pathlib import Path
from urllib.parse import urlsplit
from playwright.async_api import async_playwright

async def main():
    actors=json.loads(Path('/tmp/pfc_vtl_browser_sessions.json').read_text())['actors']
    actor=next(a for a in actors if a.get('session'))
    async with async_playwright() as p:
        browser=await p.chromium.launch(headless=True)
        context=await browser.new_context(service_workers='block')
        await context.add_cookies([{'name':'sessionid','value':actor['session'],
                                   'domain':'127.0.0.1','path':'/','httpOnly':True,'sameSite':'Lax'}])
        async def route_handler(route):
            if urlsplit(route.request.url).hostname not in ('127.0.0.1','localhost'):
                await route.abort()
            else:
                await route.continue_()
        await context.route('**/*',route_handler)
        page=await context.new_page()
        smart_requests=[]
        page.on('request',lambda req: smart_requests.append(req.url)
                if urlsplit(req.url).path=='/my-matches/' else None)
        await page.goto('http://127.0.0.1:8765/',wait_until='domcontentloaded')
        await page.locator('#pfc-smart-cta').wait_for()
        await page.evaluate("""() => {
            const button=document.querySelector('#pfc-smart-cta');
            for(let i=0;i<5;i++) button.click();
        }""")
        await page.wait_for_url(lambda url: urlsplit(str(url)).path!='/',
                                timeout=20000)
        await page.wait_for_load_state('domcontentloaded')
        print('SMART_REPEAT_TAPS',json.dumps({
            'attempted_taps':5,'smart_http_requests':len(smart_requests),
            'destination_path':urlsplit(page.url).path,
        }))
        assert len(smart_requests)==1, f'Expected exactly one SMART request, got {len(smart_requests)}'
        await browser.close()

if __name__=='__main__':
    asyncio.run(main())
