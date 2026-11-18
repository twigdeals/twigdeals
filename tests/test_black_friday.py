#!/usr/bin/env python3
"""Black Friday deals page: ranking, exclusions, and page wiring.

% off is the current price versus the higher of the store's list (compare-at)
price and the highest price Twig Deals has actually tracked. Sports Excellence
and pro stock are never in the retail list. The page is written by the regular
build, at /black-friday/.

Run: python3 tests/test_black_friday.py
"""
import re
import unittest
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BUILD = ROOT / "build.py"


def load_bf():
    src = BUILD.read_text()
    start = src.index("# Black Friday / Cyber Monday")
    end = src.index("\nCSS = ")
    ns = {"defaultdict": defaultdict, "REG": {"CAD": "ca", "USD": "us"}}
    exec(src[start:end], ns)
    return ns


class BlackFridayRanking(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.ns = load_bf()

    def test_reference_uses_store_list_when_it_is_higher(self):
        ref, basis = self.ns["bf_reference"](80, 120, [100, 80])
        self.assertEqual(ref, 120)
        self.assertEqual(basis, "vs. list price")
        self.assertEqual(self.ns["bf_pct"](80, ref), 33)

    def test_reference_uses_tracked_high_when_store_has_no_list(self):
        ref, basis = self.ns["bf_reference"](70, None, [100, 80, 70])
        self.assertEqual(ref, 100)
        self.assertEqual(basis, "vs. tracked high")
        self.assertEqual(self.ns["bf_pct"](70, ref), 30)

    def test_reference_uses_tracked_high_when_it_beats_list(self):
        ref, basis = self.ns["bf_reference"](80, 90, [100, 80])
        self.assertEqual(ref, 100)
        self.assertEqual(basis, "vs. tracked high")

    def test_no_discount_when_price_is_the_high(self):
        self.assertEqual(self.ns["bf_reference"](100, 90, [100]), (None, None))
        self.assertEqual(self.ns["bf_pct"](100, 100), 0)

    def test_prior_price_is_last_observation_before_cutoff(self):
        hist = [
            {"ts": "2026-11-10T00:00:00Z", "price": 200},
            {"ts": "2026-11-16T12:00:00Z", "price": 180},
            {"ts": "2026-11-18T11:00:00Z", "price": 150},
        ]
        self.assertEqual(self.ns["bf_prior_price"](hist, "2026-11-17T00:00:00Z"), 180)
        self.assertIsNone(self.ns["bf_prior_price"](hist[2:], "2026-11-17T00:00:00Z"))

    def test_best_is_one_per_model_sorted_by_percent(self):
        rows = [
            {"model_slug": "a", "size": "Senior", "currency": "USD",
             "bf_pct": 40, "bf_drop": 80, "price": 120, "store": "x"},
            {"model_slug": "a", "size": "Senior", "currency": "USD",
             "bf_pct": 30, "bf_drop": 50, "price": 100, "store": "y"},
            {"model_slug": "b", "size": "Junior", "currency": "CAD",
             "bf_pct": 50, "bf_drop": 90, "price": 40, "store": "z"},
            {"model_slug": "c", "size": "Senior", "currency": "CAD",
             "bf_pct": 9, "bf_drop": 10, "price": 90, "store": "z"},
        ]
        best = self.ns["bf_best"](rows, "bf_pct", drop_key="bf_drop")
        self.assertEqual([v["model_slug"] for v in best], ["b", "a"])
        self.assertEqual(best[1]["bf_pct"], 40)
        senior = self.ns["bf_best"](rows, "bf_pct", size="Senior", drop_key="bf_drop")
        self.assertEqual([v["model_slug"] for v in senior], ["a"])
        ca = self.ns["bf_best"](rows, "bf_pct", region="ca", drop_key="bf_drop")
        self.assertEqual([v["model_slug"] for v in ca], ["b"])

    def test_sports_excellence_is_excluded_from_deals(self):
        self.assertEqual(self.ns["BF_SKIP_STORES"], {"sportsexcellence"})


class BlackFridayWiring(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        # Comments are kept: the beacon test strips comments, but our
        # exclusions and copy live in real code and comments around it.
        cls.src = BUILD.read_text()
        cls.code = "\n".join(l for l in cls.src.splitlines()
                             if not l.lstrip().startswith("#"))

    def test_page_is_written_at_black_friday(self):
        self.assertIn('write("/black-friday/"', self.src)
        self.assertIn("Black Friday Hockey Stick Deals 2026", self.src)
        self.assertIn('write_black_friday(live, last_ts, upd, hist)', self.src)

    def test_nav_footer_banner_and_sitemap_sources(self):
        self.assertIn('href="/black-friday/"', self.src)
        self.assertIn('class="nav-bf"', self.src)
        self.assertIn("class=\"bf-banner\"", self.src)
        # sitemap is built from every index.html the build writes
        self.assertIn("OUT.rglob(\"index.html\")", self.src)
        self.assertIn("sitemap.xml", self.src)

    def test_itemlist_structured_data(self):
        self.assertIn('"@type": "ItemList"', self.src)
        self.assertIn("itemListElement", self.src)

    def test_sports_excellence_and_pro_stock_filtered_out(self):
        self.assertIn('v["store"] not in BF_SKIP_STORES', self.src)
        self.assertIn('not v["pro_stock"]', self.src)
        # The writer only uses confirmed in-stock rows from the latest run
        self.assertIn('v["available"] and v["last_seen"] == last_ts', self.src)

    def test_intro_names_black_friday_and_cyber_monday(self):
        self.assertIn("November 27 and November 30, 2026", self.src)
        self.assertIn("confirm on the store's own site", self.src)
        self.assertIn("twice a day", self.src)

    def test_no_manual_cloudflare_beacon(self):
        self.assertNotIn("static.cloudflareinsights.com/beacon.min.js", self.code)
        self.assertNotIn("data-cf-beacon", self.code)


if __name__ == "__main__":
    unittest.main()
