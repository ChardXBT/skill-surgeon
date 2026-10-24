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
    if i >= len(lines) or lines[i].strip().lstrip("\ufeff") != "---":
        return None, text, -1, -1
    j = i + 1
    while j < len(lines):
        if lines[j].strip() in ("---", "..."):
            return "\n".join(lines[i + 1 : j]), "\n".join(lines[j + 1 :]), i, j
        j += 1
    # opening fence but no closing fence
    return None, text, i, -1


def _manual_parse(fm: str) -> dict:
    """Lenient frontmatter parse: top-level scalars, block scalars (| >),
    one level of nested maps/lists, and folded scalar continuations.

    Used only when PyYAML is absent - must produce the same SHAPES yaml
    would (nested dicts, lists) or downstream .get() calls see strings.
    """
    meta: dict = {}
    lines = fm.splitlines()
    i = 0
    while i < len(lines):
        line = lines[i]
        if not line.strip() or line[0] in " \t" or ":" not in line:
            i += 1
            continue
        k, _, v = line.partition(":")
        key, v = k.strip(), v.strip()

        if v in ("|", ">", "|-", ">-", "|+", ">+"):      # block scalar
            i += 1
            buf = []
            while i < len(lines) and (lines[i][:1] in " \t" or not lines[i].strip()):
                if lines[i].strip():
                    buf.append(lines[i].strip())
                i += 1
            meta[key] = "\n".join(buf) if v.startswith("|") else " ".join(buf)
        elif v:
            meta[key] = v                                # plain scalar
            i += 1
        else:
            # empty value: nested block or folded continuation follows
            i += 1
            children: list[tuple[int, str]] = []
            while i < len(lines) and (lines[i][:1] in " \t" or not lines[i].strip()):
                if lines[i].strip():
                    children.append((len(lines[i]) - len(lines[i].lstrip()),
                                     lines[i].strip()))
                i += 1
            if not children:
                meta[key] = ""
                continue
            ind0 = min(c[0] for c in children)
            lvl0 = [s for ind, s in children if ind == ind0]
            if all(s.startswith(("- ", "-\t")) for s in lvl0):
                meta[key] = [s[2:].strip() for s in lvl0]
            elif all(":" in s for s in lvl0):
                m: dict = {}
                cur = ""
                for ind, s in children:
                    if ind == ind0:
                        kk, _, vv = s.partition(":")
                        cur = kk.strip()
                        m[cur] = vv.strip()
                    elif cur and s.startswith(("- ", "-\t")):
                        m[cur] = (m[cur] if isinstance(m.get(cur), list) else [])
                        m[cur].append(s[2:].strip())
                    elif cur and ":" in s:
                        kk, _, vv = s.partition(":")
                        m[cur] = (m[cur] if isinstance(m.get(cur), dict) else {})
                        m[cur][kk.strip()] = vv.strip()
                    elif cur and isinstance(m.get(cur), str):
                        m[cur] = (m[cur] + " " + s).strip()
                meta[key] = m
            else:
                meta[key] = " ".join(s for _, s in children)  # folded scalar
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


def _flow_map_items(value: str) -> list[str] | None:
    """`{a: 1, b: 2}` -> ['a: 1', 'b: 2']; None when not a flow map."""
    v = value.strip()
    if v.startswith("{") and v.endswith("}"):
        inner = v[1:-1].strip()
        if not inner:
            return []
        items = [x.strip() for x in inner.split(",") if x.strip()]
        # a comma inside a value (e.g. {note: a, b}) isn't a map separator;
        # only treat as flow map when every part looks like `k: v`
        return items if all(":" in x for x in items) else None
    return None


def upsert_metadata(fm_raw: str, key: str, value: str) -> str:
    """Set metadata.<key> = value inside frontmatter text.

    Preserves every other line verbatim. Handles: existing key (replace,
    consuming its continuation children), existing metadata: block (insert
    under it), flow-style metadata: {..} (normalized to a block), no block
    (append one). `value` is written unquoted - callers pass safe scalars.
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
        return "\n".join(list(lines) + ["metadata:", f"  {key}: {value}"])

    # flow-style `metadata: {a: 1}` or a stray scalar - normalize to a block
    inline = lines[meta_idx].split(":", 1)[1].strip()
    if inline:
        items = _flow_map_items(inline)
        block = ["metadata:"] + [f"  {x}" for x in items] if items is not None \
            else ["metadata:"]
        lines[meta_idx:meta_idx + 1] = block

    # scan the metadata block (indented lines after `metadata:`)
    key_re = re.compile(rf"^(\s+){re.escape(key)}\s*:")
    j = meta_idx + 1
    insert_at = j
    while j < len(lines) and (lines[j][:1] in " \t" or not lines[j].strip()):
        if lines[j].strip():
            m = key_re.match(lines[j])
            if m:
                # replace the key line AND swallow its continuation children
                # (list items / folded scalars) so they don't dangle
                end = j + 1
                ind = len(m.group(1))
                while end < len(lines):
                    nxt = lines[end]
                    if not nxt.strip():
                        end += 1
                        continue
                    nind = len(nxt) - len(nxt.lstrip())
                    is_seq = nxt.lstrip().startswith(("- ", "-\t")) and nind >= ind
                    is_deeper = nxt[:1] in " \t" and nind > ind
                    if is_seq or is_deeper:
                        end += 1
                        continue
                    break
                lines[j:end] = [f"{m.group(1)}{key}: {value}"]
                return "\n".join(lines)
            insert_at = j + 1
        j += 1
    lines.insert(insert_at, f"  {key}: {value}")
    return "\n".join(lines)


def rewrite_frontmatter(text: str, updates: dict[str, str]) -> str:
    """Apply metadata upserts to a full SKILL.md text; returns new text.
    Preserves the file's own line endings (CRLF files stay CRLF)."""
    eol = "\r\n" if "\r\n" in text else "\n"
    nl = text.replace("\r\n", "\n").replace("\r", "\n")
    fm_raw, body, fm_start, fm_end = split_frontmatter(nl)
    fm = fm_raw or ""
    for k, v in updates.items():
        fm = upsert_metadata(fm, k, v)
    if fm_start == -1:
        return ("---" + eol + fm.replace("\n", eol) + eol + "---" +
                eol + eol + text)
    lines = nl.splitlines()
    out = "\n".join(lines[:fm_start + 1]) + "\n" + fm + "\n" + \
        "\n".join(lines[fm_end:])
    return out.replace("\n", eol)


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
