"""Apply the shared reader shell without changing archived article content."""
import argparse
from pathlib import Path
from homepage_renderer import _style_reader_page


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument('--write', action='store_true')
    mode.add_argument('--check', action='store_true')
    parser.add_argument('--archive', type=Path, default=Path(__file__).resolve().parents[1])
    args = parser.parse_args()
    changes = []
    paths = sorted(args.archive.glob('20??/??/????-??-??/Daily Intelligence.html'))
    for path in paths:
        if path.is_symlink():
            raise ValueError('Reader page must not be a symlink')
        source = path.read_text(encoding='utf-8')
        target = _style_reader_page(source)
        if source != target:
            changes.append((path, target))
    if args.check:
        print(f'Reader style check: {len(paths)} pages, {len(changes)} stale')
        return 2 if changes else 0
    for path, target in changes:
        path.write_text(target, encoding='utf-8')
    print(f'Reader style refresh: {len(changes)} pages; article bodies preserved')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
