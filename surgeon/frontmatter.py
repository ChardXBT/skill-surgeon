"""Lenient SKILL.md frontmatter parsing.

Real-world skills have unquoted colons, folded scalars, BOMs, CRLF, and
occasionally no frontmatter at all. We try PyYAML first, then fall back to
a hand parser so a sloppy file still yields what it can.
"""

from __future__ import annotations

import re

try:
    import yaml  # type: ignore
except Exception:  # pragma: no cover - zero-dep fallback
    yaml = None


def split_frontmatter(text: str) -> tuple[str | None, str, int, int]:
    """Return (fm_raw, body, fm_start, fm_end). fm_* are -1 and fm_raw None
    when there is no frontmatter fence."""
    lines = text.splitlines()
    i = 0
    while i < len(lines) and lines[i].lstrip("\ufeff").strip() == "":
        i += 1
    if i >= len(lines) or lines[i].strip() != "---":
        return None, text, -1, -1
    j = i + 1
    while j < len(lines):
        if lines[j].strip() in ("---", "..."):
            return "\n".join(lines[i + 1 : j]), "\n".join(lines[j + 1 :]), i, j
        j += 1
    # opening fence but no closing fence
    return None, text, i, -1


def _manual_parse(fm: str) -> dict:
    meta: dict = {}
    key = None
    buf: list[str] = []

    def flush():
        nonlocal key, buf
        if key is not None:
            meta[key] = " ".join(x.strip() for x in buf).strip()
        key, buf = None, []

    for line in fm.splitlines():
        if not line.strip():
            continue
        if line[0] in " \t":  # continuation / folded block
            buf.append(line)
            continue
        if ":" in line:
            flush()
            k, _, v = line.partition(":")
            key = k.strip()
            v = v.strip()
            if v in ("|", ">", "|-", ">-", "|+", ">+"):
                buf = []
            elif v:
                buf = [v]
            else:
                buf = []
        else:
            buf.append(line)
    flush()
    return meta


def parse_frontmatter(fm: str) -> tuple[dict, str]:
    """Return (meta, error). error is '' on success."""
    if yaml is not None:
        try:
            data = yaml.safe_load(fm)
            if isinstance(data, dict):
                return data, ""
            return {}, "frontmatter is not a mapping"
        except Exception as e:
            meta = _manual_parse(fm)
            return meta, f"yaml parse failed ({e}); used lenient parser"
    return _manual_parse(fm), ""


def upsert_metadata(fm_raw: str, key: str, value: str) -> str:
    """Set metadata.<key> = value inside frontmatter text.

    Preserves every other line verbatim. Handles: existing key (replace),
    existing metadata: block (insert under it), no block (append one).
    `value` is written unquoted - callers pass already-YAML-safe scalars.
    """
    lines = fm_raw.splitlines()
    meta_idx = None
    for i, line in enumerate(lines):
        if line[:1] in " \t" or ":" not in line:
            continue
        if line.split(":", 1)[0].strip() == "metadata":
            meta_idx = i
            break

    if meta_idx is None:
        out = list(lines) + ["metadata:", f"  {key}: {value}"]
        return "\n".join(out)

    # scan the metadata block (indented lines after `metadata:`)
    key_re = re.compile(rf"^(\s+){re.escape(key)}\s*:")
    j = meta_idx + 1
    insert_at = j
    while j < len(lines) and (lines[j][:1] in " \t" or not lines[j].strip()):
        if lines[j].strip():
            insert_at = j + 1
            if key_re.match(lines[j]):
                indent = key_re.match(lines[j]).group(1)
                lines[j] = f"{indent}{key}: {value}"
                return "\n".join(lines)
        j += 1
    lines.insert(insert_at, f"  {key}: {value}")
    return "\n".join(lines)


def rewrite_frontmatter(text: str, updates: dict[str, str]) -> str:
    """Apply metadata upserts to a full SKILL.md text; returns new text."""
    fm_raw, body, fm_start, fm_end = split_frontmatter(text)
    fm = fm_raw or ""
    for k, v in updates.items():
        fm = upsert_metadata(fm, k, v)
    if fm_start == -1:
        return f"---\n{fm}\n---\n\n" + text
    lines = text.splitlines()
    return "\n".join(lines[:fm_start + 1]) + "\n" + fm + "\n" + \
        "\n".join(lines[fm_end:])


def description_block(fm_raw: str, body_offset: int) -> tuple[int, int] | None:
    """Line span (relative to the FILE, body_offset = first fm line index)
    covering the description key, including folded continuation lines."""
    lines = fm_raw.splitlines()
    for i, line in enumerate(lines):
        if line[:1] in " \t" or ":" not in line:
            continue
        k = line.split(":", 1)[0].strip()
        if k == "description":
            j = i + 1
            while j < len(lines) and lines[j][:1] in " \t" and lines[j].strip():
                j += 1
            return (body_offset + 1 + i, body_offset + 1 + j)  # [start, end) file lines
    return None
