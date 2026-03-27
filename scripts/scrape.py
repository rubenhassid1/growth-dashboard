#!/usr/bin/env python3
"""
Daily scraper: fetches public follower counts for LinkedIn, Substack, X.
- LinkedIn: reads from the existing Google Sheet (already updated daily)
- Substack: scrapes the public newsletter page
- X: uses guest token + GraphQL API
Appends results to data/counts.json and commits.
"""

import json
import os
import re
import sys
import urllib.parse
import urllib.request
import urllib.error
from datetime import datetime, timezone

DATA_FILE = os.path.join(os.path.dirname(__file__), '..', 'data', 'counts.json')

# ── LinkedIn: read from existing Google Sheet ──
SHEET_ID = '1j_Z8JuukkskQlfgsIzZgiX_XoSGu_rzNuCGLu_asZuo'
SHEET_CSV = f'https://docs.google.com/spreadsheets/d/{SHEET_ID}/export?format=csv'

def fetch_linkedin():
    """Get latest Ruben follower count from the linkedin-fighter Google Sheet."""
    try:
        req = urllib.request.Request(SHEET_CSV, headers={'User-Agent': 'Mozilla/5.0'})
        with urllib.request.urlopen(req, timeout=15) as r:
            text = r.read().decode('utf-8')
        lines = text.strip().split('\n')
        if len(lines) < 2:
            return None
        # Last row has the latest data; column 4 (index 4) = Ruben Followers
        last = lines[-1]
        # Parse CSV (handle quoted numbers with commas)
        fields = []
        in_q = False
        field = ''
        for ch in last:
            if ch == '"':
                in_q = not in_q
                continue
            if ch == ',' and not in_q:
                fields.append(field.strip())
                field = ''
                continue
            field += ch
        fields.append(field.strip())
        # Ruben Followers is column index 4
        raw = fields[4] if len(fields) > 4 else ''
        count = int(raw.replace(',', '').replace('"', ''))
        print(f'LinkedIn: {count:,}')
        return count
    except Exception as e:
        print(f'LinkedIn error: {e}', file=sys.stderr)
        return None


# ── Substack: scrape public page ──
def fetch_substack():
    """Scrape subscriber count from ruben.substack.com."""
    try:
        req = urllib.request.Request(
            'https://ruben.substack.com/',
            headers={'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'}
        )
        with urllib.request.urlopen(req, timeout=15) as r:
            html = r.read().decode('utf-8')
        match = re.search(r'([\d,]+)\s*subscriber', html, re.IGNORECASE)
        if match:
            count = int(match.group(1).replace(',', ''))
            print(f'Substack: {count:,}')
            return count
        print('Substack: count not found in page', file=sys.stderr)
        return None
    except Exception as e:
        print(f'Substack error: {e}', file=sys.stderr)
        return None


# ── X: syndication timeline embed ──
X_SCREEN_NAME = 'RubenHassid'

def fetch_x():
    """Get follower count via X's syndication timeline widget."""
    try:
        url = f'https://syndication.twitter.com/srv/timeline-profile/screen-name/{X_SCREEN_NAME}'
        req = urllib.request.Request(url, headers={
            'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36'
        })
        with urllib.request.urlopen(req, timeout=15) as r:
            html = r.read().decode('utf-8')
        match = re.search(r'"followers_count":(\d+)', html)
        if match:
            count = int(match.group(1))
            print(f'X: {count:,}')
            return count
        print('X: followers_count not found in syndication response', file=sys.stderr)
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

    # Check if we already have an entry for today
    existing = next((e for e in entries if e['date'] == today), None)
    if existing:
        # Update existing entry with any new data
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

    # Sort by date
    entries.sort(key=lambda e: e['date'])

    # Write back
    with open(DATA_FILE, 'w') as f:
        json.dump(entries, f, indent=2)

    print(f'Saved to {DATA_FILE}')
    print(json.dumps(entries[-1], indent=2))


if __name__ == '__main__':
    main()
