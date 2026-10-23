"""Turn findings + semantic results into concrete, reviewable Fix objects.

Every replace_text fix carries the exact `find`/`replace` strings so applying
it is mechanical and the operator reviews a precise diff - never a vague idea.
"""

from __future__ import annotations

import re
from pathlib import Path

from .frontmatter import description_block
from .model import Finding, Fix, Skill
from .rules_structural import DATE_SUFFIX_RE, NAME_RE, closest_existing
from .semantic import OllamaClient, condense_description, draft_description

_ctr = [0]


def _id() -> str:
    _ctr[0] += 1
    return f"F-{_ctr[0]:03d}"


def _skill_lines(skill: Skill) -> list[str]:
    return skill.raw.split("\n")


def _desc_span(skill: Skill) -> tuple[int, int] | None:
    if skill.fm_start == -1 or skill.fm_end == -1:
        return None
    return description_block(skill.fm_raw, skill.fm_start)


def _replace_line_fix(skill: Skill, rule: str, span: tuple[int, int],
                      new_text: str, rationale: str, auto: bool = True) -> Fix:
    lines = _skill_lines(skill)
    start, end = span
    return Fix(id=_id(), skill=skill.slug, rule=rule, kind="replace_text",
               file=str(skill.path), find="\n".join(lines[start:end]),
               replace=new_text, rationale=rationale, auto=auto)


def _set_frontmatter_field_fix(skill: Skill, rule: str, key: str,
                               value: str, rationale: str) -> Fix | None:
    """Replace an existing `key: ...` block (with continuations) in frontmatter."""
    if skill.fm_start == -1:
        return None
    lines = _skill_lines(skill)
    for i in range(skill.fm_start + 1, skill.fm_end):
        line = lines[i]
        if line[:1] in " \t" or ":" not in line:
            continue
        if line.split(":", 1)[0].strip() == key:
            j = i + 1
            while j < skill.fm_end and lines[j][:1] in " \t" and lines[j].strip():
                j += 1
            return _replace_line_fix(skill, rule, (i, j), f"{key}: {value}", rationale)
    return None


def _insert_frontmatter_field_fix(skill: Skill, rule: str, key: str,
                                  value: str, rationale: str) -> Fix | None:
    """Insert `key: value` as a new frontmatter line (after `name:` if present)."""
    if skill.fm_start == -1:
        return None
    lines = _skill_lines(skill)
    anchor = skill.fm_start  # default: right after opening ---
    for i in range(skill.fm_start + 1, skill.fm_end):
        if lines[i].startswith("name:"):
            anchor = i
    return Fix(id=_id(), skill=skill.slug, rule=rule, kind="replace_text",
               file=str(skill.path), find=lines[anchor],
               replace=f"{lines[anchor]}\n{key}: {value}", rationale=rationale)


def fixes_for_findings(skills: list[Skill], findings: list[Finding],
                       client: OllamaClient | None) -> list[Fix]:
    _ctr[0] = 0
    by_slug = {s.slug: s for s in skills}
    fixes: list[Fix] = []

    for f in findings:
        s = by_slug.get(f.skill)
        if s is None or not f.fixable:
            continue

        if f.rule == "S003":  # name != dir
            fix = _set_frontmatter_field_fix(
                s, "S003", "name", s.dir.name,
                f"rename field to match directory `{s.dir.name}` (alternative: rename the dir)")
            if fix:
                fixes.append(fix)

        elif f.rule == "S004":  # missing description
            drafted = draft_description(client, s) if client else None
            if drafted:
                fix = _insert_frontmatter_field_fix(
                    s, "S004", "description", drafted,
                    "drafted by local model from skill body - review before applying")
                if fix:
                    fixes.append(fix)

        elif f.rule == "S005":  # description too long
            if client:
                short = condense_description(client, s.description or "")
                span = _desc_span(s)
                if short and span:
                    fixes.append(_replace_line_fix(
                        s, "S005", span, f"description: {short}",
                        f"condensed {len(s.description or '')} -> {len(short)} chars by local model"))

        elif f.rule == "S007":  # dead reference -> fuzzy match
            m = re.search(r"`([^`]+)`", f.message)
            if m:
                dead = m.group(1)
                close = closest_existing(dead, s)
                if close:
                    try:
                        raw_at = s.raw.split("\n")[f.line - 1]
                    except IndexError:
                        continue
                    fixes.append(Fix(
                        id=_id(), skill=s.slug, rule="S007", kind="replace_text",
                        file=str(s.path), find=f"`{dead}`", replace=f"`{close}`",
                        rationale=f"dead ref `{dead}` -> closest existing file `{close}` "
                                  f"(line: {raw_at.strip()[:80]})"))

        elif f.rule == "S008":  # absolute path -> relative or placeholder
            m = re.search(r"`([^`]+)`", f.message)
            if m:
                frag = m.group(1).rstrip("\\/")
                p = Path(frag)
                try:
                    rel = p.resolve().relative_to(s.dir.resolve())
                    newref = str(rel).replace("\\", "/")
                except Exception:
                    parts = p.parts
                    anchor = next((i for i, x in enumerate(parts)
                                   if x.lower() in ("users", "home")), None)
                    newref = ("~/" + "/".join(parts[anchor + 2:])) \
                        if anchor is not None and len(parts) > anchor + 2 \
                        else f"<path-to-{p.name}>"
                fixes.append(Fix(
                    id=_id(), skill=s.slug, rule="S008", kind="replace_text",
                    file=str(s.path), find=frag, replace=newref,
                    rationale=f"portable replacement for machine-specific path `{frag}`"))

        elif f.rule == "S010":  # secret -> redact (literal never enters the report)
            from .rules_structural import SECRET_PATTERNS, PLACEHOLDER_HINTS
            literal = ""
            for rx, _label in SECRET_PATTERNS:
                m = rx.search(s.raw)
                if m:
                    val = m.group(1) if m.lastindex else m.group(0)
                    if not any(h in val.lower() for h in PLACEHOLDER_HINTS):
                        literal = val
                        break
            if literal:
                fixes.append(Fix(
                    id=_id(), skill=s.slug, rule="S010", kind="replace_text",
                    file=str(s.path), find=literal, replace="<redacted>",
                    rationale="redact credential literal - rotate it if real"))

        elif f.rule == "S012":  # dated name
            if s.name:
                new_name = DATE_SUFFIX_RE.sub("", s.name)
                if new_name and NAME_RE.match(new_name):
                    fix = _set_frontmatter_field_fix(
                        s, "S012", "name", new_name,
                        f"strip date suffix -> `{new_name}`; NOTE: also rename the "
                        f"directory `{s.dir.name}` -> `{new_name}` to stay spec-consistent")
                    if fix:
                        fixes.append(fix)

        elif f.rule == "S009":  # duplicates -> manual merge proposal
            others = [x for x in f.message.split(":", 1)[-1].split(";") if s.path.as_posix() not in x]
            fixes.append(Fix(
                id=_id(), skill=s.slug, rule="S009", kind="manual",
                file=str(s.path), auto=False,
                rationale=f"duplicate name `{s.slug}` across roots. Pick one canonical "
                          f"location (prefer {s.root}), merge unique content there, then "
                          f"retire the shadow copy. Other locations:{''.join(others)}"))

    return fixes


def fixes_for_semantic(skills: list[Skill], analysis: dict,
                       start_after: int) -> tuple[list[Fix], list[Finding]]:
    """Collision + weak-description findings, and rewrite fixes."""
    by_slug = {s.slug: s for s in skills}
    fixes: list[Fix] = []
    findings: list[Finding] = []

    for col in analysis.get("collisions", []):
        a, b = col.get("a"), col.get("b")
        if a not in by_slug or b not in by_slug:
            continue
        conf = col.get("confidence", "medium")
        msg = (f"trigger collision with `{b}` ({conf}): {col.get('reason', '')}"
               if True else "")
        findings.append(Finding("Q001", "warn" if conf != "high" else "error",
                                a, by_slug[a].path,
                                f"trigger collision with `{b}` ({conf}): {col.get('reason','')}"))
        findings.append(Finding("Q001", "warn" if conf != "high" else "error",
                                b, by_slug[b].path,
                                f"trigger collision with `{a}` ({conf}): {col.get('reason','')}"))
        for key, sugkey in (("a", "suggest_a"), ("b", "suggest_b")):
            sk = by_slug[col[key]]
            other = by_slug[col["b" if key == "a" else "a"]]
            sug = col.get(sugkey)
            span = _desc_span(sk)
            if sug and span:
                fixes.append(_replace_line_fix(
                    sk, "Q001", span, f"description: {' '.join(str(sug).split())}",
                    f"sharpened to remove overlap with `{other.slug}`"))

    for d in analysis.get("descriptions", []):
        sk = by_slug.get(d.get("name"))
        if not sk:
            continue
        issues = "; ".join(d.get("issues", [])) or "weak description"
        findings.append(Finding("Q002", "warn", sk.slug, sk.path,
                                f"description quality {d.get('quality','?')}/10: {issues}"))
        sug, span = d.get("suggested"), _desc_span(sk)
        if sug and span:
            fixes.append(_replace_line_fix(
                sk, "Q002", span,
                f"description: {' '.join(str(sug).split())}",
                f"local-model rewrite (quality {d.get('quality','?')}/10): {issues}"))

    return fixes, findings
