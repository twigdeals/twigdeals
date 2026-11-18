#!/usr/bin/env python3
"""No hand-written Cloudflare Web Analytics snippet in the page template.

Cloudflare auto-injects the beacon on twigdeals.com. A manual copy in <head>
runs first, claims window.__cfBeacon without a "version", and makes the beacon
POST to cloudflareinsights.com/cdn-cgi/rum, which 404s, so no visits were
recorded from about Oct 20, 2026. The auto-injected copy alone posts to
https://twigdeals.com/cdn-cgi/rum (204).

Run: python3 tests/test_rum_beacon.py
"""
import pathlib
import unittest

BUILD = pathlib.Path(__file__).resolve().parents[1] / "build.py"


class RumBeacon(unittest.TestCase):
    def test_no_manual_cloudflare_beacon_in_template(self):
        code = "\n".join(l for l in BUILD.read_text().splitlines()
                         if not l.lstrip().startswith("#"))
        self.assertNotIn("static.cloudflareinsights.com/beacon.min.js", code)
        self.assertNotIn("data-cf-beacon", code)


if __name__ == "__main__":
    unittest.main()
