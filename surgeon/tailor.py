"""surgeon tailor - context-aware skill adaptation.

Skills are written on the author's machine. This module finds where the
instructions assume that machine (platform root paths, `python3`, POSIX
tools, install-root env vars) and proposes exact rewrites for the host
environment - or for a target agent platform via --for.
"""

from __future__ import annotations

import re
from pathlib import Path

from .env import Environment, POSIX_ONLY_TOOLS
from .model import Finding, Fix, Skill

T_RULES = {
    "T001": "skill hardcodes another platform's install root (e.g. .claude/skills/...)",
    "T002": "command uses an interpreter that is not on PATH here",
    "T003": "POSIX-only tool referenced on a non-POSIX host",
    "T004": "platform-specific env var / placeholder for skill root",
    "T005": "command requires a CLI that is not installed",
    "T006": "shell syntax mismatch for host shell",
}

# .claude/skills/<name>/scripts/x.py  ->  scripts/x.py  (paths resolve from
# the skill dir regardless of which agent platform installed it)
PLATFORM_ROOT_RE = re.compile(
    r"\.(claude|agents|devin|codex|cursor|windsurf|autohand)[/\\]skills[/\\]"
    r"([A-Za-z0-9_-]+)[/\\]")
SKILL_ROOT_VAR_RE = re.compile(r"\$\{?(CLAUDE_SKILL_ROOT|CODEX_SKILL_ROOT|SKILL_DIR)\}?")

CMD_WORDS = ("python3", "python", "py", "node", "npm", "pip", "bash", "sh",
             "pwsh", "powershell", "uv", "bun", "deno", "docker", "gh", "jq",
             "ffmpeg", "ollama", "rg", "pandoc") + POSIX_ONLY_TOOLS


def _code_blocks(body: str) -> list[tuple[int, str]]:
    """(start_line, block_text) for fenced code blocks."""
    out = []
    in_block = False
    start = 0
    buf: list[str] = []
    for i, line in enumerate(body.split("\n")):
        if line.strip().startswith("```"):
            if in_block:
                out.append((start, "\n".join(buf)))
                buf = []
                in_block = False
            else:
                in_block, start = True, i + 1
            continue
        if in_block:
            buf.append(line)
    return out


def _commands(body: str) -> list[tuple[int, str]]:
    """Executable-looking command lines: (line_no, command)."""
    cmds: list[tuple[int, str]] = []
    for start, block in _code_blocks(body):
        for off, line in enumerate(block.split("\n")):
            s = line.strip().lstrip("$ ").strip()
            if not s or s.startswith("#"):
                continue
            first = s.split()[0].rstrip(":")
            if first in CMD_WORDS or first.startswith(("./", "python")):
                cmds.append((start + off, s))
    return cmds


def tailor_skill(skill: Skill, env: Environment,
                 target_platform: str | None = None) -> tuple[list[Finding], list[Fix]]:
    """Find environment mismatches in one skill; propose exact rewrites."""
    findings: list[Finding] = []
    fixes: list[Fix] = []
    body, slug = skill.body, skill.slug
    actual_root = env.root_name(skill.dir)
    target = target_platform or actual_root

    # T001/T004: platform install-root paths and root env vars
    for m in PLATFORM_ROOT_RE.finditer(body):
        plat, name = m.group(1), m.group(2)
        line = body.count("\n", 0, m.start()) + 1
        self_ref = name == slug or name == skill.dir.name
        wrong_root = target is not None and plat != target
        if self_ref or wrong_root:
            findings.append(Finding(
                "T001", "error" if self_ref else "warn", slug, skill.path,
                f"hardcodes `.{plat}/skills/{name}/` - "
                + ("self-referencing install path breaks on every other platform"
                   if self_ref else f"installed under `.{target}/skills/` here"),
                line=line, fixable=True))
            fixes.append(Fix(
                id="", skill=slug, rule="T001", kind="replace_text",
                file=str(skill.path),
                find=f".{plat}/skills/{name}/",
                replace="", replace_all=True,
                rationale=f"strip every `.{plat}/skills/{name}/` prefix so bundled "
                          f"paths resolve relative to the skill dir on any platform"))

    for m in SKILL_ROOT_VAR_RE.finditer(body):
        line = body.count("\n", 0, m.start()) + 1
        findings.append(Finding(
            "T004", "warn", slug, skill.path,
            f"`{m.group(0)}` env var is platform-specific; prefer paths relative to "
            "the SKILL.md dir", line=line, fixable=False))

    # T002/T003/T005: per-command checks
    seen: set[str] = set()
    for line, cmd in _commands(body):
        first = cmd.split()[0]
        if first in ("python3", "node", "pip3", "uv", "bun", "deno",
                     "docker", "gh", "jq", "ffmpeg", "ollama", "rg", "pandoc",
                     "pwsh", "npm"):
            if not env.has(first):
                key = f"interp:{first}"
                if key in seen:
                    continue
                seen.add(key)
                alt = "python" if first == "python3" and env.has("python") else None
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
        if env.os == "windows" and first in POSIX_ONLY_TOOLS:
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
