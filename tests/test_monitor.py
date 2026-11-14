"""Regression tests. Run: python -m unittest discover tests

The tag-98 replay is the acceptance test from spec §13: the archived DE utag.js
from before the 2026-08-24 publish must fire Floodlight tag 98 for ecom
submits, and the publish from 2026-11-05 must not.
"""

import unittest
from pathlib import Path

from playwright.sync_api import sync_playwright

from monitor import checks, loadrules, rules, tealium
from monitor.config import load_platforms

FIX = Path(__file__).parent / "fixtures"
ECOM = [{"name": "ecom_try", "payload": {"action": "form_submit_success", "tealium_event": "form_submit_success",
                                         "customer_lead_type": "ecom_try"}}]
GATED = [{"name": "gated_trial", "payload": {"action": "form_submit_success", "event_name": "form_submit_success",
                                             "triggered_by": "sitecore", "release_date": "2026-01-01",
                                             "gate_content_name": "DE_INT_DE_SMB_TRL_Test",
                                             "customer_lead_type": "Trial_Demo"}}]


class Tag98Replay(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.pw = sync_playwright().start()
        cls.browser = cls.pw.chromium.launch()
        cls.before = (FIX / "utag_de-de_2026-07-13_before.js").read_text(encoding="utf-8")
        cls.after = (FIX / "utag_de-de_2026-11-05_after.js").read_text(encoding="utf-8")

    @classmethod
    def tearDownClass(cls):
        cls.browser.close()
        cls.pw.stop()

    def fired(self, body, events):
        res = loadrules.evaluate(self.browser, body, "de-de", events)
        self.assertTrue(res["ok"], res)
        return set(res["results"][0]["fired"])

    def test_ecom_fired_before_publish(self):
        self.assertIn("98", self.fired(self.before, ECOM))

    def test_ecom_broken_after_publish(self):
        self.assertNotIn("98", self.fired(self.after, ECOM))

    def test_gated_forms_still_fire(self):
        self.assertIn("98", self.fired(self.after, GATED))

    def test_diff_flags_tag98_as_conversion_relevant(self):
        d = tealium.diff_utag(tealium.parse_utag(self.before), tealium.parse_utag(self.after), {"4049", "7132"})
        tag98 = [i for i in d["items"] if i.get("tag") == "98"]
        self.assertTrue(d["conversion_relevant"])
        self.assertEqual(tag98[0]["kind"], "tag_load_rule_changed")
        self.assertIn("utag.cond[274]", tag98[0]["after"]["load"])


class Rating(unittest.TestCase):
    def test_classify_known_vendors(self):
        p = load_platforms()
        hits = checks.classify([
            {"url": "https://ad.doubleclick.net/activity;src=5195550;type=sageg0;cat=dynam0;gclaw=X", "type": "fetch"},
            {"url": "https://bat.bing.com/action/0?ti=12002546&msclkid=X", "type": "img"},
            {"url": "https://region1.analytics.google.com/g/collect?tid=G-PE4Z9JJWVN&gcs=G111", "type": "fetch"},
        ], p)
        self.assertEqual(checks.vendor_summary(hits),
                         {"floodlight": ["5195550"], "ga4": ["G-PE4Z9JJWVN"], "microsoft_uet": ["12002546"]})

    def test_global_incident_needs_three_markets(self):
        fail = {"id": "CONS-02", "severity": "red", "result": "fail", "target": "x"}
        mk = lambda n: {"checks": [dict(fail)] * n, "rating": {"status": "red" if n else "green", "coverage": "full"}}  # noqa: E731
        self.assertEqual(rules.rate_global({"A": mk(1), "B": mk(1), "C": mk(0)})["incidents"], [])
        self.assertEqual(len(rules.rate_global({"A": mk(1), "B": mk(1), "C": mk(1)})["incidents"]), 1)

    def test_acknowledged_finding_does_not_count(self):
        c = [{"id": "TAG:meta", "severity": "red", "result": "fail", "target": "fr-home"}]
        rules.apply_acks("FR", c, [{"id": "a1", "market": "FR", "check": "TAG:meta", "target": "*"}], "2026-11-17")
        self.assertEqual(rules.rate_market(c)["status"], "green")


if __name__ == "__main__":
    unittest.main()
