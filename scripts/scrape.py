#!/usr/bin/env python3
"""
Daily scraper: fetches public follower counts for LinkedIn, Substack, X.
- LinkedIn: Google Sheet (same source as linkedin-fighter — always works)
- Substack: public page subscriber count
- X: GraphQL guest API
"""

import json
import os
import re
import sys
import csv
import io
import urllib.parse
import urllib.request
import urllib.error
from datetime import datetime, timezone

DATA_FILE = os.path.join(os.path.dirname(__file__), '..', 'data', 'counts.json')


# ── LinkedIn: Google Sheet (proven reliable) ──
SHEET_ID = '1j_Z8JuukkskQlfgsIzZgiX_XoSGu_rzNuCGLu_asZuo'

def fetch_linkedin():
    """Get Ruben's follower count from the Google Sheet."""
    try:
        url = f'https://docs.google.com/spreadsheets/d/{SHEET_ID}/export?format=csv'
        req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
        with urllib.request.urlopen(req, timeout=15) as r:
            text = r.read().decode('utf-8')

        rows = list(csv.reader(io.StringIO(text)))
        # Ruben Followers is column E (index 4)
        for row in reversed(rows[1:]):
            if len(row) > 4 and row[4].strip():
                raw = row[4].strip().replace(',', '')
                if raw.isdigit():
                    count = int(raw)
                    print(f'LinkedIn: {count:,}')
                    return count
        print('LinkedIn: no valid data in sheet', file=sys.stderr)
        return None
    except Exception as e:
        print(f'LinkedIn error: {e}', file=sys.stderr)
        return None


# ── Substack: public page ──
def fetch_substack():
    """Get subscriber count from public Substack profile."""
    try:
        req = urllib.request.Request(
            'https://substack.com/@ruben',
            headers={'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36'}
        )
        with urllib.request.urlopen(req, timeout=15) as r:
            html = r.read().decode('utf-8')
        # Page has: subscriberCountNumber":409000
        match = re.search(r'subscriberCountNumber[^0-9]*(\d+)', html)
        if match:
            count = int(match.group(1))
            if count > 10000:
                print(f'Substack: {count:,}')
                return count
        print('Substack: count not found in page', file=sys.stderr)
        return None
    except Exception as e:
        print(f'Substack error: {e}', file=sys.stderr)
        return None


# ── X: GraphQL guest API ──
X_SCREEN_NAME = 'RubenHassid'
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
        print('X: followers_count not found in response', file=sys.stderr)
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
        if last_val == 0:
            return new_val
        change_pct = abs(new_val - last_val) / last_val * 100
        if change_pct > 20:
            print(f'REJECTED {platform}: {new_val:,} is {change_pct:.1f}% off from {last_val:,}', file=sys.stderr)
            return None
        return new_val

    linkedin = sanity_check('linkedin', linkedin)
    substack = sanity_check('substack', substack)
    x = sanity_check('x', x)

    if linkedin is None and substack is None and x is None:
        print('All values failed or rejected. Exiting.', file=sys.stderr)
        sys.exit(1)

    # Save
    existing = next((e for e in entries if e['date'] == today), None)
    if existing:
        if linkedin is not None: existing['linkedin'] = linkedin
        if substack is not None: existing['substack'] = substack
        if x is not None: existing['x'] = x
        print(f'Updated existing entry for {today}')
    else:
        entry = {'date': today}
        if linkedin is not None: entry['linkedin'] = linkedin
        if substack is not None: entry['substack'] = substack
        if x is not None: entry['x'] = x
        entries.append(entry)
        print(f'Added new entry for {today}')

    entries.sort(key=lambda e: e['date'])

    with open(DATA_FILE, 'w') as f:
        json.dump(entries, f, indent=2)

    print(json.dumps(entries[-1], indent=2))


if __name__ == '__main__':
    main()
