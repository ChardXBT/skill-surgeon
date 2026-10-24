"""Host environment detection for `surgeon tailor`.

Skills are written on the author's machine and run on everyone else's.
This module profiles the actual environment so tailor can rewrite
instructions to fit: which interpreters exist, which CLIs are installed,
what the skills root is called, which OS/shell conventions apply.
"""

from __future__ import annotations

import os
import platform
import shutil
import sys
from dataclasses import dataclass, field
from pathlib import Path

INTERPRETERS = ("python3", "python", "py", "node", "npm", "pip", "pip3",
                "bash", "sh", "pwsh", "powershell")
CLIS = ("git", "docker", "gh", "ollama", "ffmpeg", "jq", "curl", "wget",
        "rg", "pandoc", "uv", "bun", "deno")

# platform-specific skill-root directory conventions
SKILL_ROOT_NAMES = (".agents/skills", ".claude/skills", ".devin/skills",
                    ".codex/skills", ".cursor/skills", ".windsurf/skills")

# host OS labels we rewrite between
POSIX_ONLY_TOOLS = ("sudo", "apt", "apt-get", "brew", "yum", "dnf",
                    "chmod", "chown", "launchctl", "systemctl", "osascript")


@dataclass
class Environment:
    os: str                       # windows | linux | macos
    shell: str                    # bash | powershell | zsh | ...
    home: Path
    interpreters: dict[str, str | None] = field(default_factory=dict)
    clis: dict[str, str | None] = field(default_factory=dict)
    skill_roots: list[Path] = field(default_factory=list)

    def has(self, tool: str) -> bool:
        return bool(self.interpreters.get(tool) or self.clis.get(tool))

    def python_cmd(self) -> str | None:
        for c in ("python3", "python", "py"):
            if self.interpreters.get(c):
                return c
        return None

    def root_name(self, skill_dir: Path) -> str | None:
        """Which convention name the skill actually lives under, if any."""
        parts = {p.lower() for p in skill_dir.parts}
        for conv in ("agents", "claude", "devin", "codex", "cursor", "windsurf"):
            if f".{conv}" in parts:
                return conv
        return None


def _verify_works(tool: str, path: str | None) -> str | None:
    """A PATH entry isn't proof the tool runs (Windows Store python3 stub)."""
    if not path:
        return None
    if tool in ("python3", "python", "py", "node", "uv", "bun", "deno"):
        try:
            import subprocess
            r = subprocess.run([tool, "--version"], capture_output=True,
                               text=True, timeout=10)
            out = (r.stdout or "") + (r.stderr or "")
            if r.returncode != 0 or "Microsoft Store" in out or "not found" in out.lower():
                return None
        except Exception:
            return None
    return path


def detect() -> Environment:
    sysname = platform.system().lower()
    os_name = {"windows": "windows", "darwin": "macos"}.get(sysname, "linux")
    shell = "powershell" if os.environ.get("PSModulePath") and os_name == "windows" \
        else Path(os.environ.get("SHELL", "")).name or \
        ("powershell" if os_name == "windows" else "sh")

    env = Environment(os=os_name, shell=shell, home=Path.home())
    for t in INTERPRETERS:
        env.interpreters[t] = _verify_works(t, shutil.which(t))
    for t in CLIS:
        env.clis[t] = shutil.which(t)

    for base in (Path.cwd(), env.home):
        for name in SKILL_ROOT_NAMES:
            p = base / name
            if p.is_dir() and p not in env.skill_roots:
                env.skill_roots.append(p)
    return env


def describe(env: Environment) -> str:
    py = env.python_cmd() or "none"
    cli_ok = [t for t, p in env.clis.items() if p]
    return (f"os={env.os} shell={env.shell} python={py} "
            f"clis=[{', '.join(cli_ok) or 'none'}] "
            f"roots={len(env.skill_roots)}")
