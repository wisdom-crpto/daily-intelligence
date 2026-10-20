"""Presentation invariants that protect authored content and navigation."""
import unittest
from html.parser import HTMLParser
from homepage_renderer import _index_html, _period_reviews, _style_reader_page
from test_refresh_homepage import records, fixture
from pathlib import Path
import tempfile
import datetime as dt


class Outline(HTMLParser):
    def __init__(self):
        super().__init__()
        self.ids = []
        self.controls = []
        self.links = []
    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if 'id' in attrs:
            self.ids.append(attrs['id'])
        if 'aria-controls' in attrs:
            self.controls.append(attrs['aria-controls'])
        if tag == 'a':
            self.links.append(attrs)


class InterfaceTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.rows = records()
        self.summaries = fixture(self.root, self.rows)
    def tearDown(self):
        self.temp.cleanup()

    def test_controls_and_dialog_have_unique_reachable_targets(self):
        page = _index_html(self.rows, self.summaries)
        outline = Outline()
        outline.feed(page)
        self.assertEqual(len(outline.ids), len(set(outline.ids)))
        self.assertTrue(set(outline.controls) <= set(outline.ids))
        for label in ('上一张日报', '下一张周报', '下一张月报', '关闭回顾'):
            self.assertIn('aria-label="' + label + '"', page)
        self.assertIn('aria-labelledby="review-label"', page)

    def test_full_prose_and_coverage_survive_compact_cards(self):
        entry = self.summaries['weekly'][0]
        entry['coverage_note'] = '缺少一期，不能视为完整覆盖。'
        entry['source_hashes'].pop(next(iter(entry['source_hashes'])))
        entry['items'][0]['body'] = '独特的完整分析结尾，不能被截断。'
        page = _period_reviews(self.rows, dt.date(2026, 10, 5), False, self.summaries)
        self.assertIn('已归档 6/7 期 · 覆盖不全', page)
        self.assertIn(entry['coverage_note'], page)
        self.assertIn(entry['items'][0]['body'], page)
        self.assertIn('<details class="insights">', page)
        self.assertIn(entry['watch'], page)
        for date in entry['items'][0]['source_dates']:
            self.assertIn('阅读 ' + date + ' 日报', page)

    def test_reader_old_style_and_repeated_refresh_preserve_body(self):
        article = '<main><h1>原标题</h1><p>原有事实，保持原文。</p><div class="table-wrap"><table><tr><td>100</td></tr></table></div></main>'
        source = '<html><head><style>body{color:red}</style></head><body>' + article + '<footer>出处</footer></body></html>'
        refreshed = _style_reader_page(source)
        self.assertIn(article, refreshed)
        self.assertEqual(refreshed, _style_reader_page(refreshed))
        self.assertEqual(refreshed.count('class="reader-nav"'), 1)
        self.assertIn('返回首页', refreshed)


if __name__ == '__main__':
    unittest.main()
