"""Re-render only Action Items from Markdown; report prose stays unchanged."""
import argparse
import re
from pathlib import Path

from homepage_renderer import _report_html, _style_reader_page

ACTION_MD = re.compile(r'^(##\s+Action Items[^\n]*\n[\s\S]*?)(?=^##\s|\Z)', re.M)
ACTION_HTML = re.compile(r'<h2>Action Items[^<]*</h2>[\s\S]*?(?=<h2>|</main>)')


def rendered_action(markdown: str) -> str:
    page = _report_html(markdown.rstrip() + '\n\n## _END_\n', 'Action Items')
    match = re.search(r'<h2>Action Items[^<]*</h2>[\s\S]*?(?=<h2>_END_</h2>)', page)
    if not match:
        raise ValueError('Unable to render Action Items')
    return match.group(0)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument('--write', action='store_true')
    mode.add_argument('--check', action='store_true')
    parser.add_argument('--archive', type=Path, default=Path(__file__).resolve().parents[1])
    args = parser.parse_args()
    changes = []
    for html_path in sorted(args.archive.glob('20??/??/????-??-??/Daily Intelligence.html')):
        markdown_path = html_path.with_name('Daily Intelligence.md')
        if html_path.is_symlink() or markdown_path.is_symlink():
            raise ValueError('Daily Intelligence files must not be symlinks')
        markdown_match = ACTION_MD.search(markdown_path.read_text(encoding='utf-8'))
        source = html_path.read_text(encoding='utf-8')
        html_match = ACTION_HTML.search(source)
        if not markdown_match or not html_match:
            continue
        target = source[:html_match.start()] + rendered_action(markdown_match.group(1)) + source[html_match.end():]
        target = _style_reader_page(target)
        if source != target:
            changes.append((html_path, target))
    if args.check:
        print(f'Action Items check: {len(changes)} stale')
        return 2 if changes else 0
    for path, target in changes:
        path.write_text(target, encoding='utf-8')
    print(f'Action Items refresh: {len(changes)} pages; source Markdown unchanged')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
