"""Regression checks for the dated-source and repetition publication gate."""

import datetime as dt
import json
from pathlib import Path
import tempfile
import unittest

from check_news_freshness import check


DAY = dt.date(2026, 10, 2)


def issue(day: dt.date, suffix: str = "today") -> dict:
    return {
        "date": day.isoformat(),
        "generated_at": f"{day.isoformat()}T08:00:00+08:00",
        "thesis": f"A distinct thesis for {suffix}",
        "sources": {
            category: [{
                "title": f"{suffix} {category} event {number}",
                "url": f"https://example.com/{suffix}/{category}/{number}",
                "published": (day - dt.timedelta(days=1)).isoformat(),
                "primary": True,
            } for number in (1, 2)] for category in ("ai", "business_macro")
        },
    }


class FreshnessTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.write(DAY - dt.timedelta(days=1), issue(DAY - dt.timedelta(days=1), "yesterday"))
        self.today = issue(DAY)
        self.write(DAY, self.today)

    def tearDown(self):
        self.temp.cleanup()

    def write(self, day, data):
        path = self.root / f"{day:%Y}" / f"{day:%m}" / day.isoformat() / "data.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(data), encoding="utf-8")

    def failures(self):
        self.write(DAY, self.today)
        return check(self.root, DAY)

    def test_recent_distinct_sources_pass(self):
        self.assertEqual([], self.failures())

    def test_old_source_fails(self):
        self.today["sources"]["ai"][0]["published"] = "2026-09-28"
        self.assertIn("outside current/previous calendar day", " ".join(self.failures()))

    def test_reused_source_and_thesis_fail(self):
        previous = issue(DAY - dt.timedelta(days=1), "yesterday")
        self.today["thesis"] = previous["thesis"]
        self.today["sources"]["ai"][0] = previous["sources"]["ai"][0]
        failures = " ".join(self.failures())
        self.assertIn("thesis repeats", failures)
        self.assertIn("source URL repeats", failures)

    def test_unknown_date_fails(self):
        self.today["sources"]["ai"][0]["published"] = None
        self.assertIn("publication date unknown", " ".join(self.failures()))


if __name__ == "__main__":
    unittest.main()
