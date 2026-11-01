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
import shutil
import subprocess
import tempfile
from dataclasses import dataclass, field
from pathlib import Path

from .env import CLIS, INTERPRETERS, Environment
from .model import Skill
from .tailor import _commands

# never executed, even with --run. Checked per segment (the command is
# split on ; | && || ` $( ) so `echo x; rm -rf /` or `$(rm -rf /)` can't
# smuggle a denied verb past a prefix-anchored match.
_NEVER_TOKENS = {
    "rm", "del", "rmdir", "sudo", "chmod", "chown", "dd", "mkfs",
    "shutdown", "reboot", "mv", "move", "copy", "cp", "scp", "ssh",
    "format", "reg", "bitsadmin", "certutil", "mshta", "iex", "apt",
    "apt-get", "brew", "yum", "dnf", "chattr",
}
_NEVER_RE = re.compile(
    r"(git\s+push|pip3?\s+install|npm\s+install|pypi\s+install|"
    r"curl|wget|iwr\b|irm\b|invoke-(webrequest|expression|command)|"
    r"powershell|pwsh|Remove-Item|>\s*(?:/|~|\.\.)|>>)",
    re.IGNORECASE)
_SEGMENT_SPLIT = re.compile(r"&&|\|\||[;|`]|\$\(")
# commands whose *output* we must not produce: reads of credential files
# would leak secrets into the report detail field
_READ_CMDS = {"cat", "type", "get-content", "head", "tail", "less", "more"}
_SENSITIVE_PATH_RE = re.compile(
    r"(?i)(\.ssh|\.aws|\.gnupg|\.env\b|id_rsa|id_ed25519|credentials|"
    r"secret|password|token|\.kube|\.docker|~/\.|~\\\.|%USERPROFILE%)"
)


def _unsafe_reason(cmd: str) -> str | None:
    """Why a command may not be executed; None if it looks safe."""
    if _NEVER_RE.search(cmd):
        return "matches denylist; not executed"
    for seg in _SEGMENT_SPLIT.split(cmd):
        toks = seg.split()
        if not toks:
            continue
        first = toks[0].strip("'\"")
        if first.lower() in _NEVER_TOKENS:
            return "matches denylist; not executed"
        if (first.lower() in _READ_CMDS
                and any(_SENSITIVE_PATH_RE.search(t) for t in toks[1:])):
            return "reads a credential-looking file; not executed"
    return None


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
    """Local-looking file args in a command line (redirect targets skipped:
    `python gen.py > out.py` writes out.py, it isn't an invoked input)."""
    out = []
    toks = cmd.split()
    for i, tok in enumerate(toks):
        if tok.startswith(">") or (i and toks[i - 1].startswith(">")):
            continue
        tok = tok.strip("'\"")
        if tok.startswith("-") or "://" in tok:
            continue
        if Path(tok).suffix.lower() in SCRIPT_EXT:
            out.append(tok.removeprefix("./").removeprefix(".\\"))
    return out


def check_command(skill: Skill, line: int, cmd: str,
                  env: Environment, run: bool) -> CmdResult:
    toks = cmd.split()
    if not toks:
        return CmdResult(skill.slug, line, cmd, "ok", "empty")
    first = toks[0]

    if first.startswith("./"):
        pass  # direct script invocation; file check below covers it
    elif not env.has(first):
        # probed-and-failed (None) is authoritative - don't resurrect e.g. the
        # Windows Store python3 stub via which(). Unprobed tools (sudo, apt)
        # fall back to a direct PATH check.
        if first in INTERPRETERS + CLIS or not shutil.which(first):
            return CmdResult(skill.slug, line, cmd, "missing_interp",
                             f"`{first}` not found on PATH")

    missing = [f for f in _invoked_files(cmd)
               if not (skill.dir / f).resolve().exists()]
    if missing:
        return CmdResult(skill.slug, line, cmd, "missing_file",
                         f"not found: {', '.join(missing)}")

    # static compile check for python scripts we can see - builtin compile()
    # so no __pycache__ is written into the audited skill and no interpreter
    # is needed
    for f in _invoked_files(cmd):
        fp = skill.dir / f
        if fp.suffix.lower() == ".py" and fp.exists():
            try:
                compile(fp.read_text(encoding="utf-8", errors="replace"),
                        str(fp), "exec")
            except SyntaxError as e:
                return CmdResult(skill.slug, line, cmd, "syntax_fail",
                                 f"{e.msg} (line {e.lineno})"[:160])
            except OSError as e:
                return CmdResult(skill.slug, line, cmd, "missing_file",
                                 str(e)[:160])

    if not run:
        return CmdResult(skill.slug, line, cmd, "ok", "static checks passed")

    reason = _unsafe_reason(cmd)
    if reason:
        return CmdResult(skill.slug, line, cmd, "unsafe_skipped", reason)
    # isolate: run against a temp copy of the skill dir so a rogue command
    # can't write into (or read neighbors of) the real library
    try:
        with tempfile.TemporaryDirectory(prefix="surgeon-") as iso:
            iso_dir = Path(iso) / skill.dir.name
            shutil.copytree(skill.dir, iso_dir)
            r = subprocess.run(cmd, shell=True, cwd=iso_dir,
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
            rep.results.append(
                check_command(s, s.body_offset + line, cmd, env, run))
    return rep
