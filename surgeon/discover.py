"""Discover SKILL.md files under skills roots."""

from __future__ import annotations

from pathlib import Path

from .frontmatter import parse_frontmatter, split_frontmatter
from .model import Skill

SKIP_DIRS = {".git", "node_modules", "__pycache__", ".venv", "venv", ".idea", ".vscode"}
MAX_DEPTH = 6

# Upstream skill packs kept as reference material (`<skill>/vendor/<pack>/...`)
# are not the library's own installed skills: their findings belong upstream,
# and an installed copy elsewhere would read as a duplicate. Skipped below a
# scan root unless include_vendored=True; a path that IS such a dir is still
# scanned when passed explicitly.
VENDOR_DIRS = {"vendor", "vendored", "third_party", "third-party"}

DEFAULT_ROOT_NAMES = (
    ".agents/skills", ".claude/skills", ".devin/skills",
    ".codex/skills", ".cursor/skills", ".windsurf/skills", "agents/skills",
)


def default_roots() -> list[Path]:
    """Candidate roots: cwd-relative + home-relative, existing only."""
    roots: list[Path] = []
    for base in (Path.cwd(), Path.home()):
        for rel in DEFAULT_ROOT_NAMES:
            p = base / rel
            if p.is_dir():
                roots.append(p.resolve())
    # dedupe while preserving order
    seen, out = set(), []
    for r in roots:
        if r not in seen:
            seen.add(r)
            out.append(r)
    return out


def _walk_skill_files(root: Path, depth: int = 0,
                      include_vendored: bool = False,
                      skipped: list[Path] | None = None) -> list[Path]:
    found: list[Path] = []
    if depth > MAX_DEPTH or not root.is_dir():
        return found
    try:
        entries = sorted(root.iterdir())
    except OSError:
        return found
    for e in entries:
        if e.is_file() and e.name.lower() == "skill.md":
            found.append(e)
    for e in entries:
        if not e.is_dir() or e.name in SKIP_DIRS:
            continue
        if e.name.lower() in VENDOR_DIRS and not include_vendored:
            if skipped is not None:
                skipped.extend(_walk_skill_files(e, depth + 1, True))
            continue
        found.extend(_walk_skill_files(e, depth + 1, include_vendored, skipped))
    return found


def load_skill(path: Path, root: Path) -> Skill:
    try:
        raw = path.read_text(encoding="utf-8", errors="replace")
    except OSError as e:
        return Skill(path=path, root=root, raw="", meta={}, fm_raw="",
                     fm_start=-1, fm_end=-1, body="",
                     parse_error=f"unreadable: {e}")
    raw = raw.replace("\r\n", "\n").replace("\r", "\n")
    fm_raw, body, fm_start, fm_end = split_frontmatter(raw)
    if fm_raw is None:
        return Skill(path=path, root=root, raw=raw, meta={}, fm_raw="",
                     fm_start=fm_start, fm_end=fm_end, body=body,
                     parse_error="no frontmatter block")
    meta, err = parse_frontmatter(fm_raw)
    return Skill(path=path, root=root, raw=raw, meta=meta, fm_raw=fm_raw,
                 fm_start=fm_start, fm_end=fm_end, body=body, parse_error=err)


def discover(paths: list[str] | None, include_vendored: bool = False,
             skipped: list[Path] | None = None) -> tuple[list[Skill], list[Path]]:
    """Discover skills. Each path may be a skills root, a single skill dir,
    a SKILL.md file, or a tree containing skills.

    SKILL.md files under vendor/ dirs below a scanned tree are skipped unless
    `include_vendored`; pass a list as `skipped` to receive their paths."""
    skills: list[Skill] = []
    roots_used: list[Path] = []
    seen: set[Path] = set()

    targets = [Path(p).expanduser().resolve() for p in paths] if paths else default_roots()
    for t in targets:
        if t.is_file() and t.name.lower() == "skill.md":
            files, root = [t], t.parent.parent
            roots_used.append(t.parent.parent)
        elif t.is_dir() and (t / "SKILL.md").is_file():
            files, root = [t / "SKILL.md"], t.parent
            roots_used.append(t.parent)
        elif t.is_dir():
            files, root = _walk_skill_files(t, 0, include_vendored, skipped), t
            roots_used.append(t)
        else:
            continue
        for f in files:
            rp = f.resolve()
            if rp in seen:
                continue
            seen.add(rp)
            skills.append(load_skill(rp, root))
    return skills, roots_used


def is_nested(skill: Skill) -> bool:
    """True when the skill sits inside another skill's package (a family
    sub-skill like `<pack>/skills/<name>/SKILL.md`), below its scan root.
    `variants/<slot>/SKILL.md` is a sibling alternative, not nested."""
    d = skill.dir.parent
    while d != skill.root and skill.root in d.parents:
        if (d / "SKILL.md").is_file():
            return "variants" not in {p.lower() for p in
                                      skill.path.relative_to(d).parts}
        d = d.parent
    return False
