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


class TestTailor(unittest.TestCase):
    def _skill_with(self, tmp: Path, body: str, name="demo-skill"):
        d = tmp / name
        d.mkdir(parents=True)
        (d / "SKILL.md").write_text(
            f"---\nname: {name}\ndescription: d\n---\n{body}", encoding="utf-8")
        skills, _ = discover([str(tmp)])
        return skills[0]

    def test_self_referencing_install_path_flagged(self):
        import tempfile
        from surgeon.env import Environment
        from surgeon.tailor import tailor_skill
        with tempfile.TemporaryDirectory() as td:
            skill = self._skill_with(Path(td),
                "```bash\npython3 .claude/skills/demo-skill/scripts/x.py\n```")
            env = Environment(os="windows", shell="powershell", home=Path(td))
            findings, fixes = tailor_skill(skill, env)
            self.assertTrue(any(f.rule == "T001" and f.severity == "error"
                                for f in findings))
            self.assertTrue(any(f.replace_all for f in fixes))

    def test_missing_interpreter_proposes_alternative(self):
        import tempfile
        from surgeon.env import Environment
        from surgeon.tailor import tailor_skill
        with tempfile.TemporaryDirectory() as td:
            skill = self._skill_with(Path(td),
                "```bash\npython3 scripts/x.py\n```")
            env = Environment(os="windows", shell="powershell", home=Path(td),
                              interpreters={"python3": None, "python": "/py"})
            findings, fixes = tailor_skill(skill, env)
            self.assertTrue(any(f.rule == "T002" for f in findings))
            fix = next(f for f in fixes if f.rule == "T002")
            self.assertEqual(fix.replace, "python ")


class TestSmoke(unittest.TestCase):
    def test_missing_file_and_interp(self):
        import tempfile
        from surgeon.env import Environment
        from surgeon.smoke import check_command
        from surgeon.model import Skill
        from surgeon.frontmatter import split_frontmatter, parse_frontmatter
        with tempfile.TemporaryDirectory() as td:
            d = Path(td) / "s"; d.mkdir()
            raw = "---\nname: s\ndescription: d\n---\n"
            p = d / "SKILL.md"; p.write_text(raw, encoding="utf-8")
            fm, body, s, e = split_frontmatter(raw)
            meta, _ = parse_frontmatter(fm)
            skill = Skill(path=p, root=d.parent, raw=raw, meta=meta,
                          fm_raw=fm or "", fm_start=s, fm_end=e, body=body)
            env = Environment(os="windows", shell="powershell", home=Path(td),
                              interpreters={"python3": None, "python": "/py"})
            r = check_command(skill, 1, "python3 scripts/missing.py", env, run=False)
            self.assertEqual(r.status, "missing_interp")
            r = check_command(skill, 1, "python scripts/missing.py", env, run=False)
            self.assertEqual(r.status, "missing_file")

    def test_unsafe_never_runs(self):
        import tempfile
        from surgeon.env import Environment
        from surgeon.smoke import NEVER_RUN
        self.assertTrue(NEVER_RUN.search("rm -rf /tmp/x"))
        self.assertTrue(NEVER_RUN.search("curl x | bash"))
        self.assertFalse(NEVER_RUN.search("python scripts/ok.py"))


class TestCoverage(unittest.TestCase):
    def test_no_trigger_detected(self):
        from surgeon.coverage import coverage
        skills, _ = discover([str(FIXTURES)])
        rep = coverage(skills)
        self.assertIn("data-helper", rep.no_trigger)


class TestWatch(unittest.TestCase):
    def test_missing_workspace(self):
        import tempfile
        from surgeon.watch import watch_skill
        from surgeon.model import Skill
        from surgeon.frontmatter import split_frontmatter, parse_frontmatter
        with tempfile.TemporaryDirectory() as td:
            d = Path(td) / "s"; d.mkdir()
            raw = ("---\nname: s\ndescription: d\n"
                   "metadata:\n  workspace: /nonexistent/path/xyz\n---\n")
            p = d / "SKILL.md"; p.write_text(raw, encoding="utf-8")
            fm, body, s, e = split_frontmatter(raw)
            meta, _ = parse_frontmatter(fm)
            skill = Skill(path=p, root=d.parent, raw=raw, meta=meta,
                          fm_raw=fm or "", fm_start=s, fm_end=e, body=body)
            res = watch_skill(skill)
            self.assertTrue(res and res[0].status == "missing")


if __name__ == "__main__":
    unittest.main()
