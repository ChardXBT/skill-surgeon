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
import shlex
import shutil
import subprocess
import tempfile
from dataclasses import dataclass, field
from pathlib import Path

from .env import Environment
from .model import Skill
from .tailor import _commands

# never executed, even with --run. Checked per segment (the command is
# split on ; | && || ` $( ) so `echo x; rm -rf /` or `$(rm -rf /)` can't
# smuggle a denied verb past a prefix-anchored match.
_NEVER_TOKENS = {
    "rm", "del", "rmdir", "rd", "erase", "sudo", "chmod", "chown", "dd",
    "mkfs", "shutdown", "reboot", "mv", "move", "copy", "cp", "scp", "ssh",
    "format", "reg", "bitsadmin", "certutil", "mshta", "iex", "apt",
    "apt-get", "brew", "yum", "dnf", "chattr",
    "remove-item", "move-item", "copy-item",
}
_NEVER_RE = re.compile(
    r"(git\s+push|pip3?\s+install|npm\s+install|pypi\s+install|"
    r"curl|wget|iwr\b|irm\b|invoke-(webrequest|expression|command)|"
    r"powershell|pwsh|>\s*(?:/|~|\.\.)|>>)",
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


SCRIPT_EXT = {".py", ".sh", ".ps1", ".js", ".mjs", ".cjs", ".ts", ".bash", ".rb"}

# Ways a skill spells "the directory containing this SKILL.md". A script
# under one of these is a bundled file and is checked against the skill dir.
SKILL_DIR_TOKEN_RE = re.compile(
    r"^(?:<(?:skill[-_ ]?(?:path|dir|root|base[-_ ]?dir)|path[-_ ]to[-_ ]skill"
    r"|this[-_ ]skill(?:[-_ ]dir)?)>"
    r"|\$\{?(?:SKILL_DIR|SKILL_ROOT|CLAUDE_SKILL_DIR|CLAUDE_SKILL_ROOT|"
    r"CODEX_SKILL_ROOT)\}?"
    r"|\{baseDir\})[\\/]", re.I)

# interpreters whose first positional argument is the script they execute
_SCRIPT_RUNNERS = {"python", "python3", "py", "node", "bash", "sh", "zsh",
                   "ruby", "deno", "bun", "tsx", "ts-node"}

# The closed vocabulary of check outcomes - a command check always ends in
# exactly one of these. `surgeon test` may exit green only for the states
# in CMD_STATUSES_PASS; an outcome the vocabulary doesn't know can never
# pass the CI gate (and a new state added here must be classified into
# PASS or it breaks the gate by default - the lockstep is enforced).
CMD_STATUSES = ("ok", "missing_file", "missing_interp", "syntax_fail",
                "crashed", "unsafe_skipped", "timeout", "unverified")
CMD_STATUSES_PASS = frozenset(
    {"ok", "timeout", "unsafe_skipped", "unverified"})
# the complement - outcomes that break the gate (the "N broken" count)
CMD_STATUSES_BROKEN = frozenset(CMD_STATUSES) - CMD_STATUSES_PASS


def check_status(status: str) -> str:
    """The one gate on the status vocabulary: a CmdResult's status is only
    ever one of CMD_STATUSES. Reject anything else where the value is
    parsed (CmdResult construction) so a bad literal fails at its own
    site instead of rendering '?' and exiting 0 on a broken skill."""
    if status not in CMD_STATUSES:
        raise ValueError(
            f"unknown command status {status!r}; want one of {CMD_STATUSES}")
    return status


@dataclass
class CmdResult:
    skill: str
    line: int
    command: str
    status: str          # one of CMD_STATUSES - enforced in __post_init__
    detail: str = ""

    def __post_init__(self) -> None:
        self.status = check_status(self.status)


@dataclass
class SmokeReport:
    results: list[CmdResult] = field(default_factory=list)

    def counts(self) -> dict:
        c: dict[str, int] = {}
        for r in self.results:
            c[r.status] = c.get(r.status, 0) + 1
        return c


def _strip_comment(cmd: str) -> str:
    """Drop a trailing shell comment (` # note`) - not part of the command."""
    return re.split(r"\s+#\s", cmd, maxsplit=1)[0].rstrip(" \\")


def _tokens(cmd: str) -> list[str]:
    try:
        return shlex.split(cmd, posix=True)
    except ValueError:            # unbalanced quotes in a doc snippet
        return cmd.split()


def _invoked_files(cmd: str) -> list[str]:
    """The script file a command line executes - not every argument that
    happens to end in `.py` (`-p test_*.py`, data files, comment text).

    `python -m mod` / `python -c code` run no file; `powershell -File x.ps1`
    names its script after `-File`; `./x.sh` runs itself."""
    toks = _tokens(_strip_comment(cmd))
    if not toks:
        return []
    first = toks[0]
    if first.startswith(("./", ".\\")):
        return [first[2:]] if Path(first).suffix.lower() in SCRIPT_EXT else []
    name = Path(first).name.lower().removesuffix(".exe")
    rest = toks[1:]
    if name in ("powershell", "pwsh"):
        for i, t in enumerate(rest[:-1]):
            if t.lower() in ("-file", "-f"):
                return [rest[i + 1]]
        return []
    if name in ("deno", "bun") and rest[:1] == ["run"]:
        rest = rest[1:]
    elif name == "uv" and rest[:1] == ["run"]:
        rest = rest[1:]
    elif name not in _SCRIPT_RUNNERS:
        return []
    for t in rest:
        if t in ("-m", "-c", "-e", "--eval"):
            return []             # module / inline code - no script file
        if t.startswith("-"):
            continue              # interpreter option (py -3.12, node --inspect)
        if Path(t).suffix.lower() in SCRIPT_EXT:
            return [t.removeprefix("./").removeprefix(".\\")]
        return []                 # first positional isn't a script path
    return []


def _resolve_script(skill: Skill, ref: str) -> tuple[Path | None, bool]:
    """(path-if-found, checkable). A skill-dir placeholder resolves against
    the skill dir; other placeholders (`<repo>/x.py`, `$HOME/x.py`) can't be
    checked statically. Plain relative paths are tried from the skill dir up
    through its ancestors to just above the scan root (a library-relative
    command like `python tools/x.py` runs from the repo root), then from any
    declared workspace."""
    m = SKILL_DIR_TOKEN_RE.match(ref)
    if m:
        p = skill.dir / ref[m.end():]
        return (p if p.exists() else None), True
    if re.search(r"[<>$%{}]|^~", ref):
        return None, False
    p = Path(ref)
    if p.is_absolute():
        return (p if p.exists() else None), True
    bases: list[Path] = []
    d = skill.dir
    while True:
        bases.append(d)
        if d == skill.root.parent or d.parent == d:
            break
        d = d.parent
    meta = skill.meta.get("metadata")
    meta = meta if isinstance(meta, dict) else {}
    ws = skill.meta.get("workspace") or meta.get("workspace")
    for w in (ws if isinstance(ws, list) else [ws]):
        if isinstance(w, str) and w:
            wp = Path(w).expanduser()
            bases.append(wp if wp.is_absolute() else skill.dir / wp)
    for b in bases:
        if (b / ref).exists():
            return (b / ref), True
    return None, True


def check_command(skill: Skill, line: int, cmd: str,
                  env: Environment, run: bool) -> CmdResult:
    toks = cmd.split()
    if not toks:
        return CmdResult(skill.slug, line, cmd, "ok", "empty")
    first = toks[0]

    if first.startswith(("./", ".\\")):
        pass  # direct script invocation; file check below covers it
    elif not env.has(first) and not shutil.which(first):
        # env.has covers the probed interpreters/CLIs (and rejects Store
        # stubs); which() covers everything else actually on PATH
        return CmdResult(skill.slug, line, cmd, "missing_interp",
                         f"`{first}` not on PATH")
    elif first in env.interpreters and not env.has(first):
        return CmdResult(skill.slug, line, cmd, "missing_interp",
                         f"`{first}` is on PATH but does not run (stub?)")

    scripts = _invoked_files(cmd)
    resolved: list[Path] = []
    for f in scripts:
        path, checkable = _resolve_script(skill, f)
        if not checkable:
            return CmdResult(skill.slug, line, cmd, "unverified",
                             f"placeholder path not checked: {f}")
        if path is None:
            return CmdResult(skill.slug, line, cmd, "missing_file",
                             f"not found: {f}")
        resolved.append(path)

    # static compile check for python scripts we can see - builtin compile()
    # so no __pycache__ is written into the audited skill and no interpreter
    # is needed (PATH `python` may be a stub anyway)
    for fp in resolved:
        if fp.suffix == ".py" and fp.is_file():
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
        for line, cmd in _commands(s.body, s.body_offset):
            if cmd in seen:
                continue
            seen.add(cmd)
            rep.results.append(check_command(s, line, cmd, env, run))
    return rep
