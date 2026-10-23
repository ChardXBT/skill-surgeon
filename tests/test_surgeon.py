"""Deterministic tests against examples/demo-skills fixtures."""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from surgeon.discover import discover
from surgeon.fixes import fixes_for_findings
from surgeon.frontmatter import parse_frontmatter, split_frontmatter
from surgeon.rules_structural import all_structural

FIXTURES = Path(__file__).resolve().parent.parent / "examples" / "demo-skills"


def fixture_findings():
    skills, _ = discover([str(FIXTURES)])
    return skills, all_structural(skills)


class TestFrontmatter(unittest.TestCase):
    def test_parse_simple(self):
        fm, body, s, e = split_frontmatter("---\nname: x\ndescription: y\n---\nbody")
        self.assertEqual(s, 0)
        meta, err = parse_frontmatter(fm)
        self.assertEqual(meta["name"], "x")
        self.assertEqual(err, "")

    def test_no_frontmatter(self):
        fm, body, s, e = split_frontmatter("# just markdown")
        self.assertIsNone(fm)

    def test_unquoted_colon_fallback(self):
        meta, err = parse_frontmatter("name: x\ndescription: Use when: foo bar")
        self.assertEqual(meta["name"], "x")
        self.assertIn("foo", str(meta.get("description", "")))


class TestDiscovery(unittest.TestCase):
    def test_finds_all_fixtures(self):
        skills, roots = discover([str(FIXTURES)])
        self.assertEqual(len(skills), 5)

    def test_no_duplicates(self):
        skills, _ = discover([str(FIXTURES), str(FIXTURES)])
        paths = [s.path for s in skills]
        self.assertEqual(len(paths), len(set(paths)))


class TestRules(unittest.TestCase):
    def setUp(self):
        self.skills, self.findings = fixture_findings()
        self.by = {}
        for f in self.findings:
            self.by.setdefault((f.skill, f.rule), []).append(f)

    def test_secret_detected(self):
        self.assertIn(("leaky-deployer", "S010"), self.by)

    def test_abs_path_detected(self):
        self.assertIn(("leaky-deployer", "S008"), self.by)

    def test_dead_bundled_ref(self):
        hits = [f for f in self.by.get(("leaky-deployer", "S007"), [])
                if "deploy.sh" in f.message]
        self.assertTrue(hits)

    def test_dated_name(self):
        self.assertIn(("invoice-parser-2025-03-04", "S012"), self.by)

    def test_quoted_injection_not_flagged(self):
        # chat-handoff-style: quoted phrases are warnings ABOUT injection
        self.assertNotIn(("pdf-summarizer", "S011"), self.by)

    def test_placeholder_refs_skipped(self):
        for f in self.findings:
            self.assertNotIn("YYYY", f.message)


class TestFixes(unittest.TestCase):
    def test_fixes_have_exact_strings(self):
        skills, findings = fixture_findings()
        fixes = fixes_for_findings(skills, findings, client=None)
        for fx in fixes:
            if fx.kind == "replace_text":
                self.assertTrue(fx.find, fx.id)
                raw = Path(fx.file).read_text(encoding="utf-8")
                self.assertIn(fx.find, raw, f"{fx.id} find-string not in file")

    def test_dated_name_fix(self):
        skills, findings = fixture_findings()
        fixes = fixes_for_findings(skills, findings, client=None)
        dated = [f for f in fixes if f.rule == "S012"]
        self.assertTrue(dated)
        self.assertIn("invoice-parser", dated[0].replace)


if __name__ == "__main__":
    unittest.main()
