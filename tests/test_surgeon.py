"""Deterministic tests against examples/demo-skills fixtures."""

import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from surgeon.discover import discover, load_skill
from surgeon.fixes import fixes_for_findings
from surgeon.frontmatter import parse_frontmatter, split_frontmatter
from surgeon.model import Finding
from surgeon.rules_structural import (
    all_structural,
    check_skill,
    closest_existing,
)

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

    def test_lenient_parser_nested_shapes(self):
        """Without PyYAML (CI path) nested maps/lists must still parse
        as dicts/lists - a string here crashed scan in GitHub Actions."""
        import surgeon.frontmatter as F
        real = F.yaml
        try:
            F.yaml = None
            meta, _ = F.parse_frontmatter(
                "name: s\ndescription: d\nmetadata:\n"
                "  workspace: C:/r\n  generates:\n    - a.json\n    - b.json\n"
                "folded:\n  multi\n  line\n")
        finally:
            F.yaml = real
        self.assertIsInstance(meta["metadata"], dict)
        self.assertEqual(meta["metadata"]["generates"], ["a.json", "b.json"])
        self.assertEqual(meta["metadata"]["workspace"], "C:/r")
        self.assertEqual(meta["folded"], "multi line")

    def test_scan_survives_lenient_parse(self):
        """all_structural must not crash when metadata parses to scalars."""
        import surgeon.frontmatter as F
        from surgeon.rules_structural import all_structural
        real = F.yaml
        try:
            F.yaml = None
            skills, _ = discover([str(FIXTURES)])
            findings = all_structural(skills)
        finally:
            F.yaml = real
        self.assertTrue(findings)

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


FM = "---\nname: %s\ndescription: does a thing when asked\n%s\n---\n"


def _make_skill(root: Path, rel_dir: str, body: str,
                name: str = "demo-skill", extra_fm: str = "") -> Path:
    d = root / rel_dir
    d.mkdir(parents=True, exist_ok=True)
    p = d / "SKILL.md"
    p.write_text(FM % (name, extra_fm) + body, encoding="utf-8")
    return p


def _rules(findings, rule):
    return [f for f in findings if f.rule == rule]


class TestRegressionFrontmatter(unittest.TestCase):
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
            errs = _rules(check_skill(s), "S001")
            self.assertEqual(1, len(errs))
            self.assertEqual("error", errs[0].severity)
            self.assertIn("metadata", errs[0].message)


class TestRegressionVariants(unittest.TestCase):
    def test_variant_dir_name_mismatch_is_not_flagged(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            p = _make_skill(root, "cap/variants/muse",
                            "body\n", name="cap-muse-variant")
            s = load_skill(p, root)
            self.assertEqual([], _rules(check_skill(s), "S003"))

    def test_plain_dir_name_mismatch_still_flagged(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            p = _make_skill(root, "some-dir", "body\n", name="other-name")
            s = load_skill(p, root)
            self.assertEqual(1, len(_rules(check_skill(s), "S003")))


class TestRegressionRefs(unittest.TestCase):
    def _refs(self, body: str, extra_fm: str = ""):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            p = _make_skill(root, "demo-skill", body, extra_fm=extra_fm)
            s = load_skill(p, root)
            return check_skill(s)

    def test_placeholder_refs_not_flagged(self):
        body = ("Copy `…/task-N-brief.md` into the folder.\n"
                "Then run it on `exact/path/to/file.py`.\n"
                "Edit `tests/test_x.py` as needed.\n")
        self.assertEqual([], _rules(self._refs(body), "S007"))

    def test_output_ref_not_flagged(self):
        body = "The script writes `folio/notes.md` each run.\n"
        self.assertEqual([], _rules(self._refs(body), "S007"))

    def test_dead_bundled_ref_line_number_is_file_line(self):
        body = "line one\nline two\nSee `references/missing.md` for details.\n"
        findings = _rules(self._refs(body), "S007")
        self.assertEqual(1, len(findings))
        self.assertEqual(8, findings[0].line)

    def test_absent_workspace_downgrades_to_warn(self):
        body = "Reads `data/config.json` from the managed repo.\n"
        findings = _rules(
            self._refs(body, extra_fm="metadata:\n  workspace: C:/no/such/dir"),
            "S007")
        self.assertTrue(findings)
        self.assertTrue(all(f.severity == "warn" for f in findings))


class TestRegressionClosestExisting(unittest.TestCase):
    def test_exact_basename_match_is_exact(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            p = _make_skill(root, "demo-skill", "x\n")
            (p.parent / "scripts").mkdir()
            (p.parent / "scripts" / "real.py").write_text("", encoding="utf-8")
            s = load_skill(p, root)
            match, quality = closest_existing("real.py", s)
            self.assertEqual("scripts/real.py", match)
            self.assertEqual("exact", quality)

    def test_multiple_same_basename_is_ambiguous(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            p = _make_skill(root, "demo-skill", "x\n")
            for d in ("techniques/a", "techniques/b"):
                (p.parent / d).mkdir(parents=True)
                (p.parent / d / "TECHNIQUE.md").write_text("", encoding="utf-8")
            s = load_skill(p, root)
            match, quality = closest_existing("TECHNIQUE.md", s)
            self.assertEqual("ambiguous", quality)

    def test_partial_name_match_is_fuzzy(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            p = _make_skill(root, "demo-skill", "x\n")
            (p.parent / "references").mkdir()
            (p.parent / "references" / "GLOSSARY-FORMAT.md").write_text(
                "", encoding="utf-8")
            s = load_skill(p, root)
            match, quality = closest_existing("GLOSSARY.md", s)
            self.assertEqual("references/GLOSSARY-FORMAT.md", match)
            self.assertEqual("fuzzy", quality)


class TestRegressionFixGating(unittest.TestCase):
    def _plan(self, body: str, name: str = "demo-skill",
              extra_fm: str = "", extra_files: dict | None = None):
        td = tempfile.TemporaryDirectory()
        root = Path(td.name)
        p = _make_skill(root, name, body, name=name, extra_fm=extra_fm)
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
        self.assertEqual("scripts/helper.py", s007[0].replace.strip("`"))

    def test_s008_denylist_literal_not_auto(self):
        body = ("## Never synced - denylist literals\n\n"
                "Always strip C:\\Users\\eric\\secrets from output.\n")
        td, s, findings, fixes = self._plan(body)
        self.addCleanup(td.cleanup)
        s008 = [fx for fx in fixes if fx.rule == "S008"]
        self.assertEqual(1, len(s008))
        self.assertFalse(s008[0].auto)
        self.assertEqual("review", s008[0].confidence)

    def test_duplicate_fixes_are_deduplicated(self):
        td = tempfile.TemporaryDirectory()
        root = Path(td.name)
        p = _make_skill(root, "demo-skill", "body\n")
        s = load_skill(p, root)
        same = Finding("S004", "error", s.slug, s.path, "missing", fixable=True)
        fixes = fixes_for_findings([s], [same, same], None)
        self.assertEqual(len(fixes), len({(f.find, f.replace) for f in fixes}))
        td.cleanup()


if __name__ == "__main__":
    unittest.main()
