#!/usr/bin/env python3
"""
Sync growth data from Google Sheet to counts.json.
Reads the Substack tab (gid=450841066) which has daily data with exact counts.
LinkedIn and X weekly gains come from the main tab (gid=340954267).
"""

import csv
import io
import json
import os
import sys
import re
import urllib.request
from datetime import datetime, timedelta

SHEET_ID = '1-FrnaxjNOyM169T0Rx1HscPf4mMOGePrstGYg2Czz7g'
DATA_FILE = os.path.join(os.path.dirname(__file__), '..', 'data', 'counts.json')


def fetch_csv(gid):
    url = f'https://docs.google.com/spreadsheets/d/{SHEET_ID}/export?format=csv&gid={gid}'
    req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
    with urllib.request.urlopen(req, timeout=15) as r:
        return r.read().decode('utf-8')


def parse_num(s):
    s = s.strip().replace(',', '')
    return int(s) if s.isdigit() else 0


def parse_date(date_str):
    """Parse 'Sun, Mar 29' -> '2026-03-29' (assumes 2025 for May-Dec, 2026 for Jan-Apr)."""
    date_str = date_str.strip()
    if not date_str or date_str == 'average':
        return None
    try:
        # Format: "Sun, Mar 29" or "Fri, May 30"
        dt = datetime.strptime(date_str, '%a, %b %d')
        # Determine year: May-Dec = 2025, Jan-Apr = 2026
        if dt.month >= 5:
            dt = dt.replace(year=2025)
        else:
            dt = dt.replace(year=2026)
        return dt.strftime('%Y-%m-%d')
    except ValueError:
        return None


def parse_week_end(date_range):
    """Parse '29/12 - 04/01' -> '2026-01-04' (end date, always 2026)."""
    parts = date_range.strip().split(' - ')
    if len(parts) != 2:
        return None
    end = parts[1].strip()
    try:
        day, month = end.split('/')
        return f'2026-{int(month):02d}-{int(day):02d}'
    except ValueError:
        return None


def main():
    # Load existing historical data
    if os.path.exists(DATA_FILE):
        with open(DATA_FILE) as f:
            entries = json.load(f)
    else:
        entries = []

    # Index by date for easy merging
    by_date = {e['date']: e for e in entries}

    # ── 1. Substack tab: daily exact counts ──
    print('Fetching Substack tab...')
    sub_csv = fetch_csv(450841066)
    sub_rows = list(csv.reader(io.StringIO(sub_csv)))
    # Header: Substack, Followers HtA, Followers HtP, Free total, Free, AVG, Paid, Paid +, AVG
    sub_count = 0
    for row in sub_rows[2:]:  # skip header + averages row
        date = parse_date(row[0])
        if not date:
            continue
        free_total = row[3].strip().replace(',', '') if len(row) > 3 else ''
        if not free_total.isdigit():
            continue
        count = int(free_total)
        if count < 1000:
            continue
        if date not in by_date:
            by_date[date] = {'date': date}
        by_date[date]['substack'] = count
        sub_count += 1

    print(f'  Substack: {sub_count} daily entries')

    # ── 2. Main tab: LinkedIn and X weekly gains ──
    print('Fetching main tab...')
    main_csv = fetch_csv(340954267)
    main_rows = list(csv.reader(io.StringIO(main_csv)))

    # Row 1: week date ranges
    week_ranges = main_rows[1][1:]
    week_ends = []
    for wr in week_ranges:
        if ' - ' in wr:
            end = parse_week_end(wr)
            if end:
                week_ends.append(end)
        else:
            break

    # Row 16: LinkedIn weekly gains, Row 17: X weekly gains
    li_gains = [parse_num(main_rows[16][i + 1]) if i + 1 < len(main_rows[16]) else 0 for i in range(len(week_ends))]
    x_gains = [parse_num(main_rows[17][i + 1]) if i + 1 < len(main_rows[17]) else 0 for i in range(len(week_ends))]

    # Find LinkedIn and X baselines from existing data (last known before first week)
    first_week_start = '2025-12-29'
    li_baseline = 0
    x_baseline = 0
    for e in sorted(entries, key=lambda e: e['date']):
        if e['date'] < first_week_start:
            if 'linkedin' in e:
                li_baseline = e['linkedin']
            if 'x' in e:
                x_baseline = e['x']

    print(f'  LinkedIn baseline: {li_baseline:,}, X baseline: {x_baseline:,}')

    # Compute cumulative totals for LinkedIn and X at each week end
    li_running = li_baseline
    x_running = x_baseline
    li_count = 0
    x_count = 0
    for i, end_date in enumerate(week_ends):
        li_running += li_gains[i]
        x_running += x_gains[i]

        if end_date not in by_date:
            by_date[end_date] = {'date': end_date}

        by_date[end_date]['linkedin'] = li_running
        li_count += 1

        if x_gains[i] > 0:  # only add X if there's actual data
            by_date[end_date]['x'] = x_running
            x_count += 1

    print(f'  LinkedIn: {li_count} weekly entries, X: {x_count} weekly entries')

    # Remove entries after March 26 that came from the broken scraper
    # (only keep entries that have data from the sheet or historical CSVs)
    for date_key in list(by_date.keys()):
        if date_key > '2026-03-26' and date_key not in set(week_ends):
            e = by_date[date_key]
            # Keep only if it has substack data from the sheet
            if 'substack' not in e:
                del by_date[date_key]

    # Sort and save
    result = sorted(by_date.values(), key=lambda e: e['date'])

    with open(DATA_FILE, 'w') as f:
        json.dump(result, f, indent=2)

    print(f'\nSaved {len(result)} entries. Last 5:')
    for e in result[-5:]:
        print(f'  {e}')


if __name__ == '__main__':
    main()
