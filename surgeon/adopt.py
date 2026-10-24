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

from .frontmatter import rewrite_frontmatter
from .model import Skill


@dataclass
class Adoption:
    skill: str
    file: Path
    updates: dict[str, str] = field(default_factory=dict)
    already: list[str] = field(default_factory=list)   # keys already set
    applied: bool = False


def plan_adoption(skill: Skill, workspace: str | None,
                  today: str | None = None) -> Adoption:
    """Compute the metadata updates adopt would write (does not touch disk)."""
    today = today or date.today().isoformat()
    meta = skill.meta.get("metadata")
    meta = meta if isinstance(meta, dict) else {}

    ad = Adoption(skill=skill.slug, file=skill.path)
    if workspace:
        existing = meta.get("workspace")
        if existing != workspace:
            ad.updates["workspace"] = workspace
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
              yes: bool) -> list[Adoption]:
    out = []
    for s in skills:
        ad = plan_adoption(s, workspace)
        if yes and ad.updates:
            apply_adoption(ad)
        out.append(ad)
    return out
