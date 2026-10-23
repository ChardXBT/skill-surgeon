"""Deterministic checks bound to the Agent Skills specification
(agentskills.io): name <=64 kebab-case, description <=1024, body ~<=5000
tokens / <=500 lines. Plus safety and hygiene checks that don't need a model.
"""

from __future__ import annotations

import difflib
import re
from pathlib import Path

from .model import Finding, Skill

RULES = {
    "S001": ("error", "frontmatter missing or unparseable"),
    "S002": ("error", "name missing or not kebab-case (spec: <=64 chars)"),
    "S003": ("warn", "name does not match directory name"),
    "S004": ("error", "description missing or empty (skill will never trigger)"),
    "S005": ("warn", "description exceeds spec limit (1024 chars)"),
    "S006": ("warn", "body oversized (>500 lines or ~>5000 tokens)"),
    "S007": ("error", "referenced file does not exist"),
    "S008": ("warn", "hardcoded absolute path (non-portable)"),
    "S009": ("error", "duplicate skill name across scanned roots"),
    "S010": ("error", "possible embedded secret"),
    "S011": ("warn", "dangerous or prompt-injection pattern"),
    "S012": ("info", "date-stamped skill name (prefer stable name)"),
    "Q001": ("warn", "trigger description collision with another skill"),
    "Q002": ("warn", "weak trigger description (missing what/when)"),
}

NAME_RE = re.compile(r"^[a-z0-9]+(-[a-z0-9]+)*$")
DATE_SUFFIX_RE = re.compile(r"-(?:\d{4}[-_]\d{2}[-_]\d{2}|\d{8})$")

MD_LINK_RE = re.compile(r"\[[^\]]*\]\(([^)\s]+)(?:\s+[^)]*)?\)")
BACKTICK_RE = re.compile(r"`([^`\n]+)`")
FILEISH_EXT = {
    ".md", ".py", ".sh", ".bash", ".ps1", ".json", ".yaml", ".yml", ".toml",
    ".txt", ".csv", ".ts", ".js", ".jsx", ".tsx", ".sql", ".env", ".cfg",
    ".ini", ".xml", ".html", ".pdf", ".png", ".jpg", ".template",
}
DIR_PREFIXES = ("scripts/", "references/", "assets/", "examples/", "templates/",
                "resources/", "docs/", "files/", "./", "tools/", "prompts/")

# Refs under these prefixes are bundled resources — they MUST exist in the
# skill dir. Everything else may be a runtime artifact in another repo.
BUNDLED_PREFIXES = ("scripts/", "references/", "assets/", "examples/",
                    "templates/", "resources/", "./")

PLACEHOLDER_REF_RE = re.compile(r"Y{2,4}|M{2}D{2}|\{|\}|PLACEHOLDER|INSERT")

ABS_PATH_RE = re.compile(
    r"(?:[A-Za-z]:[\\/](?:Users|home|WINDOWS|Program Files)[^\s)\"'`\]>]*"
    r"|(?<![\w:/])/(?:Users|home)/[^\s)\"'`\]>]+)"
)

SECRET_PATTERNS = [
    (re.compile(r"sk-(?:ant-|live-)?[A-Za-z0-9_-]{20,}"), "API key literal"),
    (re.compile(r"(?:ghp|gho|ghu|ghs|ghr|github_pat)_[A-Za-z0-9_]{20,}"), "GitHub token"),
    (re.compile(r"AKIA[0-9A-Z]{16}"), "AWS access key"),
    (re.compile(r"xox[baprs]-[A-Za-z0-9-]{10,}"), "Slack token"),
    (re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----"), "private key"),
    (re.compile(r"(?i)(?:api[_-]?key|secret|token|password)\s*[:=]\s*[\"']([A-Za-z0-9_\-.]{16,})[\"']"),
     "assigned credential"),
]
PLACEHOLDER_HINTS = ("your", "xxx", "<", "example", "...", "$(", "${", "%", "redacted", "dummy", "placeholder")

INJECTION_RE = re.compile(
    r"(?i)(ignore (?:all )?previous instructions|disregard (?:your )?(?:system |prior )?instructions"
    r"|do not follow (?:your )?(?:system|prior)|override (?:your )?system prompt)"
)
DANGEROUS_SHELL_RE = re.compile(
    r"(curl[^|\n]*\|\s*(?:sudo\s+)?(?:ba|z)?sh|wget[^|\n]*\|\s*(?:ba|z)?sh|\brm\s+-rf\s+[/~])"
)


def _line_of(text: str, needle_start: int) -> int:
    return text.count("\n", 0, needle_start) + 1


def _candidate_refs(skill: Skill) -> list[tuple[str, int]]:
    """Extract (ref, line_no) pairs that look like local file references."""
    refs: list[tuple[str, int]] = []
    seen: set[str] = set()

    def add(raw_ref: str, pos: int):
        ref = raw_ref.strip().replace("\\", "/")
        ref = ref.split("#", 1)[0]
        ref = re.sub(r":\d+(?::\d+)?$", "", ref)  # strip :LINE / :L1-L2
        ref = ref.strip("'\"")
        if not ref or ref in seen:
            return
        low = ref.lower()
        if re.match(r"^[A-Za-z]:/", ref):  # absolute path — S008's job
            return
        if ("://" in ref or low.startswith(("mailto:", "#", "/", "~", "$", "<", "http"))):
            return
        if any(c in ref for c in "*$<>") or "%" in ref or " " in ref:
            return
        if PLACEHOLDER_REF_RE.search(ref):
            return
        looks_fileish = Path(ref).suffix.lower() in FILEISH_EXT
        looks_dirish = low.startswith(DIR_PREFIXES)
        if looks_fileish or looks_dirish:
            seen.add(ref)
            refs.append((ref, _line_of(skill.raw, pos)))

    for m in MD_LINK_RE.finditer(skill.body):
        add(m.group(1), m.start())
    for m in BACKTICK_RE.finditer(skill.body):
        add(m.group(1), m.start())
    return refs


def check_skill(skill: Skill) -> list[Finding]:
    f: list[Finding] = []
    slug, fp = skill.slug, skill.path

    if skill.fm_end == -1:
        f.append(Finding("S001", "error", slug, fp,
                         skill.parse_error or "missing/empty frontmatter block",
                         fixable=False))
    elif skill.parse_error:
        f.append(Finding("S001", "warn", slug, fp, skill.parse_error))

    name = skill.name
    if skill.fm_end != -1:
        if not name:
            f.append(Finding("S002", "error", slug, fp, "missing `name` field"))
        elif len(name) > 64 or not NAME_RE.match(name):
            f.append(Finding("S002", "error", slug, fp,
                             f"name `{name}` is not kebab-case <=64 chars (spec)"))
        elif name != skill.dir.name:
            f.append(Finding("S003", "warn", slug, fp,
                             f"name `{name}` != directory `{skill.dir.name}`", fixable=True))

        desc = skill.description
        if not desc:
            f.append(Finding("S004", "error", slug, fp,
                             "missing `description` — router cannot trigger this skill",
                             fixable=True))
        elif len(desc) > 1024:
            f.append(Finding("S005", "warn", slug, fp,
                             f"description is {len(desc)} chars (spec <=1024)", fixable=True))

        if name and DATE_SUFFIX_RE.search(name):
            f.append(Finding("S012", "info", slug, fp,
                             f"date-stamped name `{name}`; prefer a stable name", fixable=True))

    if skill.body_lines > 500 or skill.est_tokens > 5000:
        f.append(Finding("S006", "warn", slug, fp,
                         f"~{skill.est_tokens} tokens / {skill.body_lines} body lines "
                         "(spec guidance: <=5000 tokens, <=500 lines)"))

    # Skills may declare runtime workspaces (metadata.workspace, string or
    # list) where refs resolve — operational skills legitimately point at
    # files in the repo(s) they manage, not files bundled with them.
    ws_raw = skill.meta.get("workspace") or (skill.meta.get("metadata") or {}).get("workspace")
    workspaces = [Path(str(w)).expanduser() for w in
                  (ws_raw if isinstance(ws_raw, list) else [ws_raw]) if ws_raw]

    def _ref_ok(ref: str) -> bool:
        if (skill.dir / ref).exists():
            return True
        return any((w / ref).exists() for w in workspaces)

    for ref, line in _candidate_refs(skill):
        if _ref_ok(ref):
            continue
        if ref.startswith(BUNDLED_PREFIXES) or ref.startswith("./"):
            f.append(Finding("S007", "error", slug, fp,
                             f"dead bundled reference `{ref}`", line=line, fixable=True))
        elif workspaces:
            f.append(Finding("S007", "error", slug, fp,
                             f"reference `{ref}` not found in skill dir or "
                             f"declared workspace(s)", line=line, fixable=True))
        else:
            f.append(Finding("S007", "warn", slug, fp,
                             f"reference `{ref}` not found in skill dir "
                             "(verify it resolves at runtime)", line=line, fixable=True))

    for m in ABS_PATH_RE.finditer(skill.raw):
        frag = m.group(0)
        f.append(Finding("S008", "warn", slug, fp,
                         f"absolute path `{frag}` is machine/user-specific",
                         line=_line_of(skill.raw, m.start()), fixable=True))
        if sum(1 for x in f if x.rule == "S008") >= 5:
            break

    seen_secrets: set[str] = set()
    for rx, label in SECRET_PATTERNS:
        for m in rx.finditer(skill.raw):
            val = m.group(1) if m.lastindex else m.group(0)
            if val in seen_secrets:
                continue
            if any(h in val.lower() for h in PLACEHOLDER_HINTS):
                continue
            seen_secrets.add(val)
            f.append(Finding("S010", "error", slug, fp,
                             f"possible {label} in skill",
                             line=_line_of(skill.raw, m.start()), fixable=True))

    for m in INJECTION_RE.finditer(skill.raw):
        # quoted occurrences are usually *warnings about* injection, not injection
        line_start = skill.raw.rfind("\n", 0, m.start()) + 1
        if skill.raw[line_start:m.start()].count('"') % 2 == 1:
            continue
        f.append(Finding("S011", "error", slug, fp,
                         f"prompt-injection phrasing: `{m.group(0)[:60]}`",
                         line=_line_of(skill.raw, m.start())))
    for m in DANGEROUS_SHELL_RE.finditer(skill.raw):
        f.append(Finding("S011", "warn", slug, fp,
                         f"dangerous shell pattern: `{m.group(0)[:60]}`",
                         line=_line_of(skill.raw, m.start())))
    return f


def check_cross(skills: list[Skill]) -> list[Finding]:
    """Findings spanning multiple skills: duplicate names."""
    f: list[Finding] = []
    by_name: dict[str, list[Skill]] = {}
    for s in skills:
        if s.name:
            by_name.setdefault(s.name, []).append(s)
    for name, group in by_name.items():
        if len(group) < 2:
            continue
        locs = "; ".join(str(g.path) for g in group)
        for g in group:
            f.append(Finding("S009", "error", name, g.path,
                             f"duplicate name also defined at: {locs}", fixable=True))
    return f


def all_structural(skills: list[Skill]) -> list[Finding]:
    findings: list[Finding] = []
    for s in skills:
        findings.extend(check_skill(s))
    findings.extend(check_cross(skills))
    return findings


def closest_existing(ref: str, skill: Skill) -> str | None:
    """Fuzzy-match a dead ref against real files under the skill dir."""
    pool: list[str] = []
    for p in skill.dir.rglob("*"):
        if p.is_file() and p.name.lower() != "skill.md":
            try:
                pool.append(str(p.relative_to(skill.dir)).replace("\\", "/"))
            except ValueError:
                pass
    if not pool:
        return None
    m = difflib.get_close_matches(ref, pool, n=1, cutoff=0.55)
    if not m:
        return None
    # guard: the basenames must actually resemble each other
    base_ratio = difflib.SequenceMatcher(
        None, Path(ref).name.lower(), Path(m[0]).name.lower()).ratio()
    return m[0] if base_ratio >= 0.5 else None
