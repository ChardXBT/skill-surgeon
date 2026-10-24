"""surgeon test - smoke-test the commands a skill documents.

Structural checks prove referenced files exist. This layer answers the
harder question: do the documented commands actually run on this machine?
Default mode is static (interpreter on PATH? invoked file exists? does the
script compile?). --run actually executes each command in the skill dir
with a timeout, behind a denylist of dangerous patterns.
"""

from __future__ import annotations

import os
import re
import subprocess
from dataclasses import dataclass, field
from pathlib import Path

from .env import Environment
from .model import Skill
from .tailor import _commands

# never executed, even with --run
NEVER_RUN = re.compile(
    r"(?:^|\s|&&|\|\|)(rm|del|rmdir|sudo|curl|wget|chmod|chown|dd|mkfs|"
    r"shutdown|reboot|mv|move|copy|cp|scp|ssh|scp|git\s+push|pip\s+install|"
    r"npm\s+install|apt|brew)\b|>\s*/|>>")

# env vars scrubbed before --run: skill scripts shouldn't inherit credentials
_SECRET_ENV_RE = re.compile(
    r"(?i)(api[_-]?key|secret|token|password|passwd|credential|auth)")


def _scrubbed_env() -> dict:
    """os.environ minus secret-looking variables (values stay on this host)."""
    return {k: v for k, v in os.environ.items() if not _SECRET_ENV_RE.search(k)}
SCRIPT_EXT = {".py", ".sh", ".ps1", ".js", ".ts", ".bash", ".rb"}


@dataclass
class CmdResult:
    skill: str
    line: int
    command: str
    status: str          # ok | missing_file | missing_interp | syntax_fail | crashed | unsafe_skipped | timeout
    detail: str = ""


@dataclass
class SmokeReport:
    results: list[CmdResult] = field(default_factory=list)

    def counts(self) -> dict:
        c: dict[str, int] = {}
        for r in self.results:
            c[r.status] = c.get(r.status, 0) + 1
        return c


def _invoked_files(cmd: str) -> list[str]:
    """Local-looking file args in a command line."""
    out = []
    for tok in cmd.split():
        tok = tok.strip("'\"")
        if tok.startswith("-") or "://" in tok:
            continue
        if Path(tok).suffix.lower() in SCRIPT_EXT:
            out.append(tok.lstrip("./"))
    return out


def check_command(skill: Skill, line: int, cmd: str,
                  env: Environment, run: bool) -> CmdResult:
    first = cmd.split()[0]

    if first in ("python3", "python", "py", "node", "bash", "sh", "uv",
                 "pwsh", "powershell", "npm", "pip", "pip3", "deno", "bun"):
        if not env.has(first):
            return CmdResult(skill.slug, line, cmd, "missing_interp",
                             f"`{first}` not on PATH")
    elif first.startswith("./"):
        pass  # direct script invocation; file check below covers it
    else:
        if not env.has(first):
            return CmdResult(skill.slug, line, cmd, "missing_interp",
                             f"`{first}` not found on PATH")

    missing = [f for f in _invoked_files(cmd) if not (skill.dir / f).exists()]
    if missing:
        return CmdResult(skill.slug, line, cmd, "missing_file",
                         f"not found: {', '.join(missing)}")

    # static compile check for python scripts we can see
    for f in _invoked_files(cmd):
        fp = skill.dir / f
        if fp.suffix == ".py" and fp.exists():
            r = subprocess.run(
                [env.python_cmd() or "python", "-m", "py_compile", str(fp)],
                capture_output=True, text=True, timeout=15)
            if r.returncode != 0:
                return CmdResult(skill.slug, line, cmd, "syntax_fail",
                                 (r.stderr or "compile failed").strip().split("\n")[-1][:160])

    if not run:
        return CmdResult(skill.slug, line, cmd, "ok", "static checks passed")

    if NEVER_RUN.search(cmd):
        return CmdResult(skill.slug, line, cmd, "unsafe_skipped",
                         "matches denylist; not executed")
    try:
        r = subprocess.run(cmd, shell=True, cwd=skill.dir,
                           capture_output=True, text=True, timeout=20,
                           env=_scrubbed_env())
    except subprocess.TimeoutExpired:
        return CmdResult(skill.slug, line, cmd, "timeout", ">20s")
    except Exception as e:
        return CmdResult(skill.slug, line, cmd, "crashed", str(e)[:160])
    if r.returncode != 0:
        tail = (r.stderr or r.stdout or "").strip().split("\n")
        return CmdResult(skill.slug, line, cmd, "crashed",
                         (tail[-1] if tail else f"exit {r.returncode}")[:160])
    return CmdResult(skill.slug, line, cmd, "ok", "ran clean")


def smoke_test(skills: list[Skill], env: Environment, run: bool) -> SmokeReport:
    rep = SmokeReport()
    for s in skills:
        seen: set[str] = set()
        for line, cmd in _commands(s.body):
            if cmd in seen:
                continue
            seen.add(cmd)
            rep.results.append(check_command(s, line, cmd, env, run))
    return rep
