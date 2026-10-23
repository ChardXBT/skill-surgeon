"""Core data model for skill-surgeon."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

SEVERITIES = ("error", "warn", "info")
_SEV_PENALTY = {"error": 8, "warn": 3, "info": 1}


@dataclass
class Skill:
    """A single SKILL.md package discovered under a skills root."""

    path: Path            # absolute path to SKILL.md
    root: Path            # the skills root it was discovered under
    raw: str              # full file text
    meta: dict            # parsed frontmatter (may be partial/empty)
    fm_raw: str           # raw frontmatter text between --- fences
    fm_start: int         # 0-based line index of opening ---
    fm_end: int           # 0-based line index of closing --- (-1 if none)
    body: str             # markdown body after frontmatter
    parse_error: str = "" # non-fatal frontmatter parse problem

    @property
    def dir(self) -> Path:
        return self.path.parent

    @property
    def name(self) -> str | None:
        v = self.meta.get("name")
        return str(v).strip() if v is not None else None

    @property
    def description(self) -> str | None:
        v = self.meta.get("description")
        return str(v).strip() if v is not None else None

    @property
    def slug(self) -> str:
        return self.name or self.dir.name

    @property
    def est_tokens(self) -> int:
        return max(1, len(self.raw) // 4)

    @property
    def body_lines(self) -> int:
        return len(self.body.splitlines())


@dataclass
class Finding:
    rule: str
    severity: str           # error | warn | info
    skill: str              # skill slug
    file: Path
    message: str
    line: int = 0
    fixable: bool = False   # can surgeon propose a concrete edit?


@dataclass
class Fix:
    """A concrete, reviewable proposed edit.

    kind:
      replace_text - exact find/replace on `file` (mechanically safe)
      rename_dir   - move skill directory (operator must approve; changes paths)
      manual       - cannot be auto-applied; instructions only
    """

    id: str
    skill: str
    rule: str
    kind: str
    file: str
    rationale: str
    find: str = ""
    replace: str = ""
    auto: bool = True       # False => needs human judgement (rename_dir/manual)
    status: str = "pending" # pending | applied | skipped | failed

    def to_dict(self) -> dict:
        return {
            "id": self.id, "skill": self.skill, "rule": self.rule,
            "kind": self.kind, "file": self.file, "rationale": self.rationale,
            "find": self.find, "replace": self.replace, "auto": self.auto,
            "status": self.status,
        }

    @staticmethod
    def from_dict(d: dict) -> "Fix":
        return Fix(
            id=d["id"], skill=d["skill"], rule=d["rule"], kind=d["kind"],
            file=d["file"], rationale=d.get("rationale", ""),
            find=d.get("find", ""), replace=d.get("replace", ""),
            auto=d.get("auto", True), status=d.get("status", "pending"),
        )


@dataclass
class Report:
    skills: list[Skill] = field(default_factory=list)
    findings: list[Finding] = field(default_factory=list)
    collisions: list[dict] = field(default_factory=list)      # from semantic pass
    desc_quality: list[dict] = field(default_factory=list)    # from semantic pass
    semantic_ok: bool = False
    semantic_note: str = ""

    def counts(self) -> dict:
        c = {"error": 0, "warn": 0, "info": 0}
        for f in self.findings:
            c[f.severity] = c.get(f.severity, 0) + 1
        return c

    def score_for(self, slug: str) -> int:
        s = 100
        for f in self.findings:
            if f.skill == slug:
                s -= _SEV_PENALTY.get(f.severity, 0)
        for col in self.collisions:
            if slug in (col.get("a"), col.get("b")):
                s -= 4
        return max(0, s)

    def score(self) -> int:
        if not self.skills:
            return 100
        return round(sum(self.score_for(s.slug) for s in self.skills) / len(self.skills))
