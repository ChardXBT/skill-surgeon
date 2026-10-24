"""surgeon adopt - declare a skill's workspace + verification stamp.

`watch` only covers skills whose frontmatter declares what they monitor:

    metadata:
      workspace: C:/path/to/repo      (or a list of paths)
      verified_at: 2026-10-23         (last time a human/scan verified it)

adopt writes those two fields so a healthy scan today becomes the baseline
`watch` measures decay against tomorrow. Plan-first by default; --yes writes.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from pathlib import Path

import subprocess

from .frontmatter import rewrite_frontmatter
from .model import Skill


@dataclass
class Adoption:
    skill: str
    file: Path
    updates: dict[str, str] = field(default_factory=dict)
    already: list[str] = field(default_factory=list)   # keys already set
    detected: str = ""                                  # auto-guessed workspace
    applied: bool = False


def _git_root(path: Path) -> Path | None:
    try:
        r = subprocess.run(["git", "-C", str(path), "rev-parse", "--show-toplevel"],
                           capture_output=True, text=True, timeout=10)
        return Path(r.stdout.strip()) if r.returncode == 0 and r.stdout.strip() else None
    except Exception:
        return None


def detect_workspace(skill: Skill) -> str:
    """Guess the workspace repo by following this skill's referenced files.

    Resolves paths the skill body mentions against the skill dir and its
    ancestors; the git root containing the most resolved refs wins. Empty
    string when nothing resolves inside a repo.
    """
    from .rules_structural import _candidate_refs
    votes: dict[Path, int] = {}
    for ref, _line in _candidate_refs(skill):
        for base in (skill.dir, *skill.dir.parents):
            cand = (base / ref)
            if cand.exists():
                root = _git_root(cand.parent)
                if root and skill.root not in root.parents and root != skill.root:
                    votes[root] = votes.get(root, 0) + 1
                break
    return str(max(votes, key=votes.get)) if votes else ""


def plan_adoption(skill: Skill, workspace: str | None,
                  today: str | None = None,
                  detect: bool = False) -> Adoption:
    """Compute the metadata updates adopt would write (does not touch disk)."""
    today = today or date.today().isoformat()
    meta = skill.meta.get("metadata")
    meta = meta if isinstance(meta, dict) else {}

    ad = Adoption(skill=skill.slug, file=skill.path)
    ws = workspace or (detect_workspace(skill) if detect else "")
    if ws:
        ad.detected = "" if workspace else ws
        existing = meta.get("workspace")
        if existing != ws:
            ad.updates["workspace"] = ws
        else:
            ad.already.append("workspace")
    # verified_at is the action itself: always re-stamp to today
    ad.updates["verified_at"] = today
    return ad


def apply_adoption(ad: Adoption) -> bool:
    """Write the planned updates into the skill's frontmatter."""
    if not ad.updates:
        return False
    text = ad.file.read_text(encoding="utf-8")
    ad.file.write_text(rewrite_frontmatter(text, ad.updates),
                       encoding="utf-8")
    ad.applied = True
    return True


def adopt_all(skills: list[Skill], workspace: str | None,
              yes: bool, detect: bool = False) -> list[Adoption]:
    out = []
    for s in skills:
        ad = plan_adoption(s, workspace, detect=detect)
        if yes and ad.updates:
            apply_adoption(ad)
        out.append(ad)
    return out
