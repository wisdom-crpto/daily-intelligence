import datetime as dt
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from homepage_renderer import _index_html, SECRET_RE
from editorial_summaries import issue_hash, load_summaries, periods
from refresh_homepage import main


def records():
    end = dt.date(2026, 10, 5)
    return [dict(date=(d := end - dt.timedelta(days=i)).isoformat(),
                 relative_html=f'{d:%Y/%m/%Y-%m-%d}/Daily%20Intelligence.html',
                 thesis='测试主题', summary='测试摘要', topics=['测试']) for i in range(100)]


def fixture(root, rows):
    dates = sorted(r['date'] for r in rows)
    for d in dates:
        p = root / d[:4] / d[5:7] / d / 'Daily Intelligence.md'
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text('合成测试正文 ' + d)
    def entry(start, end):
        sources = [d for d in dates if start <= d <= end]
        return dict(start=start, end=end, title='综合主题', overview='结合各期内容后的综合判断',
                    card_title='读懂变化。', card_deck='用简短导读，呈现重要联系。',
                    items=[dict(heading='重点', body='具体事件、意义和证据边界',
                                source_dates=[sources[0]]) for _ in range(3)],
                    watch='待验证的问题', source_hashes={d: issue_hash(root,d) for d in sources})
    anchor = dt.date.fromisoformat(dates[-1])
    data = dict(schema_version=1, generated_at='2026-10-06T07:00:00+08:00',
                daily={d:entry(d,d) for d in dates[-7:]},
                weekly=[entry(a,b) for a,b in periods(anchor)],
                monthly=[entry(a,b) for a,b in periods(anchor,True)])
    (root/'homepage-summaries.json').write_text(json.dumps(data))
    return data


class HomepageTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.rows = records()
        self.data = fixture(self.root,self.rows)
    def tearDown(self):
        self.temp.cleanup()

    def test_render_and_backfill_order(self):
        page = _index_html(self.rows, load_summaries(self.root,self.rows))
        self.assertEqual(page.count('class="daily-card"'), 7)
        self.assertEqual(page.count('class="editorial-card"'), 7)
        self.assertNotIn('阅读周期回顾', page)
        self.assertIn('接下来值得留意', page)
        period_section = page.split('<section id="weekly">')[1].split('<details id="archive"')[0]
        self.assertNotIn('<h3>2026', period_section)
        for label in ('已归档日报', '最新一期', '月份覆盖'):
            self.assertNotIn(label, page)
        self.assertIn('class="primary-cta" href="2026/10/2026-10-05/Daily%20Intelligence.html"', page)
        self.assertEqual(page, _index_html(list(reversed(self.rows)),self.data))
        self.assertEqual(periods(dt.date(2026,1,5),True)[0],('2025-12-01','2025-12-31'))
        self.assertEqual(periods(dt.date(2024,3,5),True)[0],('2024-02-01','2024-02-29'))

    def test_check_no_writes_and_write_idempotent(self):
        target = self.root/'index.html'
        target.write_text('stale')
        with patch('refresh_homepage._archive_records', return_value=(self.rows, [])):
            with patch('sys.argv', ['refresh', '--archive', str(self.root), '--check']):
                self.assertEqual(main(), 2)
                self.assertEqual(target.read_text(), 'stale')
            with patch('sys.argv', ['refresh', '--archive', str(self.root), '--write']):
                self.assertEqual(main(), 0)
                stamp = target.stat().st_mtime_ns
                self.assertEqual(main(), 0)
                self.assertEqual(stamp, target.stat().st_mtime_ns)
            with patch('sys.argv', ['refresh', '--archive', str(self.root), '--check']):
                self.assertEqual(main(), 0)

    def test_source_revision_requires_editorial_review(self):
        p = self.root/'2026/09/2026-09-01/Daily Intelligence.md'
        p.write_text('后续修正内容')
        with self.assertRaisesRegex(ValueError,'source changed'):
            load_summaries(self.root,self.rows)

    def test_missing_daily_or_period_rejected(self):
        for key in ['daily','weekly']:
            data = json.loads(json.dumps(self.data))
            if key == 'daily':
                del data['daily']['2026-10-05']
            else:
                data['weekly'] = data['weekly'][1:]
            (self.root/'homepage-summaries.json').write_text(json.dumps(data))
            with self.assertRaisesRegex(ValueError,'Write the'):
                load_summaries(self.root,self.rows)

    def test_every_source_and_in_period_citation_required(self):
        data = json.loads(json.dumps(self.data))
        del data['monthly'][0]['source_hashes']['2026-09-01']
        (self.root/'homepage-summaries.json').write_text(json.dumps(data))
        with self.assertRaisesRegex(ValueError,'all available'):
            load_summaries(self.root,self.rows)
        self.data['weekly'][0]['items'][0]['source_dates']=['2026-01-01']
        (self.root/'homepage-summaries.json').write_text(json.dumps(self.data))
        with self.assertRaisesRegex(ValueError,'outside'):
            load_summaries(self.root,self.rows)

    def test_prose_escaped_and_company_slug_not_a_key(self):
        self.data['daily']['2026-10-05']['card_title']='<script>alert(1)</script>'
        self.assertIn('&lt;script&gt;', _index_html(self.rows,self.data))
        self.assertIsNone(SECRET_RE.search('https://example.org/ai-sk-hynix-samsung-memory-market'))
        self.assertIsNotNone(SECRET_RE.search('sk-proj-' + 'x'*30))


if __name__ == '__main__':
    unittest.main()
