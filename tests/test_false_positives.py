"""Regression tests for skill-surgeon false-positive fixes (tmp-dir fixtures).

Each case pins a behavior that previously produced an incorrect finding or
an unsafe fix proposal. Run: py -m unittest discover -s tests -v
"""

from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from surgeon.discover import load_skill  # noqa: E402
from surgeon.fixes import fixes_for_findings  # noqa: E402
from surgeon.model import Finding  # noqa: E402
from surgeon.rules_structural import check_skill, closest_existing  # noqa: E402

FM = "---\nname: %s\ndescription: does a thing when asked\n%s\n---\n"


def make_skill(root: Path, rel_dir: str, body: str,
               name: str = "demo-skill", extra_fm: str = "") -> Path:
    d = root / rel_dir
    d.mkdir(parents=True, exist_ok=True)
    p = d / "SKILL.md"
    p.write_text(FM % (name, extra_fm) + body, encoding="utf-8")
    return p


def rules(findings, rule):
    return [f for f in findings if f.rule == rule]


class TestFrontmatter(unittest.TestCase):
    def test_duplicate_top_level_key_is_error(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            d = root / "dup-key"
            d.mkdir()
            (d / "SKILL.md").write_text(
                "---\nname: dup-key\ndescription: x\n"
                "metadata:\n  a: 1\nmetadata:\n  b: 2\n---\nbody\n",
                encoding="utf-8")
            s = load_skill(d / "SKILL.md", root)
            errs = rules(check_skill(s), "S001")
            self.assertEqual(1, len(errs))
            self.assertEqual("error", errs[0].severity)
            self.assertIn("metadata", errs[0].message)


class TestVariants(unittest.TestCase):
    def test_variant_dir_name_mismatch_is_not_flagged(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            p = make_skill(root, "cap/variants/slot-a",
                           "body\n", name="cap-slot-variant")
            s = load_skill(p, root)
            self.assertEqual([], rules(check_skill(s), "S003"))

    def test_plain_dir_name_mismatch_still_flagged(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            p = make_skill(root, "some-dir", "body\n", name="other-name")
            s = load_skill(p, root)
            self.assertEqual(1, len(rules(check_skill(s), "S003")))


class TestCandidateRefs(unittest.TestCase):
    def _refs(self, body: str, extra_fm: str = ""):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            p = make_skill(root, "demo-skill", body, extra_fm=extra_fm)
            s = load_skill(p, root)
            return check_skill(s)

    def test_placeholder_refs_not_flagged(self):
        body = ("Copy `…/task-N-brief.md` into the folder.\n"
                "Then run it on `exact/path/to/file.py`.\n"
                "Edit `tests/test_x.py` as needed.\n")
        self.assertEqual([], rules(self._refs(body), "S007"))

    def test_output_ref_not_flagged(self):
        body = "The script writes `folio/notes.md` each run.\n"
        self.assertEqual([], rules(self._refs(body), "S007"))

    def test_dead_bundled_ref_line_number_is_file_line(self):
        body = "line one\nline two\nSee `references/missing.md` for details.\n"
        # fm occupies lines 1-5; the ref is on file line 8
        findings = rules(self._refs(body), "S007")
        self.assertEqual(1, len(findings))
        self.assertEqual(8, findings[0].line)

    def test_absent_workspace_downgrades_to_warn(self):
        body = "Reads `data/config.json` from the managed repo.\n"
        findings = rules(
            self._refs(body, extra_fm="metadata:\n  workspace: C:/no/such/dir"),
            "S007")
        self.assertTrue(findings)
        self.assertTrue(all(f.severity == "warn" for f in findings))


class TestClosestExisting(unittest.TestCase):
    def test_exact_basename_match_is_exact(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            p = make_skill(root, "demo-skill", "x\n")
            (p.parent / "scripts").mkdir()
            (p.parent / "scripts" / "real.py").write_text("", encoding="utf-8")
            s = load_skill(p, root)
            match, quality = closest_existing("real.py", s)
            self.assertEqual("scripts/real.py", match)
            self.assertEqual("exact", quality)

    def test_multiple_same_basename_is_ambiguous(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            p = make_skill(root, "demo-skill", "x\n")
            for d in ("techniques/a", "techniques/b"):
                (p.parent / d).mkdir(parents=True)
                (p.parent / d / "TECHNIQUE.md").write_text("", encoding="utf-8")
            s = load_skill(p, root)
            match, quality = closest_existing("TECHNIQUE.md", s)
            self.assertEqual("ambiguous", quality)

    def test_partial_name_match_is_fuzzy(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            p = make_skill(root, "demo-skill", "x\n")
            (p.parent / "references").mkdir()
            (p.parent / "references" / "GLOSSARY-FORMAT.md").write_text(
                "", encoding="utf-8")
            s = load_skill(p, root)
            match, quality = closest_existing("GLOSSARY.md", s)
            self.assertEqual("references/GLOSSARY-FORMAT.md", match)
            self.assertEqual("fuzzy", quality)


class TestFixGating(unittest.TestCase):
    def _plan(self, body: str, name: str = "demo-skill",
              extra_fm: str = "", extra_files: dict[str, str] | None = None):
        td = tempfile.TemporaryDirectory()
        root = Path(td.name)
        p = make_skill(root, name, body, name=name, extra_fm=extra_fm)
        for rel, content in (extra_files or {}).items():
            fp = p.parent / rel
            fp.parent.mkdir(parents=True, exist_ok=True)
            fp.write_text(content, encoding="utf-8")
        s = load_skill(p, root)
        findings = check_skill(s)
        return td, s, findings, fixes_for_findings([s], findings, None)

    def test_fuzzy_s007_fix_is_not_auto(self):
        body = "See `GLOSSARY.md` for terms.\n"
        td, s, findings, fixes = self._plan(
            body, extra_files={"references/GLOSSARY-FORMAT.md": "x"})
        self.addCleanup(td.cleanup)
        s007 = [fx for fx in fixes if fx.rule == "S007"]
        self.assertEqual(1, len(s007))
        self.assertFalse(s007[0].auto)
        self.assertEqual("review", s007[0].confidence)

    def test_exact_s007_fix_can_auto(self):
        body = "Run `helper.py` first.\n"
        td, s, findings, fixes = self._plan(
            body, extra_files={"scripts/helper.py": "x"})
        self.addCleanup(td.cleanup)
        s007 = [fx for fx in fixes if fx.rule == "S007"]
        self.assertEqual(1, len(s007))
        self.assertTrue(s007[0].auto)
        self.assertEqual("safe", s007[0].confidence)
        self.assertEqual("scripts/helper.py", s007[0].replace.strip("`"))

    def test_s008_denylist_literal_not_auto(self):
        # A denylist literal is reported as info and gets no rewrite at all
        # (previously: a review-only fix that still invited an edit).
        body = ("## Never synced - denylist literals\n\n"
                "Always strip C:\\Users\\dana\\secrets from output.\n")
        td, s, findings, fixes = self._plan(body)
        self.addCleanup(td.cleanup)
        self.assertEqual(["info"], [f.severity for f in findings if f.rule == "S008"])
        self.assertEqual([], [fx for fx in fixes if fx.rule == "S008"])

    def test_duplicate_fixes_are_deduplicated(self):
        td = tempfile.TemporaryDirectory()
        root = Path(td.name)
        p = make_skill(root, "demo-skill", "body\n")
        s = load_skill(p, root)
        same = Finding("S004", "error", s.slug, s.path, "missing", fixable=True)
        fixes = fixes_for_findings([s], [same, same], None)
        self.assertEqual(len(fixes), len({(f.find, f.replace) for f in fixes}))
        td.cleanup()


if __name__ == "__main__":
    unittest.main()
