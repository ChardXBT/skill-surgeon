"""Regression tests for crashes, wrong results and Windows-path bugs found by
running every surgeon command against real multi-root skill libraries.

Each test names the bug it pins. Run: python -m unittest discover -s tests -v
"""

from __future__ import annotations

import io
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from surgeon import baseline, cli, coverage, env as envmod, smoke, tailor  # noqa: E402
from surgeon.adopt import detect_workspace  # noqa: E402
from surgeon.discover import discover, is_nested, load_skill  # noqa: E402
from surgeon.fixes import fixes_for_findings, fixes_for_semantic  # noqa: E402
from surgeon.model import Finding, Fix, Report  # noqa: E402
from surgeon.report import apply_fix, render_terminal  # noqa: E402
from surgeon.rules_structural import (all_structural, check_skill,  # noqa: E402
                                      closest_existing)

FM = "---\nname: {name}\ndescription: {desc}\n{extra}---\n"


def write_skill(root: Path, rel: str, body: str = "body\n", name: str = "",
                desc: str = "Use when testing.", extra: str = "",
                newline: str = "\n") -> Path:
    d = root / rel
    d.mkdir(parents=True, exist_ok=True)
    p = d / "SKILL.md"
    text = FM.format(name=name or d.name, desc=desc, extra=extra) + body
    p.write_bytes(text.replace("\n", newline).encode("utf-8"))
    return p


def rules(findings, rule):
    return [f for f in findings if f.rule == rule]


class TmpCase(unittest.TestCase):
    def setUp(self):
        self._td = tempfile.TemporaryDirectory()
        self.root = Path(self._td.name).resolve()

    def tearDown(self):
        self._td.cleanup()

    def skill(self, rel, body="body\n", **kw):
        return load_skill(write_skill(self.root, rel, body, **kw), self.root)


# --- frontmatter.py -----------------------------------------------------------

class TestLenientParserScalars(unittest.TestCase):
    """Without PyYAML (the stdlib-only path) quoted scalars kept their
    quotes: `name: "x"` raised a false S002 and quoted workspace paths
    never resolved."""

    def test_quotes_and_comments_match_yaml(self):
        from surgeon.frontmatter import _manual_parse
        meta = _manual_parse(
            'name: "demo-skill"\n'
            'description: "Read-only: watches things"\n'
            "metadata:\n"
            "  workspace:\n"
            "    - ~/repo\n"
            '    - "~/dir with space"\n'
            "  note: 'it''s' # trailing comment\n"
            "  verified_at: 2026-10-01 # stamped\n")
        self.assertEqual("demo-skill", meta["name"])
        self.assertEqual("Read-only: watches things", meta["description"])
        self.assertEqual(["~/repo", "~/dir with space"],
                         meta["metadata"]["workspace"])
        self.assertEqual("it's", meta["metadata"]["note"])
        self.assertEqual("2026-10-01", meta["metadata"]["verified_at"])


# --- fixes.py ---------------------------------------------------------------

class TestS009DuplicateAcrossRoots(TmpCase):
    """S009 passed confidence= to list.append -> TypeError crashed `scan`
    whenever one name existed in two roots; its location filter compared a
    posix path against backslash Windows paths, and every copy got its own
    contradictory "prefer this root" fix."""

    def test_divergent_copies_produce_one_manual_fix_without_crashing(self):
        write_skill(self.root / "a", "dup-skill", "version one\n")
        write_skill(self.root / "b", "dup-skill", "version two\n")
        write_skill(self.root / "c", "dup-skill", "version three\n")
        skills, _ = discover([str(self.root / r) for r in ("a", "b", "c")])
        findings = all_structural(skills)
        self.assertEqual(3, len([f for f in rules(findings, "S009")
                                 if f.severity == "error"]))
        fixes = [f for f in fixes_for_findings(skills, findings, None)
                 if f.rule == "S009"]
        self.assertEqual(1, len(fixes))
        fx = fixes[0]
        self.assertEqual(("manual", False, "review"),
                         (fx.kind, fx.auto, fx.confidence))
        for s in skills:
            self.assertEqual(1, fx.rationale.count(str(s.path)))


class TestSemanticFixBuilders(TmpCase):
    """_replace_line_fix() took no `confidence` argument, so S005/Q001/Q002
    fixes raised TypeError as soon as a local model was reachable."""

    def test_q001_q002_fixes_build_and_quote_yaml(self):
        a = self.skill("alpha", desc="does a thing")
        b = self.skill("beta", desc="does a thing too")
        analysis = {
            "collisions": [{"a": "alpha", "b": "beta", "confidence": "medium",
                            "reason": "same", "suggest_a": "Use when: alpha",
                            "suggest_b": "Use for beta work"}],
            "descriptions": [{"name": "alpha", "quality": 3,
                              "suggested": "Use when alpha # really"}],
        }
        fixes, findings = fixes_for_semantic([a, b], analysis, 0)
        self.assertEqual({"Q001", "Q002"}, {f.rule for f in fixes})
        self.assertTrue(all(f.confidence == "review" for f in fixes))
        # model text with ": " or " #" must be quoted or the YAML breaks
        q = [f.replace for f in fixes if f.skill == "alpha"]
        self.assertIn('description: "Use when: alpha"', q)
        self.assertIn('description: "Use when alpha # really"', q)
        self.assertIn("description: Use for beta work",
                      [f.replace for f in fixes if f.skill == "beta"])

    def test_s005_condense_fix_builds(self):
        s = self.skill("long-one", desc="x" * 1100)
        finding = Finding("S005", "warn", s.slug, s.path, "too long", fixable=True)
        with mock.patch("surgeon.fixes.condense_description",
                        return_value="Use when short."):
            fixes = fixes_for_findings([s], [finding], client=object())
        self.assertEqual(1, len(fixes))
        self.assertEqual("review", fixes[0].confidence)


class TestS007Fixes(TmpCase):
    def test_exact_target_is_safe_confidence(self):
        """Every S007 fix was labelled `review`, so --safe-only never applied
        even a same-named-file rewrite the docs call deterministic."""
        s = self.skill("demo", "Run `helper.py` first.\n")
        (s.dir / "scripts").mkdir()
        (s.dir / "scripts" / "helper.py").write_text("", encoding="utf-8")
        fx = [f for f in fixes_for_findings([s], check_skill(s), None)
              if f.rule == "S007"]
        self.assertEqual(1, len(fx))
        self.assertEqual(("safe", True), (fx[0].confidence, fx[0].auto))

    def test_markdown_link_ref_fix_targets_the_link(self):
        """The fix always searched for `ref` in backticks; a markdown-link
        reference `[x](ref)` produced a find string that never matched."""
        s = self.skill("demo", "See [the guide](guide.md) for details.\n")
        (s.dir / "references").mkdir()
        (s.dir / "references" / "guide.md").write_text("", encoding="utf-8")
        fx = [f for f in fixes_for_findings([s], check_skill(s), None)
              if f.rule == "S007"][0]
        self.assertEqual(("](guide.md)", "](references/guide.md)"),
                         (fx.find, fx.replace))
        ok, msg = apply_fix(fx)
        self.assertTrue(ok, msg)
        self.assertIn("[the guide](references/guide.md)",
                      s.path.read_text(encoding="utf-8"))

    def test_fuzzy_guess_needs_similar_stems(self):
        """`.sops.yaml` was 'fixed' to `agents/openai.yaml`: comparing whole
        basenames let the shared `.yaml` carry the similarity score."""
        s = self.skill("demo", "x\n")
        (s.dir / "agents").mkdir()
        (s.dir / "agents" / "openai.yaml").write_text("", encoding="utf-8")
        self.assertEqual((None, ""), closest_existing(".sops.yaml", s))


class TestS012AndS010(TmpCase):
    def test_dated_name_rename_is_never_auto(self):
        """S012 proposed an auto/safe rename of the invocation name (part of
        `apply --all`) and told the operator to rename `x` -> `x`."""
        s = self.skill("namer", name="namer-2026-06-22")
        fx = [f for f in fixes_for_findings([s], check_skill(s), None)
              if f.rule == "S012"][0]
        self.assertEqual((False, "review"), (fx.auto, fx.confidence))
        self.assertNotIn("rename the directory", fx.rationale)

    def test_each_secret_gets_its_own_redaction(self):
        """S010 always redacted the first secret in the file, so a second
        secret's finding produced a duplicate fix and stayed in place."""
        s = self.skill("leaky", "a ghp_" + "A" * 30 + "\n\nb AKIA" + "B" * 16 + "\n")
        fx = [f for f in fixes_for_findings([s], check_skill(s), None)
              if f.rule == "S010"]
        self.assertEqual({"ghp_" + "A" * 30, "AKIA" + "B" * 16},
                         {f.find for f in fx})


# --- report.apply_fix -------------------------------------------------------

class TestApplyFixBytes(TmpCase):
    """apply_fix wrote with Path.write_text: on Windows text mode expands
    every \\n, turning LF files into CRLF and CRLF files into \\r\\r\\n."""

    def _fix(self, p):
        return Fix(id="F-001", skill="s", rule="S007", kind="replace_text",
                   file=str(p), rationale="", find="`a.md`", replace="`b.md`")

    def test_lf_file_stays_lf(self):
        p = write_skill(self.root, "lf", "see `a.md`\nnext\n")
        self.assertTrue(apply_fix(self._fix(p))[0])
        data = p.read_bytes()
        self.assertNotIn(b"\r", data)
        self.assertIn(b"see `b.md`\nnext\n", data)

    def test_crlf_file_stays_crlf(self):
        p = write_skill(self.root, "crlf", "see `a.md`\nnext\n", newline="\r\n")
        before = p.read_bytes().count(b"\r\n")
        self.assertTrue(apply_fix(self._fix(p))[0])
        data = p.read_bytes()
        self.assertNotIn(b"\r\r\n", data)
        self.assertEqual(before, data.count(b"\r\n"))
        self.assertIn(b"see `b.md`\r\nnext\r\n", data)

    def test_non_utf8_file_is_refused_not_mangled(self):
        p = self.root / "latin1.md"
        p.write_bytes(b"caf\xe9 `a.md`\n")
        ok, msg = apply_fix(self._fix(p))
        self.assertFalse(ok)
        self.assertIn("UTF-8", msg)
        self.assertEqual(b"caf\xe9 `a.md`\n", p.read_bytes())


# --- rules_structural false positives -----------------------------------------

class TestRefFalsePositives(TmpCase):
    def s007(self, body, **kw):
        return rules(check_skill(self.skill("demo", body, **kw)), "S007")

    def test_denylist_section_entries_are_not_refs(self):
        body = ("OUT OF SCOPE (never synced):\n\n"
                "- `config/` - account config, `market_snapshot.json`\n")
        ws = self.root / "ws"
        ws.mkdir()
        self.assertEqual([], self.s007(
            body, extra=f"metadata:\n  workspace: {ws.as_posix()}\n"))

    def test_refs_after_example_marker_are_illustrative(self):
        self.assertEqual([], self.s007(
            "- **Examples:** `references/schema.md` for tables.\n"
            "- e.g. `scripts/rotate_pdf.py` for PDFs.\n"))
        # a real ref BEFORE the marker is still checked
        self.assertEqual(1, len(self.s007(
            "See `references/api.md` (e.g. for auth).\n")))

    def test_numbered_elided_suffix_and_cited_refs(self):
        self.assertEqual([], self.s007(
            "Edit `ppt/slides/slideN.xml` or `slideLayoutN.xml`.\n"
            "Plans go in `NNN-short-slug.md`.\n"
            "Names like `Q3-report…v12-final.pdf` truncate.\n"
            "Notes go in a separate `-notes.md` file.\n"
            "| `Toast.tsx:41` | appears instantly |\n"))
        # case-sensitive: a real `plan.md` is not a placeholder
        self.assertEqual(1, len(self.s007("Follow the `plan.md` steps.\n")))

    def test_runtime_presence_checks_are_not_dead_refs(self):
        self.assertEqual([], self.s007(
            "Use `.interface-design/system.md` if present.\n"
            "Check for `DESIGN.md` in the project.\n"))

    def test_generic_name_shared_by_several_bundled_files(self):
        s = self.skill("maps", "Load only that technique's `TECHNIQUE.md`.\n")
        for t in ("a", "b"):
            (s.dir / "techniques" / t).mkdir(parents=True)
            (s.dir / "techniques" / t / "TECHNIQUE.md").write_text("", encoding="utf-8")
        self.assertEqual([], rules(check_skill(s), "S007"))

    def test_relative_workspace_resolves_from_skill_dir(self):
        """A relative metadata.workspace was resolved from the process cwd."""
        s = self.skill("ops", "Reads `data/state.json`.\n",
                       extra="metadata:\n  workspace: ../repo\n")
        (self.root / "repo" / "data").mkdir(parents=True)
        absent = [f for f in check_skill(s) if "absent" in f.message]
        self.assertEqual([], absent)


class TestAbsolutePaths(TmpCase):
    def s008(self, body):
        return rules(check_skill(self.skill("demo", body)), "S008")

    def test_bare_users_dir_and_placeholder_users_not_flagged(self):
        self.assertEqual([], self.s008(
            "Never commit `C:\\Users` paths.\n"
            "Install to `C:\\Users\\<you>\\tools` or /home/$USER/tools.\n"
            "Or C:/Users/USERNAME/AppData.\n"))

    def test_real_user_path_still_flagged(self):
        self.assertEqual(1, len(self.s008("Run C:\\Users\\dana\\repo\\x.py\n")))

    def test_denylist_literal_is_info_without_fix(self):
        s = self.skill("demo", "## Never synced - denylist literals\n\n"
                               "Always strip C:\\Users\\dana\\secrets from output.\n")
        f = rules(check_skill(s), "S008")
        self.assertEqual(["info"], [x.severity for x in f])
        self.assertEqual([], [x for x in fixes_for_findings([s], f, None)])


# --- discovery: vendored + nested -------------------------------------------

class TestVendoredAndNested(TmpCase):
    def test_vendor_dirs_skipped_by_default_and_reported(self):
        write_skill(self.root, "director")
        write_skill(self.root, "director/vendor/pack/skills/up-skill")
        skipped = []
        skills, _ = discover([str(self.root)], skipped=skipped)
        self.assertEqual(["director"], [s.slug for s in skills])
        self.assertEqual(1, len(skipped))
        skills, _ = discover([str(self.root)], include_vendored=True)
        self.assertEqual(2, len(skills))
        # passing the vendor tree itself scans it
        skills, _ = discover([str(self.root / "director" / "vendor")])
        self.assertEqual(["up-skill"], [s.slug for s in skills])

    def test_scan_report_mentions_skipped_vendored(self):
        write_skill(self.root, "director")
        write_skill(self.root, "director/vendor/pack/up-skill")
        report, _, roots = cli.run_scan([str(self.root)], "m", "h", True, True)
        self.assertEqual(1, len(report.skipped_vendored))
        self.assertIn("skipped 1 vendored", render_terminal(report, roots))
        self.assertEqual("disabled (--no-semantic)", report.semantic_note)

    def test_nested_family_skill_vs_variant(self):
        write_skill(self.root, "pack")
        sub = self.skill("pack/skills/sub-skill")
        var = self.skill("fam/variants/slot-a", name="fam")
        write_skill(self.root, "fam2")
        var2 = self.skill("fam2/variants/claude", name="fam2")
        top = self.skill("pack")
        self.assertTrue(is_nested(sub))
        self.assertFalse(is_nested(var))
        self.assertFalse(is_nested(var2))
        self.assertFalse(is_nested(top))


class TestCoverage(TmpCase):
    def test_nested_and_variant_labels(self):
        """Variants were listed as the same bare name several times, and
        family sub-skills (routed by their parent) as 'may never fire'."""
        write_skill(self.root, "pack", desc="Use when packing.")
        write_skill(self.root, "pack/skills/sub-skill", desc="Sub thing")
        write_skill(self.root, "fam/variants/a", name="fam", desc="Fam thing")
        write_skill(self.root, "fam/variants/b", name="fam", desc="Fam thing")
        skills, _ = discover([str(self.root)])
        rep = coverage.coverage(skills)
        self.assertEqual(["fam (fam/variants/a)", "fam (fam/variants/b)"],
                         sorted(rep.no_trigger))
        self.assertEqual(["sub-skill"], rep.no_trigger_nested)

    def test_same_skill_in_two_roots_gets_distinct_labels(self):
        write_skill(self.root / "lib" / "skills", "relay", desc="Relay thing")
        write_skill(self.root / "home" / "skills", "relay", desc="Relay thing")
        skills, _ = discover([str(self.root / "lib" / "skills"),
                              str(self.root / "home" / "skills")])
        rep = coverage.coverage(skills)
        self.assertEqual(["relay (home/skills/relay)", "relay (lib/skills/relay)"],
                         sorted(rep.no_trigger))

    def test_trigger_phrasings_recognised(self):
        for desc in ("Load at session start to steer the agent.",
                     "Principles you can invoke by name mid-task.",
                     "Use before committing to a shared repo.",
                     "Reads the doc when the user asks for a summary."):
            self.assertRegex(desc, coverage.TRIGGER_RE)
        self.assertNotRegex("Cut AI tells from any writing.", coverage.TRIGGER_RE)


# --- tailor -----------------------------------------------------------------

def fake_env(os_name="linux", have=("python", "git")):
    e = envmod.Environment(os=os_name, shell="bash", home=Path.home())
    for t in envmod.INTERPRETERS:
        e.interpreters[t] = f"/bin/{t}" if t in have else None
    for t in envmod.CLIS:
        e.clis[t] = f"/bin/{t}" if t in have else None
    return e


class TestTailor(TmpCase):
    def test_line_numbers_are_file_lines(self):
        """Tailor/test reported body-relative, off-by-one line numbers."""
        body = "intro\n\n```bash\npython3 run.py\n```\n"
        s = self.skill("demo", body)
        f = tailor.tailor_skill(s, fake_env())[0]
        expected = s.raw.split("\n").index("python3 run.py") + 1
        self.assertEqual([expected], [x.line for x in f if x.rule == "T002"])
        self.assertEqual([(expected, "python3 run.py")],
                         tailor._commands(s.body, s.body_offset))

    def test_multi_root_probe_is_info_without_rewrite(self):
        """A find-my-script loop over several install roots was 'fixed' to a
        list of identical `$HOME/scripts/x.py` paths."""
        body = ('```bash\nfor p in "$HOME/.agents/skills/demo/scripts/x.py" '
                '"$HOME/.claude/skills/demo/scripts/x.py"; do :; done\n```\n')
        f, fx = tailor.tailor_skill(self.skill("demo", body), fake_env())
        self.assertEqual(["info"], [x.severity for x in f if x.rule == "T001"])
        self.assertEqual([], fx)

    def test_self_path_rewrite_takes_the_root_prefix(self):
        body = ("Run `~/.claude/skills/demo/scripts/a.py` then "
                "`~/.claude/skills/demo/scripts/b.py`.\n")
        f, fx = tailor.tailor_skill(self.skill("demo", body), fake_env())
        self.assertEqual(1, len(fx))  # one replace_all fix, not one per hit
        self.assertEqual(("~/.claude/skills/demo/", ""), (fx[0].find, fx[0].replace))
        self.assertIn("2 occurrences", [x for x in f if x.rule == "T001"][0].message)

    def test_other_skill_path_is_retargeted_not_stripped(self):
        """Stripping `.claude/skills/other/` left a path into the CURRENT
        skill's dir; the fix must retarget the other skill's root."""
        body = "Uses `.claude/skills/other/scripts/a.py`.\n"
        s = self.skill(".agents/skills/demo", body, name="demo")
        _, fx = tailor.tailor_skill(s, fake_env())
        self.assertEqual([(".claude/skills/other/", ".agents/skills/other/")],
                         [(x.find, x.replace) for x in fx])
        self.assertEqual("review", fx[0].confidence)

    def test_skill_dir_var_collapsed(self):
        body = "".join(f"use $SKILL_DIR/x{i}\n" for i in range(5))
        f, _ = tailor.tailor_skill(self.skill("demo", body), fake_env())
        t004 = [x for x in f if x.rule == "T004"]
        self.assertEqual(1, len(t004))
        self.assertIn("5 occurrences", t004[0].message)

    def test_python3_alt_is_py_on_windows(self):
        s = self.skill("demo", "```\npython3 a.py\n```\n")
        _, fx = tailor.tailor_skill(s, fake_env("windows", have=("py",)))
        self.assertEqual(["py "], [x.replace for x in fx])

    def test_posix_tool_on_path_not_flagged(self):
        """Git Bash supplies chmod & co.; T003 claimed they were missing."""
        s = self.skill("demo", "```bash\nchmod +x run.sh\n```\n")
        with mock.patch("surgeon.tailor.shutil.which", return_value="/usr/bin/chmod"):
            f, _ = tailor.tailor_skill(s, fake_env("windows"))
        self.assertEqual([], [x for x in f if x.rule == "T003"])
        with mock.patch("surgeon.tailor.shutil.which", return_value=None):
            f, _ = tailor.tailor_skill(s, fake_env("windows"))
        self.assertEqual(1, len([x for x in f if x.rule == "T003"]))


class TestEnvShell(unittest.TestCase):
    def test_git_bash_detected_via_msystem(self):
        """PSModulePath exists on every Windows box, so Git Bash was always
        reported as powershell."""
        environ = {k: v for k, v in os.environ.items() if k != "SHELL"}
        environ.update(MSYSTEM="MINGW64", PSModulePath="x")
        with mock.patch.dict(os.environ, environ, clear=True):
            self.assertEqual("bash", envmod.detect().shell)


# --- smoke test ---------------------------------------------------------------

class TestSmoke(TmpCase):
    def test_invoked_files_only_the_executed_script(self):
        cases = {
            "python -m unittest discover -s tests -p test_x.py": [],
            "python demo.py  # includes test_public_copy.py": ["demo.py"],
            'python -c "import x"': [],
            "py -3.12 tools/run.py --flag data.json": ["tools/run.py"],
            "powershell -ExecutionPolicy Bypass -File scripts/a.ps1": ["scripts/a.ps1"],
            "npm test path/to/test.test.ts": [],
            "./run.sh arg.py": ["run.sh"],
        }
        for cmd, want in cases.items():
            self.assertEqual(want, smoke._invoked_files(cmd), cmd)

    def test_placeholders_and_ancestor_resolution(self):
        body = ("```bash\n"
                "python <skill-path>/scripts/ok.py\n"
                "python $SKILL_DIR/scripts/ok.py --x\n"
                "python tools/export.py list\n"
                "python <repo>/thing.py\n"
                "python scripts/missing.py\n"
                "```\n")
        s = load_skill(write_skill(self.root / "lib", "demo", body),
                       self.root / "lib")
        (s.dir / "scripts").mkdir()
        (s.dir / "scripts" / "ok.py").write_text("x = 1\n", encoding="utf-8")
        (self.root / "tools").mkdir()   # repo root = one above the scan root
        (self.root / "tools" / "export.py").write_text("", encoding="utf-8")
        e = fake_env(have=("python",))
        rep = smoke.smoke_test([s], e, run=False)
        status = [r.status for r in rep.results]
        self.assertEqual(["ok", "ok", "ok", "unverified", "missing_file"], status)
        first = s.raw.split("\n").index("python <skill-path>/scripts/ok.py") + 1
        self.assertEqual(first, rep.results[0].line)

    def test_cli_handles_unverified_status(self):
        s = write_skill(self.root, "demo", "```\npython <repo>/x.py\n```\n")
        buf = io.StringIO()
        with redirect_stdout(buf), mock.patch(
                "surgeon.cli.detect", return_value=fake_env(have=("python",))):
            rc = cli.main(["test", str(s.parent)])
        self.assertIn("UNVER", buf.getvalue())
        self.assertIn(rc, (0, 1))


# --- watch / adopt / baseline / cli ---------------------------------------------

@unittest.skipUnless(shutil.which("git"), "git required")
class TestGitBacked(TmpCase):
    def git(self, *a, cwd):
        subprocess.run(["git", *a], cwd=cwd, check=True, capture_output=True,
                       env={**os.environ, "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@e",
                            "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@e"})

    def test_watch_dedupes_and_matches_paths(self):
        """Each commit's file list was concatenated, so a ref changed in four
        commits was listed four times; a bare `README.md` ref also matched
        docs/x/README.md only because basenames were compared for path refs."""
        ws = self.root / "ws"
        (ws / "docs").mkdir(parents=True)
        self.git("init", "-q", cwd=ws)
        for i in range(3):
            (ws / "data.json").write_text(str(i), encoding="utf-8")
            (ws / "docs" / "notes.md").write_text(str(i), encoding="utf-8")
            self.git("add", "-A", cwd=ws)
            self.git("commit", "-q", "-m", f"c{i}", cwd=ws)
        from surgeon.watch import watch_skill
        s = self.skill("ops", "Reads `data.json` and `other/notes.md`.\n",
                       extra=f"metadata:\n  workspace: {ws.as_posix()}\n"
                             "  verified_at: 2000-01-01\n")
        res = watch_skill(s)[0]
        self.assertEqual("drifted", res.status)
        self.assertEqual(["data.json"], res.changed_refs)
        self.assertEqual(2, res.commits)

    def test_detect_workspace_ignores_the_skills_own_repo(self):
        """adopt --detect declared the skills library itself as every
        skill's workspace, because bundled refs resolve inside it."""
        lib = self.root / "lib"
        s = self.skill("lib/caps/demo", "See `references/guide.md`.\n")
        (s.dir / "references").mkdir()
        (s.dir / "references" / "guide.md").write_text("", encoding="utf-8")
        self.git("init", "-q", cwd=lib)
        s = load_skill(s.path, lib / "caps")
        self.assertEqual("", detect_workspace(s))


class TestBaselineAndCli(TmpCase):
    def test_size_findings_survive_small_edits(self):
        a = Finding("S006", "warn", "s", Path("x"), "~5791 tokens / 201 body lines")
        b = Finding("S006", "warn", "s", Path("x"), "~5793 tokens / 201 body lines")
        self.assertEqual(baseline._signature(a), baseline._signature(b))

    def test_scan_json_report_is_a_usable_baseline(self):
        p = write_skill(self.root, "demo", "See `references/gone.md`.\n")
        out = self.root / "r.json"
        with redirect_stdout(io.StringIO()):
            cli.main(["scan", str(p.parent), "--no-semantic", "--json", str(out),
                      "--plan", str(self.root / "plan.json")])
            rc = cli.main(["diff", str(out), str(p.parent)])
        self.assertEqual(0, rc)

    def test_bad_baseline_is_usage_error(self):
        p = write_skill(self.root, "demo")
        bad = self.root / "bad.json"
        bad.write_text("[1, 2]", encoding="utf-8")
        with redirect_stdout(io.StringIO()):
            self.assertEqual(3, cli.main(["diff", str(bad), str(p.parent)]))
            self.assertEqual(3, cli.main(["diff", str(self.root / "none.json"),
                                          str(p.parent)]))

    def test_global_model_flag_not_overwritten_by_subcommand(self):
        a = cli.build_parser().parse_args(["--model", "m1", "doctor"])
        self.assertEqual("m1", a.model)
        a = cli.build_parser().parse_args(["--model", "m1", "diff", "b.json"])
        self.assertEqual("m1", a.model)

    def test_apply_reports_held_and_unknown_ids_and_honours_log(self):
        p = write_skill(self.root, "demo", "x\n")
        plan = self.root / "plan.json"
        plan.write_text(json.dumps({"fixes": [Fix(
            id="F-001", skill="demo", rule="S009", kind="manual", file=str(p),
            rationale="merge", auto=False).to_dict()]}), encoding="utf-8")
        log = self.root / "out" / "log.md"
        log.parent.mkdir()
        buf = io.StringIO()
        with redirect_stdout(buf):
            rc = cli.main(["apply", "--plan", str(plan), "--ids", "F-001,F-404",
                           "--log", str(log)])
        self.assertEqual(3, rc)
        self.assertIn("F-001 not applied", buf.getvalue())
        self.assertIn("F-404", buf.getvalue())
        self.assertTrue(log.is_file())


# --- implicit state machines (audit: IMPLICIT-STATE-MACHINES.md) --------------

class TestCmdResultStatus(TmpCase):
    """CmdResult.status was a free-form str: a typo'd or unlisted status
    rendered '?'/'info', dodged the hand-maintained "broken" tuple and
    `surgeon test` exited 0 - a green CI on a broken skill."""

    def test_unknown_status_rejected_at_construction(self):
        for bad in ("missing_inter", "okish", "", "OK", None):
            with self.assertRaises(ValueError, msg=repr(bad)):
                smoke.CmdResult("s", 1, "cmd", bad)

    def test_all_declared_statuses_construct(self):
        self.assertEqual(
            {"ok", "missing_file", "missing_interp", "syntax_fail",
             "crashed", "unsafe_skipped", "timeout", "unverified"},
            set(smoke.CMD_STATUSES))
        for st in smoke.CMD_STATUSES:
            self.assertEqual(st, smoke.CmdResult("s", 1, "cmd", st).status)

    def test_unknown_status_exits_non_green(self):
        """A status that dodges construction (post-hoc mutation, a foreign
        SmokeReport) must fail the CI gate, not render '?' and exit 0."""
        p = write_skill(self.root, "demo", "```\necho hi\n```\n")
        r = smoke.CmdResult("demo", 1, "echo hi", "ok")
        r.status = "bogus-status"            # bypass the constructor gate
        rep = smoke.SmokeReport(results=[r])
        buf = io.StringIO()
        with redirect_stdout(buf), \
                mock.patch("surgeon.cli.detect", return_value=fake_env()), \
                mock.patch("surgeon.cli.smoke_test", return_value=rep):
            rc = cli.main(["test", str(p.parent)])
        self.assertEqual(1, rc)
        self.assertIn("?", buf.getvalue())

    def test_known_outcomes_keep_their_gate_verdicts(self):
        """ok/timeout/unsafe_skipped/unverified stay green; the four broken
        states still exit 1 - same verdicts as the old 'bad' tuple."""
        p = write_skill(self.root, "demo", "```\necho hi\n```\n")
        for st, want in (("ok", 0), ("timeout", 0), ("unsafe_skipped", 0),
                         ("unverified", 0), ("missing_file", 1),
                         ("missing_interp", 1), ("syntax_fail", 1),
                         ("crashed", 1)):
            rep = smoke.SmokeReport(
                results=[smoke.CmdResult("demo", 1, "echo hi", st)])
            with redirect_stdout(io.StringIO()), \
                    mock.patch("surgeon.cli.detect", return_value=fake_env()), \
                    mock.patch("surgeon.cli.smoke_test", return_value=rep):
                rc = cli.main(["test", str(p.parent)])
            self.assertEqual(want, rc, st)


class TestFindingSeverity(TmpCase):
    """Finding.severity was a free-form str: 'errors' crashed the terminal
    render via sev_order[x.severity] yet cost 0 penalty in the score
    (_SEV_PENALTY.get(..., 0)) - one bad datum, opposite failure modes."""

    def _foreign_finding(self, sev):
        f = Finding("X000", "error", "s", Path("x.md"), "m")
        f.severity = sev                     # bypass the constructor gate
        return f

    def test_unknown_severity_rejected_at_construction(self):
        for bad in ("errors", "warning", "", "WARN"):
            with self.assertRaises(ValueError, msg=repr(bad)):
                Finding("X000", bad, "s", Path("x.md"), "m")

    def test_declared_severities_construct(self):
        for sev in ("error", "warn", "info"):
            self.assertEqual(
                sev, Finding("X000", sev, "s", Path("x.md"), "m").severity)

    def test_score_does_not_inflate_on_foreign_severity(self):
        """An unknown severity must fail loudly, not subtract 0 penalty."""
        rep = Report(skills=[mock.Mock(slug="s")],
                     findings=[self._foreign_finding("bogus")])
        with self.assertRaises(KeyError):
            rep.score()

    def test_counts_fail_loudly_on_foreign_severity(self):
        rep = Report(findings=[self._foreign_finding("bogus")])
        with self.assertRaises(KeyError):
            rep.counts()

    def test_terminal_render_fails_loudly_on_foreign_severity(self):
        rep = Report(findings=[self._foreign_finding("bogus")])
        with self.assertRaises(KeyError):
            render_terminal(rep, [])

    def test_baseline_entries_with_unknown_severity_still_diff(self):
        """Baselines and `scan --json` files are parsed input: a stale or
        odd severity there must not break `surgeon diff` (severity never
        fed the finding signature anyway)."""
        old = {"surgeon_baseline": 1, "saved": "x", "score": 90, "skills": 1,
               "findings": [{"rule": "S007", "severity": "bogus",
                             "skill": "s", "message": "dead ref `a.md`"},
                            {"rule": "S008", "skill": "s",
                             "message": "no severity key at all"}]}
        p = self.root / "b.json"
        p.write_text(json.dumps(old), encoding="utf-8")
        d = baseline.diff_baseline(p, Report())
        self.assertEqual(2, len(d["resolved"]))
        self.assertEqual("bogus", d["resolved"][0]["severity"])


if __name__ == "__main__":
    unittest.main()
