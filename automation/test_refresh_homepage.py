import datetime as dt
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from homepage_renderer import _index_html
from refresh_homepage import main


def records():
    end = dt.date(2026, 10, 5)
    return [dict(date=(d := end - dt.timedelta(days=i)).isoformat(),
                 relative_html=f'{d:%Y/%m/%Y-%m-%d}/Daily%20Intelligence.html',
                 thesis='测试主题', summary='测试摘要', topics=['测试']) for i in range(100)]


class HomepageTests(unittest.TestCase):
    def test_week_month_rollover_and_backfill(self):
        rows = records()
        page = _index_html(rows)
        self.assertEqual(page.count('class="week-card"'), 7)
        self.assertEqual(page.count('class="week-card period-card"'), 7)
        self.assertIn('09/28 — 10/04', page)
        self.assertIn('2026年09月', page)
        self.assertNotIn('2026年10月', page)
        self.assertEqual(page, _index_html(list(reversed(rows))))

    def test_check_rejects_stale_without_writing_and_write_is_idempotent(self):
        with tempfile.TemporaryDirectory() as temp:
            target = Path(temp) / 'index.html'
            target.write_text('stale')
            with patch('refresh_homepage._archive_records', return_value=(records(), [])):
                with patch('sys.argv', ['refresh', '--archive', temp, '--check']):
                    self.assertEqual(main(), 2)
                    self.assertEqual(target.read_text(), 'stale')
                with patch('sys.argv', ['refresh', '--archive', temp, '--write']):
                    self.assertEqual(main(), 0)
                    stamp = target.stat().st_mtime_ns
                    self.assertEqual(main(), 0)
                    self.assertEqual(stamp, target.stat().st_mtime_ns)
                with patch('sys.argv', ['refresh', '--archive', temp, '--check']):
                    self.assertEqual(main(), 0)


if __name__ == '__main__':
    unittest.main()
