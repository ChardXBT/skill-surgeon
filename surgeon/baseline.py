"""surgeon diff - compare the library's health against a saved baseline.

`scan --save-baseline FILE` snapshots findings; `surgeon diff FILE` re-scans
and reports what's new, what's resolved, and the score delta. This is the
decay story as a number: libraries don't stay fixed, and diff is how you
see which direction yours is moving.
"""

from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path

from .model import Finding, Report


def _signature(f: Finding) -> str:
    """Stable identity for a finding across scans.

    Line numbers and volatile path prefixes are stripped so cosmetic file
    edits don't fake 'resolved'/'new' churn.
    """
    msg = re.sub(r"`[^`]+`", "`X`", f.message)          # mask file paths
    msg = re.sub(r"\b\d+\b", "N", msg)                  # mask counts/numbers
    msg = re.sub(r"line \d+", "line", msg)
    return f"{f.rule}|{f.skill}|{msg[:80]}"


def save_baseline(path: Path, report: Report) -> None:
    path.write_text(json.dumps({
        "surgeon_baseline": 1,
        "saved": datetime.now(timezone.utc).isoformat(),
        "score": report.score(),
        "skills": len(report.skills),
        "findings": [
            {"sig": _signature(f), "rule": f.rule, "severity": f.severity,
             "skill": f.skill, "message": f.message}
            for f in report.findings
        ],
    }, indent=2), encoding="utf-8")


def diff_baseline(baseline_path: Path, report: Report) -> dict:
    """Return {new, resolved, unchanged, score_then, score_now}."""
    try:
        old = json.loads(baseline_path.read_text(encoding="utf-8"))
    except Exception as e:
        raise SystemExit(f"cannot read baseline {baseline_path}: {e}")
    old_find = old.get("findings", [])
    old_sig = {d["sig"]: d for d in old_find}
    now_sig = {_signature(f): f for f in report.findings}

    new = [f for sig, f in now_sig.items() if sig not in old_sig]
    resolved = [d for sig, d in old_sig.items() if sig not in now_sig]
    return {
        "new": new,
        "resolved": resolved,
        "unchanged": len(set(now_sig) & set(old_sig)),
        "score_then": old.get("score"),
        "score_now": report.score(),
        "saved": old.get("saved", "?"),
    }
