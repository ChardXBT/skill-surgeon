"""skill-surgeon CLI: scan -> propose -> approve -> apply -> verify."""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

from . import __version__
from .discover import discover
from .fixes import fixes_for_findings, fixes_for_semantic
from .model import Fix, Report
from .report import apply_fix, render_markdown, render_plan_md, render_terminal, c
from .rules_structural import RULES, all_structural
from .semantic import DEFAULT_HOST, DEFAULT_MODEL, OllamaClient, analyze


def run_scan(paths: list[str], model: str, host: str,
             no_semantic: bool, want_fixes: bool):
    skills, roots = discover(paths)
    report = Report(skills=skills)
    report.findings = all_structural(skills)

    client = None
    analysis: dict = {}
    if not no_semantic and skills:
        client = OllamaClient(model=model, host=host)
        ok, note = client.available()
        report.semantic_ok, report.semantic_note = ok, note
        if ok:
            analysis = analyze(client, skills) or {}
            sem_fixes, sem_findings = fixes_for_semantic(skills, analysis, 0)
            report.findings.extend(sem_findings)
            report.collisions = analysis.get("collisions", [])
            report.desc_quality = analysis.get("descriptions", [])
        else:
            report.semantic_note = note

    fixes: list[Fix] = []
    if want_fixes:
        fixes = fixes_for_findings(skills, report.findings, client)
        if report.semantic_ok and analysis:
            sem_fixes, _ = fixes_for_semantic(skills, analysis, len(fixes))
            # keep only the fix objects (findings already merged above)
            fixes.extend(sem_fixes)
    return report, fixes, roots


def _renumber(fixes: list[Fix]) -> None:
    for i, fx in enumerate(fixes, 1):
        fx.id = f"F-{i:03d}"


def cmd_scan(args) -> int:
    report, fixes, roots = run_scan(args.paths, args.model, args.host,
                                    args.no_semantic, want_fixes=True)
    if not report.skills:
        print("No SKILL.md files found. Pass a skills dir, e.g. `surgeon scan ~/.agents/skills`")
        return 3
    _renumber(fixes)
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
    return 1 if any(f.severity == "error" for f in report.findings) else 0


def _apply_list(fixes: list[Fix], log_lines: list[str]) -> tuple[int, int]:
    applied = failed = 0
    for fx in fixes:
        ok, msg = apply_fix(fx)
        fx.status = "applied" if ok else "failed"
        applied += ok
        failed += not ok
        log_lines.append(f"- {fx.id} **{fx.skill}** ({fx.rule}) - "
                         f"{'applied' if ok else 'FAILED: ' + msg} - {fx.rationale}")
    return applied, failed


def cmd_fix(args) -> int:
    report, fixes, roots = run_scan(args.paths, args.model, args.host,
                                    args.no_semantic, want_fixes=True)
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

    for fx in auto:
        print(f"\n{fx.id} · {fx.skill} · {fx.rule} - {fx.rationale}")
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
            n, _ = _apply_list(auto[auto.index(fx):], log)
            applied += n
            break
        if ans in ("y", "yes"):
            n, _ = _apply_list([fx], log)
            applied += n
            print(c("    applied", "ok"))
        else:
            fx.status = "skipped"
            log.append(f"- {fx.id} **{fx.skill}** ({fx.rule}) - skipped")

    if manual:
        print(f"\n{len(manual)} findings need manual review (written to plan file):")
        for fx in manual:
            print(f"  - {fx.id} {fx.skill}: {fx.rationale[:140]}")
            log.append(f"- {fx.id} **{fx.skill}** ({fx.rule}) - manual: {fx.rationale}")

    Path("surgery-log.md").write_text("\n".join(log) + "\n", encoding="utf-8")
    print(c(f"\n{applied} fix(es) applied · surgery-log.md written", "bold"))

    if applied:
        print(c("re-scanning to verify...", "dim"))
        report2, _, roots2 = run_scan(args.paths, args.model, args.host, True, False)
        print(f"  score {report.score()}/100 -> {report2.score()}/100 "
              f"({report2.counts()} findings now)")
    return 0


def cmd_apply(args) -> int:
    """Non-interactive apply of a plan file (agent path)."""
    try:
        plan = json.loads(Path(args.plan).read_text(encoding="utf-8"))
    except Exception as e:
        print(f"cannot read plan {args.plan}: {e}")
        return 3
    fixes = [Fix.from_dict(d) for d in plan.get("fixes", [])]
    ids = set()
    if args.ids:
        ids = {x.strip() for x in args.ids.split(",") if x.strip()}
    chosen = [f for f in fixes
              if (args.all or f.id in ids) and f.kind == "replace_text" and f.auto]
    skipped = [f for f in fixes if f not in chosen]
    log = [f"# Surgery log - {datetime.now().isoformat(timespec='seconds')}", ""]
    applied, failed = _apply_list(chosen, log)
    for f in skipped:
        log.append(f"- {f.id} **{f.skill}** ({f.rule}) - skipped")
    Path("surgery-log.md").write_text("\n".join(log) + "\n", encoding="utf-8")
    print(f"{applied} applied, {failed} failed, {len(skipped)} skipped → surgery-log.md")
    return 0 if failed == 0 else 1


def cmd_rules(_args) -> int:
    for rid, (sev, desc) in RULES.items():
        print(f"  {rid}  {sev:<6} {desc}")
    return 0


def main(argv=None) -> int:
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass
    p = argparse.ArgumentParser(prog="surgeon",
                                description="Audit agent skills, propose fixes, "
                                            "apply them after operator approval.")
    p.add_argument("--version", action="version", version=f"skill-surgeon {__version__}")
    p.add_argument("--model", default=DEFAULT_MODEL)
    p.add_argument("--host", default=DEFAULT_HOST)
    sub = p.add_subparsers(dest="cmd", required=True)

    def add_common(sp):
        sp.add_argument("paths", nargs="*", default=[],
                        help="skills roots / skill dirs / SKILL.md files (default: auto-discover)")
        sp.add_argument("--no-semantic", action="store_true",
                        help="skip the open-weight model pass (structural only)")

    sp = sub.add_parser("scan", help="audit skills and write a fix plan")
    add_common(sp)
    sp.add_argument("--plan", default="surgery-plan.json")
    sp.add_argument("--md", default="")
    sp.add_argument("--json", default="")
    sp.set_defaults(func=cmd_scan)

    sp = sub.add_parser("fix", help="scan then interactively approve & apply fixes")
    add_common(sp)
    sp.set_defaults(func=cmd_fix)

    sp = sub.add_parser("apply", help="apply chosen fixes from a plan file")
    sp.add_argument("--plan", default="surgery-plan.json")
    sp.add_argument("--ids", default="", help="comma-separated fix ids")
    sp.add_argument("--all", action="store_true")
    sp.set_defaults(func=cmd_apply)

    sp = sub.add_parser("rules", help="list all rules")
    sp.set_defaults(func=cmd_rules)

    args = p.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
