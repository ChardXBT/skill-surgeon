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
    def test_scalar_metadata_no_crash(self):
        import tempfile
        from surgeon.watch import watch_skill
        from surgeon.model import Skill
        from surgeon.frontmatter import split_frontmatter, parse_frontmatter
        with tempfile.TemporaryDirectory() as td:
            d = Path(td) / "s"; d.mkdir()
            raw = "---\nname: s\ndescription: d\nmetadata: keep\n---\n"
            p = d / "SKILL.md"; p.write_text(raw, encoding="utf-8")
            fm, body, s, e = split_frontmatter(raw)
            meta, _ = parse_frontmatter(fm)
            skill = Skill(path=p, root=d.parent, raw=raw, meta=meta,
                          fm_raw=fm or "", fm_start=s, fm_end=e, body=body)
            res = watch_skill(skill)          # must not raise AttributeError
            self.assertEqual(res, [])

    def test_relative_workspace_resolves_from_skill_dir(self):
        import tempfile
        from surgeon.watch import _workspaces
        from surgeon.model import Skill
        from surgeon.frontmatter import split_frontmatter, parse_frontmatter
        with tempfile.TemporaryDirectory() as td:
            d = Path(td) / "s"; d.mkdir()
            raw = "---\nname: s\ndescription: d\nmetadata:\n  workspace: ../repo\n---\n"
            p = d / "SKILL.md"; p.write_text(raw, encoding="utf-8")
            fm, body, s, e = split_frontmatter(raw)
            meta, _ = parse_frontmatter(fm)
            skill = Skill(path=p, root=d.parent, raw=raw, meta=meta,
                          fm_raw=fm or "", fm_start=s, fm_end=e, body=body)
            ws = _workspaces(skill)
            self.assertEqual(ws[0], d / "../repo")

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


class TestAdopt(unittest.TestCase):
    def _mk(self, td: str, fm_extra: str = ""):
        from surgeon.model import Skill
        from surgeon.frontmatter import split_frontmatter, parse_frontmatter
        d = Path(td) / "s"; d.mkdir()
        raw = f"---\nname: s\ndescription: d\n{fm_extra}---\nbody"
        p = d / "SKILL.md"; p.write_text(raw, encoding="utf-8")
        fm, body, s, e = split_frontmatter(raw)
        meta, _ = parse_frontmatter(fm)
        return Skill(path=p, root=d.parent, raw=raw, meta=meta,
                     fm_raw=fm or "", fm_start=s, fm_end=e, body=body)

    def test_plan_stamps_and_applies(self):
        import tempfile
        from surgeon.adopt import adopt_all
        with tempfile.TemporaryDirectory() as td:
            skill = self._mk(td)
            ads = adopt_all([skill], "C:/repo/x", yes=False)
            self.assertEqual(ads[0].updates["workspace"], "C:/repo/x")
            self.assertFalse(ads[0].applied)            # plan only
            ads = adopt_all([skill], "C:/repo/x", yes=True)
            self.assertTrue(ads[0].applied)
            txt = (Path(td) / "s" / "SKILL.md").read_text()
            self.assertIn("verified_at:", txt)
            self.assertIn("workspace: C:/repo/x", txt)
            self.assertIn("name: s", txt)               # other fields preserved

    def test_restamps_existing(self):
        import tempfile
        from surgeon.adopt import adopt_all
        with tempfile.TemporaryDirectory() as td:
            skill = self._mk(td, "metadata:\n  verified_at: 2020-01-01\n")
            ads = adopt_all([skill], None, yes=True)
            txt = (Path(td) / "s" / "SKILL.md").read_text()
            self.assertNotIn("2020-01-01", txt)
            self.assertIn("verified_at:", txt)


class TestBaseline(unittest.TestCase):
    def test_diff_new_and_resolved(self):
        import tempfile
        from surgeon.baseline import save_baseline, diff_baseline
        from surgeon.model import Finding, Report, Skill
        from surgeon.frontmatter import split_frontmatter, parse_frontmatter
        skills, _ = discover([str(FIXTURES)])
        r1 = Report(skills=skills)
        r1.findings = [Finding("S007", "error", "pdf-summarizer",
                               skills[0].path, "dead ref `x.md`")]
        with tempfile.TemporaryDirectory() as td:
            bp = Path(td) / "base.json"
            save_baseline(bp, r1)
            r2 = Report(skills=skills)   # finding resolved, none new
            r2.findings = []
            d = diff_baseline(bp, r2)
            self.assertEqual(len(d["resolved"]), 1)
            self.assertEqual(len(d["new"]), 0)


class TestEdgeCases(unittest.TestCase):
    def test_dotdot_refs_not_mangled(self):
        from surgeon.smoke import _invoked_files
        files = _invoked_files("python ../scripts/x.py")
        self.assertEqual(files, ["../scripts/x.py"])

    def test_upsert_metadata_flow_style(self):
        from surgeon.frontmatter import upsert_metadata
        fm = 'name: s\nmetadata: {workspace: C:/r}\n'
        out = upsert_metadata(fm, "verified_at", "2026-10-24")
        self.assertIn("workspace: C:/r", out)
        self.assertIn("verified_at: 2026-10-24", out)
        self.assertNotIn("{workspace", out)   # normalized to block

    def test_upsert_replaces_list_children(self):
        from surgeon.frontmatter import upsert_metadata
        fm = 'metadata:\n  workspace:\n    - a\n    - b\n  keep: 1\n'
        out = upsert_metadata(fm, "workspace", "C:/new")
        self.assertIn("workspace: C:/new", out)
        self.assertNotIn("- a", out)          # old list items swallowed
        self.assertIn("keep: 1", out)

    def test_crlf_preserved_on_rewrite(self):
        from surgeon.frontmatter import rewrite_frontmatter
        raw = "---\r\nname: s\r\ndescription: d\r\n---\r\nbody\r\n"
        out = rewrite_frontmatter(raw, {"verified_at": "2026-10-24"})
        self.assertIn("\r\n", out)
        self.assertNotIn("\n", out.replace("\r\n", ""))   # no bare LF
        self.assertIn("verified_at: 2026-10-24", out)

    def test_bom_frontmatter_detected(self):
        from surgeon.frontmatter import split_frontmatter
        fm, body, s, e = split_frontmatter("\ufeff---\nname: x\n---\nbody")
        self.assertIsNotNone(fm)
        self.assertIn("name: x", fm)

    def test_signature_distinguishes_refs(self):
        from surgeon.baseline import _signature
        from surgeon.model import Finding
        from pathlib import Path
        f1 = Finding("S007", "error", "s", Path("x"), "dead ref `a.md`")
        f2 = Finding("S007", "error", "s", Path("x"), "dead ref `b.md`")
        self.assertNotEqual(_signature(f1), _signature(f2))

    def test_apply_fix_crlf_file(self):
        import tempfile
        from surgeon.model import Fix
        from surgeon.report import apply_fix
        with tempfile.TemporaryDirectory() as td:
            p = Path(td) / "SKILL.md"
            p.write_bytes(b"---\r\nname: s\r\ndescription: old desc\r\n---\r\n")
            fx = Fix(id="F-1", skill="s", rule="X", kind="replace_text",
                     file=str(p), rationale="r",
                     find="description: old desc", replace="description: new")
            ok, _ = apply_fix(fx)
            self.assertTrue(ok)
            self.assertIn(b"new", p.read_bytes())
            self.assertIn(b"\r\n", p.read_bytes())      # EOL preserved


class TestConfidence(unittest.TestCase):
    def test_fuzzy_fix_is_review(self):
        skills, findings = fixture_findings()
        fixes = fixes_for_findings(skills, findings, client=None)
        s007 = [f for f in fixes if f.rule == "S007"]
        if s007:   # only when a fuzzy match exists
            self.assertTrue(all(f.confidence == "review" for f in s007))
        s012 = [f for f in fixes if f.rule == "S012"]
        self.assertTrue(all(f.confidence == "safe" for f in s012))


if __name__ == "__main__":
    unittest.main()
