"""Offline homepage refresh/check. No API calls, network, or Git writes."""
import argparse
import sys
from pathlib import Path
from homepage_renderer import _archive_records, _index_html
from editorial_summaries import load_summaries


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument('--write', action='store_true')
    mode.add_argument('--check', action='store_true')
    parser.add_argument('--archive', type=Path, default=Path(__file__).resolve().parents[1])
    args = parser.parse_args()
    root = args.archive.resolve()
    records, _ = _archive_records(root)
    if not records:
        raise ValueError('No archived issues; refusing to replace homepage')
    target = root / 'index.html'
    if target.is_symlink():
        raise ValueError('Homepage must not be a symlink')
    summaries = load_summaries(root, records)
    expected = _index_html(records, summaries)
    current = target.read_text(encoding='utf-8') if target.exists() else None
    if current == expected:
        print('Homepage current: 7 days / 4 completed weeks / 3 completed months')
        return 0
    if args.check:
        print('Homepage stale: run automation/refresh_homepage.py --write before committing', file=sys.stderr)
        return 2
    target.write_text(expected, encoding='utf-8')
    print('Homepage refreshed from archived issue metadata')
    return 0


if __name__ == '__main__':
    try:
        raise SystemExit(main())
    except (ValueError, OSError, KeyError, TypeError) as error:
        print(str(error), file=sys.stderr)
        raise SystemExit(2)
