"""surgeon watch - decay monitoring for skills that describe live repos.

A skill rots when the world it documents moves on. For skills that declare
`metadata.workspace`, watch diffs each workspace's git history against the
skill's last verification (`metadata.verified_at`, else file mtime) and
reports which referenced files changed since - the skills most likely stale.
"""

from __future__ import annotations

import re
import subprocess
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from .model import Skill

GIT = "git"


@dataclass
class WatchResult:
    skill: str
    workspace: Path
    status: str        # fresh | drifted | untracked | not_git | missing
    changed_refs: list[str] = field(default_factory=list)
    commits: int = 0
    detail: str = ""


def _workspaces(skill: Skill) -> list[Path]:
    raw = skill.meta.get("workspace") or (skill.meta.get("metadata") or {}).get("workspace")
    ws = raw if isinstance(raw, list) else ([raw] if raw else [])
    return [Path(str(w)).expanduser() for w in ws]


def _verified_at(skill: Skill) -> datetime:
    raw = skill.meta.get("verified_at") or (skill.meta.get("metadata") or {}).get("verified_at")
    if raw:
        try:
            return datetime.fromisoformat(str(raw).replace("Z", "+00:00"))
        except ValueError:
            pass
    return datetime.fromtimestamp(skill.path.stat().st_mtime, tz=timezone.utc)


def _skill_refs(skill: Skill) -> set[str]:
    """Refs this skill mentions (same extraction as S007)."""
    from .rules_structural import _candidate_refs
    return {ref for ref, _line in _candidate_refs(skill)}


def _git(ws: Path, *args: str) -> tuple[int, str]:
    try:
        r = subprocess.run([GIT, "-C", str(ws), *args],
                           capture_output=True, text=True, timeout=30)
        return r.returncode, (r.stdout or "").strip()
    except Exception as e:
        return 1, str(e)


def watch_skill(skill: Skill) -> list[WatchResult]:
    out: list[WatchResult] = []
    verified = _verified_at(skill)
    refs = _skill_refs(skill)

    for ws in _workspaces(skill):
        res = WatchResult(skill=skill.slug, workspace=ws, status="fresh")
        if not ws.exists():
            res.status, res.detail = "missing", "declared workspace path does not exist"
            out.append(res)
            continue
        rc, _ = _git(ws, "rev-parse", "--git-dir")
        if rc != 0:
            res.status = "not_git"
            res.detail = "workspace is not a git repo; drift cannot be tracked"
            out.append(res)
            continue

        rc, changed = _git(
            ws, "log", f"--since={verified.isoformat()}",
            "--name-only", "--format=", "HEAD")
        if rc != 0:
            res.status, res.detail = "untracked", "git log failed"
            out.append(res)
            continue

        files = [l.strip() for l in changed.split("\n") if l.strip()]
        if not files:
            res.detail = f"no workspace commits since {verified.date()}"
            out.append(res)
            continue

        res.status = "drifted"
        res.commits = len(set(files))
        # strongest signal: files the skill actually references moved
        touched = [f for f in files
                   if f in refs or Path(f).name in {Path(r).name for r in refs}]
        res.changed_refs = touched
        res.detail = (f"{len(set(files))} files changed since verification "
                      f"({verified.date()})")
        if touched:
            res.detail += f" - referenced files changed: {', '.join(touched[:5])}"
        out.append(res)

    return out


def watch_all(skills: list[Skill]) -> list[WatchResult]:
    out: list[WatchResult] = []
    for s in skills:
        out.extend(watch_skill(s))
    return out
