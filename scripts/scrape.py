#!/usr/bin/env python3
"""
Daily scraper: fetches public follower counts for LinkedIn, Substack, X.
- LinkedIn: Apify scraper (supreme_coder/linkedin-profile-scraper)
- Substack: Apify playwright-scraper with authenticated cookie
- X: Apify playwright-scraper via residential proxy
Appends results to data/counts.json and commits.
"""

import json
import os
import re
import sys
import time
import urllib.parse
import urllib.request
import urllib.error
from datetime import datetime, timezone

DATA_FILE = os.path.join(os.path.dirname(__file__), '..', 'data', 'counts.json')

APIFY_TOKEN = os.environ.get('APIFY_TOKEN', '')
SUBSTACK_SID = os.environ.get('SUBSTACK_SID', '')
LINKEDIN_URL = 'https://www.linkedin.com/in/ruben-hassid/'
X_SCREEN_NAME = 'RubenHassid'


def apify_request(url, data=None, timeout=15):
    """Helper for Apify API calls."""
    if data is not None:
        body = json.dumps(data).encode()
        req = urllib.request.Request(url, data=body, headers={'Content-Type': 'application/json'})
    else:
        req = urllib.request.Request(url)
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read())


def apify_run_and_poll(actor, input_data, max_wait=300):
    """Start an Apify actor run and poll until complete."""
    run_url = f'https://api.apify.com/v2/acts/{actor}/runs?token={APIFY_TOKEN}'
    result = apify_request(run_url, input_data, timeout=30)
    run_data = result.get('data', result)
    run_id = run_data['id']
    dataset_id = run_data['defaultDatasetId']

    # Poll for completion
    status = 'RUNNING'
    for _ in range(max_wait // 10):
        time.sleep(10)
        status_url = f'https://api.apify.com/v2/actor-runs/{run_id}?token={APIFY_TOKEN}'
        run_info = apify_request(status_url)['data']
        status = run_info['status']
        if status in ('SUCCEEDED', 'FAILED', 'ABORTED'):
            break

    if status != 'SUCCEEDED':
        print(f'  Apify run {run_id} ended with status: {status}', file=sys.stderr)
        return None

    items_url = f'https://api.apify.com/v2/datasets/{dataset_id}/items?token={APIFY_TOKEN}'
    return apify_request(items_url)


# ── LinkedIn: Apify scraper ──
def fetch_linkedin():
    """Get follower count via Apify LinkedIn profile scraper."""
    if not APIFY_TOKEN:
        print('LinkedIn: APIFY_TOKEN not set, skipping', file=sys.stderr)
        return None
    try:
        run_url = f'https://api.apify.com/v2/acts/supreme_coder~linkedin-profile-scraper/runs?token={APIFY_TOKEN}&waitForFinish=120'
        body = json.dumps({"urls": [{"url": LINKEDIN_URL}]}).encode()
        req = urllib.request.Request(run_url, data=body, headers={'Content-Type': 'application/json'})
        with urllib.request.urlopen(req, timeout=130) as r:
            run = json.loads(r.read())

        run_data = run.get('data', run)
        status = run_data.get('status')
        dataset_id = run_data.get('defaultDatasetId')

        if status != 'SUCCEEDED' or not dataset_id:
            print(f'LinkedIn: Apify run status={status}', file=sys.stderr)
            return None

        items_url = f'https://api.apify.com/v2/datasets/{dataset_id}/items?token={APIFY_TOKEN}'
        req = urllib.request.Request(items_url)
        with urllib.request.urlopen(req, timeout=15) as r:
            items = json.loads(r.read())

        if items and len(items) > 0:
            count = items[0].get('followerCount')
            if count and isinstance(count, (int, float)):
                count = int(count)
                print(f'LinkedIn: {count:,}')
                return count

        print('LinkedIn: followerCount not found in Apify response', file=sys.stderr)
        return None
    except Exception as e:
        print(f'LinkedIn error: {e}', file=sys.stderr)
        return None


# ── Substack: Apify playwright-scraper with auth cookie ──
def fetch_substack():
    """Get exact subscriber count via authenticated Substack dashboard."""
    if not APIFY_TOKEN or not SUBSTACK_SID:
        print('Substack: APIFY_TOKEN or SUBSTACK_SID not set, skipping', file=sys.stderr)
        return None
    try:
        cookie_json = json.dumps(SUBSTACK_SID)
        page_function = f'''async function pageFunction({{ page, log }}) {{
            await page.context().addCookies([{{
                name: "substack.sid",
                value: {cookie_json},
                domain: ".substack.com",
                path: "/"
            }}]);
            log.info("Navigating to subscribers page...");
            await page.goto("https://ruben.substack.com/publish/subscribers", {{
                waitUntil: "domcontentloaded",
                timeout: 60000
            }});
            await page.waitForTimeout(10000);
            const text = await page.textContent("body");
            const match = text.match(/(\\d[\\d,]+)\\s+subscribers/);
            const count = match ? parseInt(match[1].replace(/,/g, ""), 10) : null;
            return {{ count, url: page.url() }};
        }}'''

        input_data = {
            "startUrls": [{"url": "https://ruben.substack.com"}],
            "pageFunction": page_function,
            "proxyConfiguration": {"useApifyProxy": True, "apifyProxyGroups": ["RESIDENTIAL"]},
            "launchContext": {"launchOptions": {"headless": False}},
            "maxRequestRetries": 0,
        }

        # Try up to 2 times (Apify residential proxy can be slow)
        for attempt in range(2):
            if attempt > 0:
                print(f'Substack: retrying (attempt {attempt + 1})...', file=sys.stderr)
            items = apify_run_and_poll('apify~playwright-scraper', input_data, max_wait=300)
            if items and items[0].get('count') and items[0]['count'] > 100000:
                count = items[0]['count']
                print(f'Substack: {count:,}')
                return count
            if items:
                print(f'Substack debug: {json.dumps(items[0])[:300]}', file=sys.stderr)

        print('Substack: could not extract count after retries', file=sys.stderr)
        return None
    except Exception as e:
        print(f'Substack error: {e}', file=sys.stderr)
        return None


# ── X: GraphQL guest API ──
TWITTER_BEARER = 'AAAAAAAAAAAAAAAAAAAAANRILgAAAAAAnNwIzUejRCOuH5E6I8xnZz4puTs%3D1Zv7ttfk8LF81IUq16cHjhLTvJu4FA33AGWWjCpTnA'

def fetch_x():
    """Get follower count via X's GraphQL guest API."""
    try:
        variables = json.dumps({"screen_name": X_SCREEN_NAME})
        encoded = urllib.parse.quote(variables)
        url = f'https://api.twitter.com/graphql/BQ6xjFU6Mgm-WhEP3OiT9w/UserByScreenName?variables={encoded}'
        req = urllib.request.Request(url, headers={
            'Authorization': f'Bearer {urllib.parse.unquote(TWITTER_BEARER)}',
            'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36',
        })
        with urllib.request.urlopen(req, timeout=15) as r:
            data = json.loads(r.read())
        user = data.get('data', {}).get('user', {}).get('result', {}).get('legacy', {})
        count = user.get('followers_count')
        if count and isinstance(count, int):
            print(f'X: {count:,}')
            return count
        print('X: followers_count not found in GraphQL response', file=sys.stderr)
        return None
    except Exception as e:
        print(f'X error: {e}', file=sys.stderr)
        return None


def main():
    today = datetime.now(timezone.utc).strftime('%Y-%m-%d')
    print(f'Scraping for {today}...')

    linkedin = fetch_linkedin()
    substack = fetch_substack()
    x = fetch_x()

    if linkedin is None and substack is None and x is None:
        print('All platforms failed. Exiting.', file=sys.stderr)
        sys.exit(1)

    # Load existing data
    os.makedirs(os.path.dirname(DATA_FILE), exist_ok=True)
    if os.path.exists(DATA_FILE):
        with open(DATA_FILE) as f:
            entries = json.load(f)
    else:
        entries = []

    # Sanity check: reject any value that changed more than 20% from the last known value
    def sanity_check(platform, new_val):
        if new_val is None:
            return None
        prev_entries = [e for e in entries if platform in e]
        if not prev_entries:
            return new_val
        last_val = prev_entries[-1][platform]
        change_pct = abs(new_val - last_val) / last_val * 100
        if change_pct > 20:
            print(f'REJECTED {platform}: {new_val:,} is {change_pct:.1f}% off from last value {last_val:,}', file=sys.stderr)
            return None
        return new_val

    linkedin = sanity_check('linkedin', linkedin)
    substack = sanity_check('substack', substack)
    x = sanity_check('x', x)

    if linkedin is None and substack is None and x is None:
        print('All values rejected by sanity check. Exiting.', file=sys.stderr)
        sys.exit(1)

    # Check if we already have an entry for today
    existing = next((e for e in entries if e['date'] == today), None)
    if existing:
        if linkedin is not None:
            existing['linkedin'] = linkedin
        if substack is not None:
            existing['substack'] = substack
        if x is not None:
            existing['x'] = x
        print(f'Updated existing entry for {today}')
    else:
        entry = {'date': today}
        if linkedin is not None:
            entry['linkedin'] = linkedin
        if substack is not None:
            entry['substack'] = substack
        if x is not None:
            entry['x'] = x
        entries.append(entry)
        print(f'Added new entry for {today}')

    entries.sort(key=lambda e: e['date'])

    with open(DATA_FILE, 'w') as f:
        json.dump(entries, f, indent=2)

    print(f'Saved to {DATA_FILE}')
    print(json.dumps(entries[-1], indent=2))


if __name__ == '__main__':
    main()
