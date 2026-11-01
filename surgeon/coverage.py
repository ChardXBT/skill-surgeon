"""surgeon coverage - library routing/intent map.

Structural rules check each skill alone. This maps the library as a router
sees it: which skills carry trigger phrasing, which descriptions are
too similar to route between (deterministic complement to Q001), and -
with a local model - which user intents the library can't serve at all.
"""

from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass, field

from .discover import is_nested
from .model import Skill

# Trigger phrasing: an explicit condition for loading the skill. "Use when",
# "Use for", "Use before committing", "Invoke when", "Load at session
# start", "Triggers on ...", "when the user asks ...".
TRIGGER_RE = re.compile(
    r"(?i)\b(use (?:it |this(?: skill)? )?(?:when|for|to|this|after|before|if|"
    r"during|whenever|on|at)\b|(?:invoke|load|apply|run|call|activate|trigger)"
    r"(?:s|ed)? (?:it |this )?(?:when|at|for|on|before|after|whenever|by name)\b|"
    r"triggers? (?:when|on|for)|whenever|for requests to|"
    r"when (?:the )?(?:user|you|asked|someone|an agent|a user)\b)")

STOP = {"the", "a", "an", "and", "or", "of", "to", "for", "in", "on", "with",
        "use", "when", "this", "that", "it", "is", "are", "be", "by", "your",
        "you", "skill", "skills", "agent", "file", "files", "via", "as", "at"}


@dataclass
class CoverageReport:
    no_trigger: list[str] = field(default_factory=list)        # never-fire risk
    no_trigger_nested: list[str] = field(default_factory=list)  # parent-routed
    similar_pairs: list[tuple[str, str, float]] = field(default_factory=list)
    uncovered: list[str] = field(default_factory=list)         # model pass
    model_note: str = "off"
    embed_note: str = "off (token overlap)"


def _labels(skills: list[Skill]) -> dict[int, str]:
    """Display label per skill: its name, plus its dir when several skills
    share a name (variants, installed copies) so list entries stay distinct."""
    counts = Counter(s.slug for s in skills)
    out: dict[int, str] = {}
    for i, s in enumerate(skills):
        if counts[s.slug] > 1:
            try:
                where = s.dir.relative_to(s.root).as_posix()
            except ValueError:
                where = s.dir.name
            out[i] = f"{s.slug} ({where})"
        else:
            out[i] = s.slug
    # the same skill installed under several roots: qualify with the root
    again = Counter(out.values())
    for i, s in enumerate(skills):
        if again[out[i]] > 1:
            root = f"{s.root.parent.name}/{s.root.name}"
            try:
                where = f"{root}/{s.dir.relative_to(s.root).as_posix()}"
            except ValueError:
                where = s.dir.as_posix()
            out[i] = f"{s.slug} ({where})"
    return out


def _tokens(text: str) -> set[str]:
    return {t for t in re.findall(r"[a-z0-9]+", text.lower())
            if t not in STOP and len(t) > 2}


def _jaccard(a: set, b: set) -> float:
    return len(a & b) / len(a | b) if a and b else 0.0


def _embed_pairs(client, skills: list[Skill],
                 labels: dict[int, str] | None = None
                 ) -> list[tuple[str, str, float]] | None:
    """Cosine-similar pairs via local embeddings; None when unavailable."""
    try:
        import json
        import math
        import urllib.request
        payload = json.dumps({
            "model": "nomic-embed-text",
            "input": [f"{s.slug}: {s.description or ''}" for s in skills],
        }).encode()
        req = urllib.request.Request(
            f"{client.host}/api/embed", data=payload,
            headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=30) as r:
            vecs = json.loads(r.read()).get("embeddings", [])
        if len(vecs) != len(skills):
            return None
        def cos(a, b):
            d = math.sqrt(sum(x * x for x in a)) * math.sqrt(sum(x * x for x in b))
            return sum(x * y for x, y in zip(a, b)) / d if d else 0.0
        out = []
        for i in range(len(skills)):
            for j in range(i + 1, len(skills)):
                if skills[i].slug == skills[j].slug:
                    continue
                sim = cos(vecs[i], vecs[j])
                if sim >= 0.72:   # embedding-space overlap, not token overlap
                    lab = labels or {}
                    out.append((lab.get(i, skills[i].slug), lab.get(j, skills[j].slug),
                                round(sim, 2)))
        return out
    except Exception:
        return None


def coverage(skills: list[Skill], client=None) -> CoverageReport:
    rep = CoverageReport()
    labels = _labels(skills)
    # keyed by index: variants share a name, and a slug key would let the
    # last variant silently overwrite the others
    toks = [_tokens(s.description or "") for s in skills]

    for i, s in enumerate(skills):
        if s.description and not TRIGGER_RE.search(s.description):
            # a family sub-skill (`<pack>/skills/<name>/SKILL.md`) is picked
            # by its parent's router, not by host description matching
            (rep.no_trigger_nested if is_nested(s) else rep.no_trigger
             ).append(labels[i])

    jaccard_pairs: list[tuple[str, str, float]] = []
    for i in range(len(skills)):
        for k in range(i + 1, len(skills)):
            if skills[i].slug == skills[k].slug:
                continue
            j = _jaccard(toks[i], toks[k])
            if j >= 0.30:
                jaccard_pairs.append((labels[i], labels[k], round(j, 2)))

    embed_pairs = _embed_pairs(client, skills, labels) if client is not None else None
    if embed_pairs is not None:
        rep.similar_pairs = embed_pairs
        rep.embed_note = "on (nomic-embed-text)"
    else:
        rep.similar_pairs = jaccard_pairs
        rep.embed_note = "off (token overlap)"

    if client is not None:
        listing = "\n".join(f"- {s.slug}: {(s.description or '')[:160]}"
                            for s in skills)
        try:
            from .semantic import extract_json
            data = extract_json(client.generate(
                "Here are agent skills with their trigger descriptions:\n"
                + listing +
                "\n\nList up to 8 concrete user intents this library does NOT "
                "cover at all (gaps where no skill would route). "
                "JSON only: {\"uncovered\": [\"intent\", ...]}"))
            if isinstance(data, dict):
                rep.uncovered = [str(x) for x in data.get("uncovered", [])][:8]
                rep.model_note = "on"
            else:
                rep.model_note = "model returned no usable JSON"
        except Exception as e:
            rep.model_note = f"failed ({e})"
    return rep
