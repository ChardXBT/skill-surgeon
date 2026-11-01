"""surgeon tailor - context-aware skill adaptation.

Skills are written on the author's machine. This module finds where the
instructions assume that machine (platform root paths, `python3`, POSIX
tools, install-root env vars) and proposes exact rewrites for the host
environment - or for a target agent platform via --for.
"""

from __future__ import annotations

import re
import shutil
from pathlib import Path

from .env import Environment, POSIX_ONLY_TOOLS
from .model import Finding, Fix, Skill

T_RULES = {
    "T001": "skill hardcodes another platform's install root (e.g. .claude/skills/...)",
    "T002": "command uses an interpreter that is not on PATH here",
    "T003": "POSIX-only tool referenced on a non-POSIX host",
    "T004": "platform-specific env var / placeholder for skill root",
    "T005": "command requires a CLI that is not installed",
    "T006": "reserved: shell syntax mismatch for host shell (not checked yet)",
}

# .claude/skills/<name>/scripts/x.py  ->  scripts/x.py  (paths resolve from
# the skill dir regardless of which agent platform installed it)
PLATFORM_ROOT_RE = re.compile(
    r"\.(claude|agents|devin|codex|cursor|windsurf|autohand)[/\\]skills[/\\]"
    r"([A-Za-z0-9_-]+)[/\\]")
SKILL_ROOT_VAR_RE = re.compile(r"\$\{?(CLAUDE_SKILL_ROOT|CODEX_SKILL_ROOT|SKILL_DIR)\}?")
# characters that end a path token when scanning back for its root prefix
_TOKEN_STOP = set(" \t\n`'\"()[]<>=,;|")

CMD_WORDS = ("python3", "python", "py", "node", "npm", "pip", "bash", "sh",
             "pwsh", "powershell", "uv", "bun", "deno", "docker", "gh", "jq",
             "ffmpeg", "ollama", "rg", "pandoc") + POSIX_ONLY_TOOLS

_FENCE_RE = re.compile(r"^\s*(`{3,}|~{3,})")


def _code_blocks(body: str) -> list[tuple[int, str]]:
    """(first_content_line, block_text) for fenced code blocks; line numbers
    are 1-based body lines. ``` and ~~~ fences; a longer fence is closed only
    by a fence of the same character that is at least as long."""
    out = []
    fence = ""
    start = 0
    buf: list[str] = []
    for i, line in enumerate(body.split("\n")):
        m = _FENCE_RE.match(line)
        if m:
            mark = m.group(1)
            if not fence:
                fence, start, buf = mark, i + 2, []
                continue
            if mark[0] == fence[0] and len(mark) >= len(fence) \
                    and not line.strip()[len(mark):].strip():
                out.append((start, "\n".join(buf)))
                fence = ""
                continue
        if fence:
            buf.append(line)
    return out


def _commands(body: str, offset: int = 0) -> list[tuple[int, str]]:
    """Executable-looking command lines: (line_no, command).

    `line_no` is a body line + `offset`; pass `skill.body_offset` to get the
    real SKILL.md file line."""
    cmds: list[tuple[int, str]] = []
    for start, block in _code_blocks(body):
        for off, line in enumerate(block.split("\n")):
            s = line.strip().lstrip("$ ").strip()
            if not s or s.startswith("#"):
                continue
            first = s.split()[0].rstrip(":")
            if first in CMD_WORDS or first.startswith(("./", "python")):
                cmds.append((offset + start + off, s))
    return cmds


def _root_prefix(text: str, at: int) -> str:
    """The path text before a `.claude/skills/...` match: `~/`, `$HOME/`,
    `C:\\Users\\me\\`... Stripping the match alone would leave it dangling."""
    j = at
    while j > 0 and text[j - 1] not in _TOKEN_STOP:
        j -= 1
    prefix = text[j:at]
    return prefix if prefix.endswith(("/", "\\")) else ""


def tailor_skill(skill: Skill, env: Environment,
                 target_platform: str | None = None) -> tuple[list[Finding], list[Fix]]:
    """Find environment mismatches in one skill; propose exact rewrites."""
    findings: list[Finding] = []
    fixes: list[Fix] = []
    body, slug = skill.body, skill.slug
    off = skill.body_offset
    actual_root = env.root_name(skill.dir)
    target = target_platform or actual_root

    def file_line(pos: int) -> int:
        return off + body.count("\n", 0, pos) + 1

    # T001/T004: platform install-root paths and root env vars
    matches = list(PLATFORM_ROOT_RE.finditer(body))
    own = {skill.slug, skill.dir.name}
    # A skill that names its own path under several platform roots is
    # probing install locations on purpose (a find-my-script loop); rewriting
    # each candidate to the same relative path would break the lookup.
    probe_roots = {m.group(1) for m in matches if m.group(2) in own}
    probing = len(probe_roots) >= 2
    if probing:
        first = next(m for m in matches if m.group(2) in own)
        findings.append(Finding(
            "T001", "info", slug, skill.path,
            f"probes its own install path under {len(probe_roots)} platform roots "
            f"({', '.join('.' + r for r in sorted(probe_roots))}) - intentional "
            "multi-platform lookup, no rewrite proposed",
            line=file_line(first.start())))

    t001: dict[tuple[str, str], list] = {}   # (find, replace) -> [finding, n]
    for m in matches:
        plat, name = m.group(1), m.group(2)
        self_ref = name in own
        wrong_root = target is not None and plat != target
        if not (self_ref or wrong_root) or (self_ref and probing):
            continue
        prefix = _root_prefix(body, m.start()) if self_ref else ""
        find = prefix + m.group(0)
        if self_ref:
            replace = ""
            rationale = (f"strip `{find}` so bundled paths resolve relative "
                         "to the skill dir on any platform")
        else:
            replace = m.group(0).replace(f".{plat}", f".{target}", 1)
            rationale = (f"point `{name}` at this platform's root `.{target}/skills/` "
                         "(verify that skill is installed there)")
        key = (find, replace)
        if key in t001:   # one finding + one replace_all fix per distinct path
            t001[key][1] += 1
            continue
        fnd = Finding(
            "T001", "error" if self_ref else "warn", slug, skill.path,
            f"hardcodes `.{plat}/skills/{name}/` - "
            + ("self-referencing install path breaks on every other platform"
               if self_ref else f"installed under `.{target}/skills/` here"),
            line=file_line(m.start()), fixable=True)
        t001[key] = [fnd, 1]
        findings.append(fnd)
        fixes.append(Fix(
            id="", skill=slug, rule="T001", kind="replace_text",
            file=str(skill.path), find=find, replace=replace, replace_all=True,
            rationale=rationale, confidence="safe" if self_ref else "review"))
    for fnd, n in t001.values():
        if n > 1:
            fnd.message += f" ({n} occurrences)"

    var_hits: dict[str, list[int]] = {}
    for m in SKILL_ROOT_VAR_RE.finditer(body):
        var_hits.setdefault(m.group(0), []).append(file_line(m.start()))
    for var, lines in var_hits.items():
        more = f" ({len(lines)} occurrences)" if len(lines) > 1 else ""
        findings.append(Finding(
            "T004", "warn", slug, skill.path,
            f"`{var}` env var is platform-specific; prefer paths relative to "
            f"the SKILL.md dir{more}", line=lines[0], fixable=False))

    # T002/T003/T005: per-command checks
    seen: set[str] = set()
    for line, cmd in _commands(body, off):
        first = cmd.split()[0]
        if first in ("python3", "node", "pip3", "uv", "bun", "deno",
                     "docker", "gh", "jq", "ffmpeg", "ollama", "rg", "pandoc",
                     "pwsh", "npm"):
            if not env.has(first):
                key = f"interp:{first}"
                if key in seen:
                    continue
                seen.add(key)
                alt = None
                if first == "python3":
                    # Windows ships the `py` launcher where `python3` is a
                    # Microsoft Store stub - offer whichever really runs
                    alt = next((a for a in ("python", "py") if env.has(a)), None)
                findings.append(Finding(
                    "T002", "warn", slug, skill.path,
                    f"`{first}` is not on PATH in this environment"
                    + (f" (but `{alt}` is)" if alt else " - skill will fail here"),
                    line=line, fixable=bool(alt)))
                if alt:
                    fixes.append(Fix(
                        id="", skill=slug, rule="T002", kind="replace_text",
                        file=str(skill.path), find=f"{first} ", replace=f"{alt} ",
                        replace_all=True,
                        rationale=f"`{first}` is absent on this host; `{alt}` resolves "
                                  f"to {env.interpreters[alt]} (replaces every use)"))
        if env.os == "windows" and first in POSIX_ONLY_TOOLS \
                and not shutil.which(first):
            # Git Bash / MSYS put chmod, cp... on PATH - only flag a tool
            # this host really lacks
            if f"posix:{first}" in seen:
                continue
            seen.add(f"posix:{first}")
            findings.append(Finding(
                "T003", "warn", slug, skill.path,
                f"`{first}` is POSIX-only - not available on this Windows host",
                line=line, fixable=False))
        if first in ("jq", "pandoc", "ffmpeg", "docker", "gh", "ollama"):
            if not env.has(first):
                key = f"cli:{first}"
                if key in seen:
                    continue
                seen.add(key)
                findings.append(Finding(
                    "T005", "warn", slug, skill.path,
                    f"command requires `{first}` which is not installed here",
                    line=line, fixable=False))

    return findings, fixes


def tailor_all(skills: list[Skill], env: Environment,
               target_platform: str | None = None) -> tuple[list[Finding], list[Fix]]:
    f_all: list[Finding] = []
    x_all: list[Fix] = []
    for s in skills:
        f, x = tailor_skill(s, env, target_platform)
        f_all.extend(f)
        x_all.extend(x)
    return f_all, x_all
