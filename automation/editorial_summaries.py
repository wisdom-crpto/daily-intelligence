"""Validate authored homepage summaries against every issue in their period.

This module never generates prose, uses a network, or writes archive files.
"""
import datetime as dt
import hashlib
import json
from pathlib import Path


def periods(anchor, monthly=False):
    end = anchor.replace(day=1) if monthly else anchor - dt.timedelta(days=anchor.weekday())
    result = []
    for _ in range(3 if monthly else 4):
        start = (end - dt.timedelta(days=1)).replace(day=1) if monthly else end - dt.timedelta(days=7)
        result.append((start.isoformat(), (end - dt.timedelta(days=1)).isoformat()))
        end = start
    return result


def issue_hash(root, date):
    path = root / date[:4] / date[5:7] / date / 'Daily Intelligence.md'
    if path.is_symlink():
        raise ValueError('Summary source must not be a symlink')
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load_summaries(root, records):
    path = root / 'homepage-summaries.json'
    if path.is_symlink():
        raise ValueError('Summary file must not be a symlink')
    data = json.loads(path.read_text(encoding='utf-8'))
    if data.get('schema_version') != 1:
        raise ValueError('Unsupported homepage summary schema')
    if dt.datetime.fromisoformat(data['generated_at']).tzinfo is None:
        raise ValueError('Summary timestamp needs a timezone')
    dates = sorted(r['date'] for r in records)
    anchor = dt.date.fromisoformat(dates[-1])

    def text(value):
        if not isinstance(value, str) or not value.strip() or len(value) > 1500:
            raise ValueError('Empty or oversized editorial prose')

    def check(entry, source_dates, daily=False):
        if sorted(entry['source_hashes']) != source_dates:
            raise ValueError('Summary must cover all available issues in its period')
        for date in source_dates:
            if entry['source_hashes'][date] != issue_hash(root, date):
                raise ValueError(f'Summary source changed: {date}; review its editorial content')
        for key in ('title', 'overview'):
            text(entry[key])
        for key, limit in [('card_title', 24), ('card_deck', 60)]:
            text(entry.get(key))
            if len(entry[key]) > limit:
                raise ValueError(f'{key} exceeds the concise homepage copy limit')
        items = entry['items']
        if not isinstance(items, list) or not 3 <= len(items) <= 5:
            raise ValueError('Editorial summary needs 3–5 substantive points')
        for item in items:
            text(item['heading']); text(item['body'])
            if not item['source_dates'] or not set(item['source_dates']) <= set(source_dates):
                raise ValueError('Editorial reference outside its source period')
        if not daily:
            text(entry['watch'])
            start, end = dt.date.fromisoformat(entry['start']), dt.date.fromisoformat(entry['end'])
            if len(source_dates) < (end - start).days + 1:
                text(entry.get('coverage_note'))

    required_daily = [d for d in dates if d >= (anchor - dt.timedelta(days=6)).isoformat()]
    for date in required_daily:
        if date not in data['daily']:
            raise ValueError(f'Write the authored daily highlights for {date} before refreshing')
        check(data['daily'][date], [date], daily=True)
    for kind, monthly in [('weekly', False), ('monthly', True)]:
        by_start = {e['start']: e for e in data[kind]}
        if len(by_start) != len(data[kind]):
            raise ValueError('Duplicate summary period')
        for start, end in periods(anchor, monthly):
            entry = by_start.get(start)
            if entry is None or entry['end'] != end:
                raise ValueError(f'Write the complete {kind} synthesis for {start} before refreshing')
            check(entry, [d for d in dates if start <= d <= end])
    return data
