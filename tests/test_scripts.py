"""Tests for the site-health-audit scripts. Run: python3 -m unittest discover -s tests"""
from __future__ import annotations

import io
import json
import os
import stat
import sys
import tempfile
import unittest
import urllib.error
from contextlib import redirect_stdout, redirect_stderr
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "skills" / "site-health-audit" / "scripts"
FIXTURES = Path(__file__).resolve().parent / "fixtures"
sys.path.insert(0, str(SCRIPTS))

import audit_sites  # noqa: E402
import crux  # noqa: E402
import summarize  # noqa: E402


def load(name: str) -> dict:
    return json.loads((FIXTURES / name).read_text())


PRIORITIES = summarize.load_json(summarize.DEFAULT_PRIORITIES)


class SummarizeTests(unittest.TestCase):
    def setUp(self):
        self.s = summarize.summarize(load("current.json"), PRIORITIES)
        self.by_rule = {f["ruleId"]: f for f in self.s["findings"]}

    def test_broken_links_is_fix_now_and_first(self):
        first = self.s["findings"][0]
        self.assertEqual(first["ruleId"], "links/broken-links")
        self.assertEqual(first["tier"], 1)
        self.assertEqual(first["pagesAffected"], 30)
        self.assertTrue(first["pagesAffectedHasMore"])
        self.assertEqual(first["exampleItems"], ["https://example.com/old/ (404)"])

    def test_title_length_nag_is_demoted(self):
        self.assertEqual(self.by_rule["core/meta-title"]["tier"], 3)

    def test_error_check_wins_over_demoted_warning(self):
        # 1 MB image is a fail at severity error -> tier 2, even though the 200 KB warn is tier 3
        self.assertEqual(self.by_rule["images/image-file-size"]["tier"], 2)

    def test_errors_raised_to_at_least_tier_2(self):
        self.assertEqual(self.by_rule["a11y/form-labels"]["tier"], 2)

    def test_category_default_applies(self):
        self.assertEqual(self.by_rule["url/hyphens"]["tier"], 3)

    def test_duplicate_rule_dropped(self):
        self.assertIn("content/duplicate-title", self.by_rule)
        self.assertNotIn("core/title-unique", self.by_rule)

    def test_info_findings_excluded(self):
        self.assertNotIn("ax/llms-txt", self.by_rule)

    def test_coverage_names_what_was_skipped(self):
        text = " ".join(self.s["coverage"])
        self.assertIn("12 more known URLs were not audited", text)
        self.assertIn("without running JavaScript", text)
        self.assertIn("Links to other websites were not checked", text)
        self.assertIn("Broken External Links", text)

    def test_rejects_unknown_schema(self):
        bad = load("current.json")
        bad["meta"]["schemaVersion"] = "2.0"
        with self.assertRaises(SystemExit):
            summarize.summarize(bad, PRIORITIES)

    def test_markdown_structure(self):
        md = summarize.to_markdown(self.s)
        self.assertIn("# Site health: example.com (2026-11-01)", md)
        self.assertIn("**Score: 72/100 (grade C)**", md)
        self.assertIn("## Fix now (2)", md)  # broken links + duplicate titles
        self.assertIn("## Fix soon (2)", md)  # 1 MB image + form labels
        self.assertIn("## What this audit did not check", md)
        self.assertIn("**At fault:** https://example.com/old/ (404)", md)

    def test_customised_level_label(self):
        r = load("current.json")
        r["meta"]["auditLevel"].update({"level": "custom", "basedOn": "full"})
        self.assertEqual(summarize.summarize(r, PRIORITIES)["level"], "full (customised)")


class DiffTests(unittest.TestCase):
    def setUp(self):
        s = summarize.summarize(load("current.json"), PRIORITIES, previous=load("previous.json"))
        self.d = s["diff"]
        self.md = summarize.to_markdown(s)

    def names(self, key):
        return {f["ruleId"] for f in self.d[key]}

    def test_resolved_only_when_rechecked(self):
        self.assertEqual(self.names("resolved"), {"core/canonical"})
        self.assertEqual(self.names("notRecheckedThisTime"), {"links/broken-external-links"})

    def test_new_and_changed(self):
        self.assertIn("core/meta-title", self.names("new"))
        changed = {f["ruleId"]: (f["previousPages"], f["pagesAffected"]) for f in self.d["changed"]}
        self.assertEqual(changed["links/broken-links"], (35, 30))

    def test_markdown_shows_score_change(self):
        self.assertIn("Score 65 → 72 (+7).", self.md)
        self.assertIn("not counted as resolved", self.md)

    def test_level_mismatch_warns(self):
        prev = load("previous.json")
        prev["meta"]["auditLevel"]["level"] = "quick"
        d = summarize.diff_reports(load("current.json"), prev, PRIORITIES)
        self.assertTrue(any("different levels" in w for w in d["warnings"]))


class CruxTests(unittest.TestCase):
    SAMPLE = {
        "record": {
            "key": {"origin": "https://example.com"},
            "metrics": {
                "largest_contentful_paint": {"percentiles": {"p75": 3100}},
                "interaction_to_next_paint": {"percentiles": {"p75": 150}},
                "cumulative_layout_shift": {"percentiles": {"p75": "0.31"}},
            },
            "collectionPeriod": {"firstDate": {"year": 2026, "month": 10, "day": 1},
                                 "lastDate": {"year": 2026, "month": 10, "day": 28}},
        }
    }

    def test_parse_and_rate(self):
        r = crux.parse_record(self.SAMPLE)
        ratings = {m["key"]: (m["p75Display"], m["rating"]) for m in r["metrics"]}
        self.assertEqual(ratings["largest_contentful_paint"], ("3.1 s", "needs improvement"))
        self.assertEqual(ratings["interaction_to_next_paint"], ("150 ms", "good"))
        self.assertEqual(ratings["cumulative_layout_shift"], ("0.31", "poor"))
        self.assertEqual(r["collectionPeriod"], "2026-10-01 to 2026-10-28")

    def test_404_means_no_data(self):
        def opener(req, timeout):
            raise urllib.error.HTTPError(req.full_url, 404, "Not Found", {}, io.BytesIO(b"{}"))
        r = crux.query({"origin": "https://tiny.example"}, "KEY", opener=opener)
        self.assertEqual(r["status"], "no-data")

    def test_missing_key_is_not_configured(self):
        with tempfile.TemporaryDirectory() as d, mock.patch.dict(os.environ, {}, clear=True):
            out = Path(d) / "c.json"
            self.assertEqual(crux.main(["--origin", "https://example.com", "-o", str(out)]), 0)
            self.assertEqual(json.loads(out.read_text())["status"], "not-configured")

    def test_error_output_never_contains_key(self):
        def opener(req, timeout):
            raise urllib.error.HTTPError(req.full_url, 403, "Forbidden", {},
                                         io.BytesIO(b'{"error": {"message": "API key not valid"}}'))
        r = crux.query({"origin": "https://example.com"}, "SECRET123", opener=opener)
        self.assertEqual(r["status"], "error")
        self.assertNotIn("SECRET123", json.dumps(r))


FAKE_SQUIRREL = """#!/usr/bin/env python3
import json, os, shutil, sys
args = sys.argv[1:]
with open(os.environ["FAKE_SQUIRREL_LOG"], "a") as fh:
    fh.write(json.dumps(args) + "\\n")
code = int(os.environ.get("FAKE_SQUIRREL_EXIT", "0"))
if code == 0:
    shutil.copy(os.environ["FAKE_SQUIRREL_FIXTURE"], args[args.index("-o") + 1])
else:
    print("blocked by robots.txt", file=sys.stderr)
sys.exit(code)
"""


class AuditSitesTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)
        self.squirrel = self.dir / "squirrel"
        self.squirrel.write_text(FAKE_SQUIRREL)
        self.squirrel.chmod(self.squirrel.stat().st_mode | stat.S_IEXEC)
        self.log = self.dir / "calls.log"
        self.env = mock.patch.dict(os.environ, {
            "FAKE_SQUIRREL_LOG": str(self.log),
            "FAKE_SQUIRREL_FIXTURE": str(FIXTURES / "current.json"),
        })
        self.env.start()
        os.environ.pop("CRUX_API_KEY", None)

    def tearDown(self):
        self.env.stop()
        self.tmp.cleanup()

    def run_main(self, *args):
        out, err = io.StringIO(), io.StringIO()
        with redirect_stdout(out), redirect_stderr(err):
            code = audit_sites.main([*args, "--out", str(self.dir / "out"), "--squirrel", str(self.squirrel)])
        return code, out.getvalue()

    def calls(self):
        return [json.loads(line) for line in self.log.read_text().splitlines()]

    def test_always_offline_and_never_publishes(self):
        code, out = self.run_main("https://example.com", "--passive")
        self.assertEqual(code, 0)
        call = self.calls()[0]
        self.assertIn("--offline", call)
        self.assertIn("--passive", call)
        self.assertNotIn("--publish", call)
        self.assertIn("Audited 1 of 1 sites.", out)
        self.assertTrue((self.dir / "out" / "example.com").glob("*-surface.md"))

    def test_second_run_includes_diff(self):
        self.run_main("https://example.com")
        self.run_main("https://example.com")
        reports = sorted((self.dir / "out" / "example.com").glob("*-surface.md"), key=lambda p: p.stat().st_mtime)
        self.assertEqual(len(reports), 2)
        self.assertNotIn("Changes since the last audit", reports[0].read_text())
        self.assertIn("Changes since the last audit", reports[-1].read_text())

    def test_failed_site_is_reported_not_hidden(self):
        os.environ["FAKE_SQUIRREL_EXIT"] = "3"
        try:
            code, out = self.run_main("https://blocked.example")
        finally:
            os.environ.pop("FAKE_SQUIRREL_EXIT")
        self.assertEqual(code, 1)
        self.assertIn("Audited 0 of 1 sites.", out)
        self.assertIn("NOT AUDITED, blocked", out)

    def test_sites_file(self):
        sites = audit_sites.parse_sites_file(
            "# my sites\nhttps://a.example\nhttps://b.example level=full passive max-pages=300  # club\n", "surface")
        self.assertEqual(sites[0], {"url": "https://a.example", "level": "surface", "passive": False, "maxPages": None})
        self.assertEqual(sites[1], {"url": "https://b.example", "level": "full", "passive": True, "maxPages": 300})

    def test_rejects_bad_url(self):
        with self.assertRaises(SystemExit):
            audit_sites.validate({"url": "example.com", "level": "surface"})


class PrioritiesFileTests(unittest.TestCase):
    def test_tiers_are_valid(self):
        for rule, tier in PRIORITIES["rules"].items():
            self.assertIn(tier, (1, 2, 3), rule)
            self.assertRegex(rule, r"^[a-z0-9]+/[a-z0-9-]+$")
        for o in PRIORITIES["messageOverrides"]:
            self.assertIn(o["tier"], (1, 2, 3))


if __name__ == "__main__":
    unittest.main()
