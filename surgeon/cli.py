"""skill-surgeon CLI: scan -> propose -> approve -> apply -> verify."""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

from . import __version__
from .adopt import adopt_all
from .baseline import diff_baseline, save_baseline
from .coverage import coverage
from .discover import discover
from .env import describe as env_describe, detect
from .fixes import fixes_for_findings, fixes_for_semantic
from .model import Fix, Report
from .report import apply_fix, render_markdown, render_terminal, c
from .rules_structural import RULES, all_structural
from .semantic import DEFAULT_HOST, DEFAULT_MODEL, OllamaClient, analyze
from .smoke import CMD_STATUSES_BROKEN, CMD_STATUSES_PASS, smoke_test
from .tailor import T_RULES, tailor_all
from .watch import watch_all


def _discover(args):
    """discover() with the CLI's vendored-dir policy; returns skipped too."""
    skipped: list[Path] = []
    skills, roots = discover(args.paths,
                             include_vendored=getattr(args, "include_vendored", False),
                             skipped=skipped)
    return skills, roots, skipped


def _vendored_note(skipped: list[Path]) -> None:
    if skipped:
        print(c(f"  skipped {len(skipped)} vendored SKILL.md under vendor/ dirs "
                "(upstream reference copies; --include-vendored scans them)", "dim"))


def run_scan(paths: list[str], model: str, host: str,
             no_semantic: bool, want_fixes: bool,
             include_vendored: bool = False):
    skipped: list[Path] = []
    skills, roots = discover(paths, include_vendored=include_vendored,
                             skipped=skipped)
    report = Report(skills=skills, skipped_vendored=skipped)
    report.findings = all_structural(skills)

    client = None
    analysis: dict = {}
    if no_semantic:
        report.semantic_note = "disabled (--no-semantic)"
    elif skills:
        client = OllamaClient(model=model, host=host)
        ok, note = client.available()
        report.semantic_ok, report.semantic_note = ok, note
        if ok:
            analysis = analyze(client, skills) or {}
            sem_fixes, sem_findings = fixes_for_semantic(skills, analysis)
            report.findings.extend(sem_findings)
            report.collisions = analysis.get("collisions", [])
            report.desc_quality = analysis.get("descriptions", [])
        else:
            report.semantic_note = note

    fixes: list[Fix] = []
    if want_fixes:
        # a known-dead client would make drafting hang for its full timeout
        fixes = fixes_for_findings(
            skills, report.findings, client if report.semantic_ok else None)
        if report.semantic_ok and analysis:
            sem_fixes, _ = fixes_for_semantic(skills, analysis)
            # keep only the fix objects (findings already merged above)
            fixes.extend(sem_fixes)
    return report, fixes, roots


def _renumber(fixes: list[Fix]) -> None:
    for i, fx in enumerate(fixes, 1):
        fx.id = f"F-{i:03d}"


def cmd_scan(args) -> int:
    report, fixes, roots = run_scan(args.paths, args.model, args.host,
                                    args.no_semantic, want_fixes=True,
                                    include_vendored=args.include_vendored)
    if not report.skills:
        print("No SKILL.md files found. Pass a skills dir, e.g. `surgeon scan ~/.agents/skills`")
        return 3
    _renumber(fixes)
    if args.ci:
        counts = report.counts()
        print(f"skill-surgeon: score={report.score()}/100 errors={counts['error']} "
              f"warnings={counts['warn']} skills={len(report.skills)}")
    else:
        print(render_terminal(report, roots))

    plan_path = Path(args.plan)
    plan_path.write_text(json.dumps(
        {"generated": datetime.now(timezone.utc).isoformat(), "fixes": [f.to_dict() for f in fixes]},
        indent=2), encoding="utf-8")
    if fixes:
        print(c(f"  {len(fixes)} proposed fixes written to {plan_path}", "dim"))
        print(c("  review: `surgeon fix` (interactive) or `surgeon apply --ids F-001,F-002`", "dim"))
    if args.md:
        Path(args.md).write_text(render_markdown(report, roots), encoding="utf-8")
        print(c(f"  markdown report: {args.md}", "dim"))
    if args.json:
        Path(args.json).write_text(json.dumps({
            "score": report.score(), "counts": report.counts(),
            "findings": [{"rule": f.rule, "severity": f.severity, "skill": f.skill,
                          "message": f.message, "file": str(f.file), "line": f.line}
                         for f in report.findings],
        }, indent=2), encoding="utf-8")
    if getattr(args, "save_baseline", ""):
        # diff re-scans structurally only - snapshot only structural findings
        # or every semantic finding reads as "resolved" next run
        base = Report(skills=report.skills,
                      findings=[f for f in report.findings
                                if not f.rule.startswith("Q")],
                      collisions=report.collisions)
        save_baseline(Path(args.save_baseline), base)
        print(c(f"  baseline saved: {args.save_baseline} "
                "(compare later with `surgeon diff`)", "dim"))
    has_errors = any(f.severity == "error" for f in report.findings)
    if getattr(args, "adopt_on_clean", False):
        if has_errors:
            print(c("  adopt skipped - errors present; fix first, "
                    "then adopt the clean scan", "dim"))
        else:
            n = sum(1 for ad in adopt_all(report.skills, None, yes=True)
                    if ad.applied)
            print(c(f"  adopt: stamped verified_at on {n} skills - "
                    "`surgeon watch` now measures drift from today", "ok"))
    return 1 if has_errors else 0


def _apply_list(fixes: list[Fix], log_lines: list[str]) -> tuple[int, int]:
    applied = failed = 0
    for fx in fixes:
        ok, msg = apply_fix(fx)
        fx.status = "applied" if ok else "failed"
        applied += ok
        failed += not ok
        if not ok:
            print(c(f"    FAILED {fx.id}: {msg}", "error"))
        log_lines.append(f"- {fx.id} **{fx.skill}** ({fx.rule}) - "
                         f"{'applied' if ok else 'FAILED: ' + msg} - {fx.rationale}")
    return applied, failed


def cmd_fix(args) -> int:
    report, fixes, roots = run_scan(args.paths, args.model, args.host,
                                    args.no_semantic, want_fixes=True,
                                    include_vendored=args.include_vendored)
    if not report.skills:
        print("No SKILL.md files found.")
        return 3
    _renumber(fixes)
    print(render_terminal(report, roots))
    if not fixes:
        print("Nothing fixable found.")
        return 0

    auto = [f for f in fixes if f.auto and f.kind == "replace_text"]
    manual = [f for f in fixes if f not in auto]
    log = [f"# Surgery log - {datetime.now().isoformat(timespec='seconds')}", ""]
    applied = 0

    for i, fx in enumerate(auto):
        conf = c(" [review: guessed target]", "warn") if fx.confidence == "review" else ""
        print(f"\n{fx.id} · {fx.skill} · {fx.rule}{conf} - {fx.rationale}")
        for l in fx.find.split("\n"):
            print(c("  - " + l, "error"))
        for l in fx.replace.split("\n"):
            print(c("  + " + l, "ok"))
        try:
            ans = input("  apply? [y]es/[s]kip/[a]ll/[q]uit: ").strip().lower()
        except EOFError:
            ans = "s"
        if ans == "q":
            break
        if ans == "a":
            n, _ = _apply_list(auto[i:], log)
            applied += n
            break
        if ans in ("y", "yes"):
            n, f_ = _apply_list([fx], log)
            applied += n
            if not f_:
                print(c("    applied", "ok"))
        else:
            fx.status = "skipped"
            log.append(f"- {fx.id} **{fx.skill}** ({fx.rule}) - skipped")

    if manual:
        print(f"\n{len(manual)} findings need manual review (logged to surgery-log.md):")
        for fx in manual:
            print(f"  - {fx.id} {fx.skill}: {fx.rationale[:140]}")
            log.append(f"- {fx.id} **{fx.skill}** ({fx.rule}) - manual: {fx.rationale}")

    Path(args.log).write_text("\n".join(log) + "\n", encoding="utf-8")
    print(c(f"\n{applied} fix(es) applied · {args.log} written", "bold"))

    if applied:
        print(c("re-scanning to verify...", "dim"))
        report2, _, roots2 = run_scan(args.paths, args.model, args.host, True, False,
                                      include_vendored=args.include_vendored)
        cnt = report2.counts()
        print(f"  score {report.score()}/100 -> {report2.score()}/100 "
              f"({cnt['error']} errors, {cnt['warn']} warnings now)")
    return 0


def cmd_apply(args) -> int:
    """Non-interactive apply of a plan file (agent path)."""
    try:
        plan = json.loads(Path(args.plan).read_text(encoding="utf-8"))
    except Exception as e:
        print(f"cannot read plan {args.plan}: {e}")
        return 3
    fixes: list[Fix] = []
    for d in plan.get("fixes", []):
        try:
            fixes.append(Fix.from_dict(d))
        except (KeyError, TypeError, AttributeError) as e:
            print(c(f"  skipping malformed plan entry: {e}", "warn"))
    ids = set()
    if args.ids:
        ids = {x.strip() for x in args.ids.split(",") if x.strip()}
    if not ids and not args.all:
        print(f"no fixes selected - pass --ids F-001,F-002 or --all "
              f"({len(fixes)} pending in {args.plan})")
        return 3
    unknown = ids - {f.id for f in fixes}
    if unknown:
        print(c(f"  unknown fix id(s) ignored: {', '.join(sorted(unknown))}", "warn"))
    chosen = [f for f in fixes
              if (args.all or f.id in ids) and f.kind == "replace_text" and f.auto
              and (not args.safe_only or f.confidence == "safe")]
    skipped = [f for f in fixes if f not in chosen]
    # plans are agent-facing input: only ever write into SKILL.md files, so a
    # crafted plan can't turn `apply` into arbitrary file modification
    non_skill = [f for f in chosen
                 if Path(f.file).name.lower() != "skill.md"]
    for f in non_skill:
        chosen.remove(f)
        skipped.append(f)
        print(c(f"  {f.id}: skipped - target is not a SKILL.md ({f.file})", "warn"))
    log = [f"# Surgery log - {datetime.now().isoformat(timespec='seconds')}", ""]
    applied, failed = _apply_list(chosen, log)
    for f in skipped:
        reason = _skip_reason(f, args.safe_only)
        log.append(f"- {f.id} **{f.skill}** ({f.rule}) - skipped: {reason}")
        if f.id in ids:  # the operator asked for it - say why it was held
            print(f"  {f.id} not applied: {reason}")
    unknown = sorted(ids - {f.id for f in fixes})
    if unknown:
        print(f"  unknown fix id(s): {', '.join(unknown)}")
    log_path = Path(args.log)
    log_path.write_text("\n".join(log) + "\n", encoding="utf-8")
    print(f"{applied} applied, {failed} failed, {len(skipped)} skipped -> {log_path}")
    return 1 if failed else (3 if unknown else 0)


def _skip_reason(f: Fix, safe_only: bool) -> str:
    if f.kind != "replace_text":
        return f"{f.kind} fix - make this change by hand after review"
    if not f.auto:
        return "needs human judgement (guessed or ambiguous target) - edit by hand"
    if safe_only and f.confidence != "safe":
        return "review-confidence fix held by --safe-only"
    return "not selected"


def cmd_rules(_args) -> int:
    for rid, (sev, desc) in RULES.items():
        print(f"  {rid}  {sev:<6} {desc}")
    for rid, desc in T_RULES.items():
        print(f"  {rid}  tailor {desc}")
    return 0


def cmd_adopt(args) -> int:
    """Stamp metadata.workspace + verified_at so `watch` has a baseline."""
    skills, roots, skipped = _discover(args)
    if not skills:
        print("No SKILL.md files found.")
        return 3
    ws = str(Path(args.workspace).expanduser().resolve()) if args.workspace else None
    ads = adopt_all(skills, ws, yes=args.yes, detect=args.detect)
    mode = "applied" if args.yes else "plan (pass --yes to write)"
    print(f"\n  ADOPT - declare workspace + verification stamp [{mode}]")
    _vendored_note(skipped)
    print("")
    for ad in ads:
        if ad.error:
            print(f"  {c('!', 'error')} {ad.skill.ljust(28)[:28]} failed: {ad.error}")
        elif ad.updates:
            marks = ", ".join(f"{k}: {v}" for k, v in ad.updates.items())
            det = c(" (detected)", "dim") if ad.detected else ""
            print(f"  {c('+', 'ok')} {ad.skill.ljust(28)[:28]} {marks}{det}")
        else:
            print(f"  {c('=', 'dim')} {ad.skill.ljust(28)[:28]} already declared")
    if not args.yes:
        print(c("\n  nothing written - re-run with --yes to stamp "
                "verified_at (and --workspace to declare a repo)", "dim"))
    return 0


def cmd_diff(args) -> int:
    """Compare current health against a `scan --save-baseline` snapshot."""
    report, _, _ = run_scan(args.paths, args.model, args.host,
                            True, want_fixes=False,
                            include_vendored=args.include_vendored)
    if not report.skills:
        print("No SKILL.md files found.")
        return 3
    try:
        d = diff_baseline(Path(args.baseline), report)
    except SystemExit as e:  # unreadable/invalid baseline is a usage error
        print(e)
        return 3
    print(f"\n  DIFF - vs baseline saved {d['saved']}")
    print(f"  score {d['score_then']}/100 -> {d['score_now']}/100   "
          f"{d['unchanged']} unchanged   "
          f"{c(str(len(d['new'])) + ' new', 'error' if d['new'] else 'dim')}   "
          f"{c(str(len(d['resolved'])) + ' resolved', 'ok' if d['resolved'] else 'dim')}")
    for f in d["new"][:20]:
        print(f"    {c('+', 'error')} {f.rule} {f.skill}: {f.message[:90]}")
    for o in d["resolved"][:20]:
        print(f"    {c('-', 'ok')} {o['rule']} {o['skill']}: {o['message'][:90]}")
    return 1 if d["new"] else 0


def cmd_tailor(args) -> int:
    """Rewrite skill instructions to fit THIS environment (or a target platform)."""
    env = detect()
    skills, roots, skipped = _discover(args)
    if not skills:
        print("No SKILL.md files found.")
        return 3
    findings, fixes = tailor_all(skills, env, args.target)
    print(f"\n  TAILOR - environment fit")
    print(c(f"  {env_describe(env)}", "dim"))
    _vendored_note(skipped)
    if args.target:
        print(c(f"  target platform: .{args.target}/skills", "dim"))
    print("")
    for f in findings:
        print(f"  {c(f.severity.upper().ljust(5), f.severity)} {f.skill.ljust(28)[:28]} "
              f"{f.message}  {c(f.file.name + ':' + str(f.line), 'dim')}")
    if not findings:
        print(c("  every skill fits this environment", "ok"))
    _renumber(fixes)
    plan = Path(args.plan)
    plan.write_text(json.dumps(
        {"generated": datetime.now(timezone.utc).isoformat(),
         "fixes": [f.to_dict() for f in fixes]}, indent=2), encoding="utf-8")
    if fixes:
        print(c(f"\n  {len(fixes)} rewrites proposed -> {plan} "
                f"(apply with `surgeon apply --plan {plan} --ids ...`)", "dim"))
    return 1 if any(f.severity == "error" for f in findings) else 0


def cmd_test(args) -> int:
    """Smoke-test the commands each skill documents."""
    env = detect()
    skills, roots, skipped = _discover(args)
    if not skills:
        print("No SKILL.md files found.")
        return 3
    rep = smoke_test(skills, env, run=args.run)
    if args.json:
        Path(args.json).write_text(json.dumps({
            "run": bool(args.run), "counts": rep.counts(),
            "results": [{"skill": r.skill, "line": r.line, "command": r.command,
                         "status": r.status, "detail": r.detail}
                        for r in rep.results],
        }, indent=2), encoding="utf-8")
    mode = "live execution" if args.run else "static (pass --run to execute)"
    print(f"\n  SMOKE TEST - do the documented commands work? [{mode}]")
    print(c(f"  {env_describe(env)}", "dim"))
    _vendored_note(skipped)
    print("")
    last = None
    for r in rep.results:
        if r.skill != last:
            print(f"  {r.skill}")
            last = r.skill
        mark = {"ok": "ok", "missing_file": "error", "missing_interp": "error",
                "syntax_fail": "error", "crashed": "error", "timeout": "warn",
                "unsafe_skipped": "info", "unverified": "info"}.get(r.status, "info")
        tag = {"ok": "PASS", "missing_file": "DEAD", "missing_interp": "NOENV",
               "syntax_fail": "FAIL", "crashed": "CRASH", "timeout": "SLOW",
               "unsafe_skipped": "SKIP", "unverified": "UNVER"}.get(r.status, "?")
        print(f"    {c(tag.ljust(5), mark)} L{r.line:<5} {r.command[:70]}"
              + (f"  {c(r.detail, 'dim')}" if r.detail else ""))
    cnt = rep.counts()
    bad = sum(cnt.get(k, 0) for k in CMD_STATUSES_BROKEN)
    print(f"\n  {len(rep.results)} commands checked - "
          f"{c(str(cnt.get('ok',0)) + ' pass', 'ok')}   "
          f"{c(str(bad) + ' broken', 'error' if bad else 'dim')}   "
          f"{cnt.get('unsafe_skipped',0)} skipped (unsafe)   "
          f"{cnt.get('unverified',0)} unverified (placeholder paths)")
    # green only when every outcome is a declared pass state - a status the
    # vocabulary doesn't know (or one a foreign report smuggles past the
    # constructor) can never exit 0
    return 0 if all(r.status in CMD_STATUSES_PASS for r in rep.results) else 1


def cmd_watch(args) -> int:
    """Check whether skills' declared workspaces drifted since verification."""
    skills, roots, skipped = _discover(args)
    if not skills:
        print("No SKILL.md files found.")
        return 3
    results = watch_all(skills)
    if args.json:
        Path(args.json).write_text(json.dumps({
            "results": [{"skill": r.skill, "workspace": str(r.workspace),
                         "status": r.status, "detail": r.detail,
                         "changed_refs": r.changed_refs}
                        for r in results],
        }, indent=2), encoding="utf-8")
    print(f"\n  WATCH - workspace drift")
    _vendored_note(skipped)
    if not results:
        print(c("  no skills declare metadata.workspace - nothing to watch", "dim"))
        print("  declare one in frontmatter:  metadata: {workspace: ~/path/to/repo}")
        print(c("  or auto-stamp + auto-detect:  surgeon adopt <paths> --detect --yes", "dim"))
        return 0
    print("")
    for r in results:
        tag = {"fresh": "FRESH ", "drifted": "DRIFT ", "not_git": "NOGIT ",
               "missing": "GONE  ", "untracked": "UNK   "}[r.status]
        sev = {"fresh": "ok", "drifted": "warn", "not_git": "info",
               "missing": "error", "untracked": "info"}[r.status]
        print(f"  {c(tag, sev)} {r.skill.ljust(28)[:28]} {r.workspace.name.ljust(24)[:24]} {r.detail}")
    drifted = [r for r in results if r.status == "drifted" and r.changed_refs]
    if drifted:
        print(c(f"\n  {len(drifted)} skill(s) reference files that changed since "
                "verification - re-review those sections", "warn"))
    return 1 if any(r.status == "missing"
                    or (r.status == "drifted" and r.changed_refs)
                    for r in results) else 0


def cmd_coverage(args) -> int:
    """Map the library as a router sees it: triggers, overlaps, gaps."""
    skills, roots, skipped = _discover(args)
    if not skills:
        print("No SKILL.md files found.")
        return 3
    client = None
    if not args.no_semantic:
        client = OllamaClient(model=args.model, host=args.host)
        ok, _ = client.available()
        if not ok:
            client = None
    rep = coverage(skills, client)
    if args.json:
        Path(args.json).write_text(json.dumps({
            "skills": len(skills), "embed": rep.embed_note,
            "no_trigger": rep.no_trigger,
            "no_trigger_nested": rep.no_trigger_nested,
            "similar_pairs": [{"a": a, "b": b, "score": j}
                              for a, b, j in rep.similar_pairs],
            "uncovered": rep.uncovered,
        }, indent=2), encoding="utf-8")
    print(f"\n  COVERAGE - routing map for {len(skills)} skills")
    _vendored_note(skipped)
    print("")
    if rep.no_trigger:
        print(c("  no trigger phrasing (may never fire):", "warn"))
        for s in rep.no_trigger:
            print(f"    - {s}")
    if rep.no_trigger_nested:
        print(c("\n  nested sub-skills without trigger phrasing (routed by their "
                "parent skill; matters only where a host lists nested skills):",
                "info"))
        for s in rep.no_trigger_nested:
            print(f"    - {s}")
    if rep.similar_pairs:
        print(c("\n  description overlap (possible routing confusion):", "warn"))
        for a, b, j in sorted(rep.similar_pairs, key=lambda x: -x[2]):
            print(f"    - {a} vs {b}  ({j:.0%} token overlap)")
    if rep.uncovered:
        print(c(f"\n  uncovered intents (local model):", "info"))
        for u in rep.uncovered:
            print(f"    - {u}")
    elif rep.model_note != "off":
        print(c(f"  model gap analysis: {rep.model_note}", "dim"))
    if not rep.no_trigger and not rep.no_trigger_nested and not rep.similar_pairs:
        print(c("  every skill has trigger phrasing; no deterministic overlap", "ok"))
    return 0


def cmd_doctor(args) -> int:
    """Check surgeon's own runtime: python, Ollama, embed model, PATH."""
    import shutil
    checks = []
    v = sys.version_info
    checks.append((f"python {v.major}.{v.minor}.{v.micro}", v >= (3, 9),
                   "3.9+ required"))
    env = detect()
    py = env.python_cmd()
    checks.append((f"python interpreter on PATH ({py or 'none'})",
                   py is not None, "tailor/test need a working interpreter"))
    try:
        import yaml  # noqa
        checks.append(("pyyaml", True, ""))
    except Exception:
        checks.append(("pyyaml", False, "optional - lenient parser covers most files"))
    client = OllamaClient(model=args.model, host=args.host)
    ok, note = client.available()
    checks.append((f"ollama + {args.model}", ok, note if not ok else ""))
    if ok:
        try:
            import urllib.request, json as _j
            with urllib.request.urlopen(f"{args.host}/api/tags", timeout=4) as r:
                names = [m.get("name", "") for m in _j.loads(r.read()).get("models", [])]
            checks.append(("nomic-embed-text (semantic coverage)",
                           any("nomic-embed" in n for n in names),
                           "optional - coverage falls back to token overlap"))
        except Exception:
            pass
    checks.append(("`surgeon` on PATH", shutil.which("surgeon") is not None,
                   "optional - `python -m surgeon` always works"))
    print(f"\n  DOCTOR - skill-surgeon {__version__} self-check")
    print("")
    bad = 0
    for label, ok_, note in checks:
        mark = c("OK  ", "ok") if ok_ else c("MISS", "warn")
        if not ok_:
            bad += 1
        print(f"  {mark} {label}" + (f"  {c(note, 'dim')}" if note else ""))
    print("")
    return 0 if all(c[1] for c in checks[:2]) else 1


def cmd_badge(args) -> int:
    """Print a README badge line with the library's score."""
    report, fixes, roots = run_scan(args.paths, args.model, args.host,
                                    True, want_fixes=False,
                                    include_vendored=args.include_vendored)
    if not report.skills:
        print("No SKILL.md files found.")
        return 3
    score = report.score()
    color = ("brightgreen" if score >= 90 else "green" if score >= 75 else
             "yellow" if score >= 60 else "orange" if score >= 40 else "red")
    print(f"![skill-surgeon](https://img.shields.io/badge/"
          f"skill--surgeon-{score}%2F100-{color})")
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="surgeon",
                                description="Audit agent skills, propose fixes, "
                                            "apply them after operator approval.")
    p.add_argument("--version", action="version", version=f"skill-surgeon {__version__}")
    p.add_argument("--model", default=DEFAULT_MODEL)
    p.add_argument("--host", default=DEFAULT_HOST)
    sub = p.add_subparsers(dest="cmd", required=True)

    def add_paths(sp):
        sp.add_argument("paths", nargs="*", default=[],
                        help="skills roots / skill dirs / SKILL.md files (default: auto-discover)")
        sp.add_argument("--include-vendored", action="store_true",
                        help="also scan SKILL.md under vendor/ dirs (upstream "
                             "reference copies; skipped by default)")

    def add_common(sp):
        add_paths(sp)
        sp.add_argument("--no-semantic", action="store_true",
                        help="skip the open-weight model pass (structural only)")
        add_model(sp)

    def add_model(sp):
        # SUPPRESS: a subparser default would silently overwrite a global
        # `surgeon --model X <cmd>` value; only set it when given here.
        sp.add_argument("--model", default=argparse.SUPPRESS)
        sp.add_argument("--host", default=argparse.SUPPRESS)

    sp = sub.add_parser("scan", help="audit skills and write a fix plan")
    add_common(sp)
    sp.add_argument("--plan", default="surgery-plan.json")
    sp.add_argument("--md", default="")
    sp.add_argument("--json", default="")
    sp.add_argument("--ci", action="store_true",
                    help="one-line output for CI; exit 1 if errors")
    sp.add_argument("--save-baseline", default="",
                    help="snapshot findings to FILE for `surgeon diff`")
    sp.add_argument("--adopt-on-clean", action="store_true",
                    help="stamp metadata.verified_at on every skill when the scan is clean")
    sp.set_defaults(func=cmd_scan)

    sp = sub.add_parser("fix", help="scan then interactively approve & apply fixes")
    add_common(sp)
    sp.add_argument("--log", default="surgery-log.md", help="decision log FILE")
    sp.set_defaults(func=cmd_fix)

    sp = sub.add_parser("apply", help="apply chosen fixes from a plan file")
    sp.add_argument("--plan", default="surgery-plan.json")
    sp.add_argument("--ids", default="", help="comma-separated fix ids")
    sp.add_argument("--all", action="store_true")
    sp.add_argument("--safe-only", action="store_true",
                    help="apply only deterministic fixes; hold review-flagged ones")
    sp.add_argument("--log", default="surgery-log.md", help="decision log FILE")
    sp.set_defaults(func=cmd_apply)

    sp = sub.add_parser("rules", help="list all rules")
    sp.set_defaults(func=cmd_rules)

    sp = sub.add_parser("tailor", help="adapt skills to this environment (or --for a platform)")
    add_paths(sp)
    sp.add_argument("--for", dest="target", default=None,
                    choices=["claude", "agents", "devin", "codex", "cursor", "windsurf"],
                    help="target platform root name")
    sp.add_argument("--plan", default="tailor-plan.json")
    sp.set_defaults(func=cmd_tailor)

    sp = sub.add_parser("test", help="smoke-test documented commands")
    add_paths(sp)
    sp.add_argument("--run", action="store_true",
                    help="actually execute commands (denylisted ones are skipped, env scrubbed, temp-copy sandbox)")
    sp.add_argument("--json", default="", help="write results to FILE")
    sp.set_defaults(func=cmd_test)

    sp = sub.add_parser("watch", help="flag skills whose workspaces changed since verification")
    add_paths(sp)
    sp.add_argument("--json", default="", help="write results to FILE")
    sp.set_defaults(func=cmd_watch)

    sp = sub.add_parser("coverage", help="routing/intent map of the library")
    add_common(sp)
    sp.add_argument("--json", default="", help="write results to FILE")
    sp.set_defaults(func=cmd_coverage)

    sp = sub.add_parser("badge", help="print a README badge with the library score")
    add_common(sp)
    sp.set_defaults(func=cmd_badge)

    sp = sub.add_parser("adopt", help="stamp metadata.workspace + verified_at for watch")
    add_paths(sp)
    sp.add_argument("--workspace", default="",
                    help="repo path the skills monitor (single value applied to all)")
    sp.add_argument("--detect", action="store_true",
                    help="guess each skill's workspace from its referenced files' git roots")
    sp.add_argument("--yes", action="store_true",
                    help="write the stamps (default: plan only)")
    sp.set_defaults(func=cmd_adopt)

    sp = sub.add_parser("diff", help="compare health vs a saved baseline")
    sp.add_argument("baseline", help="file written by `scan --save-baseline`")
    add_paths(sp)
    add_model(sp)
    sp.set_defaults(func=cmd_diff)

    sp = sub.add_parser("doctor", help="check surgeon's own runtime prerequisites")
    add_model(sp)
    sp.set_defaults(func=cmd_doctor)
    return p


def main(argv=None) -> int:
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass
    args = build_parser().parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
