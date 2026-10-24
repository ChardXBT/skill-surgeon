"""surgeon coverage - library routing/intent map.

Structural rules check each skill alone. This maps the library as a router
sees it: which skills carry trigger phrasing, which descriptions are
too similar to route between (deterministic complement to Q001), and -
with a local model - which user intents the library can't serve at all.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from .model import Skill

TRIGGER_RE = re.compile(
    r"(?i)\b(use (?:when|for|to|this)|triggers? (?:when|on)|"
    r"whenever|for requests to)\b")

STOP = {"the", "a", "an", "and", "or", "of", "to", "for", "in", "on", "with",
        "use", "when", "this", "that", "it", "is", "are", "be", "by", "your",
        "you", "skill", "skills", "agent", "file", "files", "via", "as", "at"}


@dataclass
class CoverageReport:
    no_trigger: list[str] = field(default_factory=list)        # never-fire risk
    similar_pairs: list[tuple[str, str, float]] = field(default_factory=list)
    uncovered: list[str] = field(default_factory=list)         # model pass
    model_note: str = "off"
    embed_note: str = "off (token overlap)"


def _tokens(text: str) -> set[str]:
    return {t for t in re.findall(r"[a-z0-9]+", text.lower())
            if t not in STOP and len(t) > 2}


def _jaccard(a: set, b: set) -> float:
    return len(a & b) / len(a | b) if a and b else 0.0


def _embed_pairs(client, skills: list[Skill]) -> list[tuple[str, str, float]] | None:
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
                    out.append((skills[i].slug, skills[j].slug, round(sim, 2)))
        return out
    except Exception:
        return None


def coverage(skills: list[Skill], client=None) -> CoverageReport:
    rep = CoverageReport()
    toks = {s.slug: _tokens(s.description or "") for s in skills}

    for s in skills:
        if s.description and not TRIGGER_RE.search(s.description):
            rep.no_trigger.append(s.slug)

    names = list(toks)
    jaccard_pairs: list[tuple[str, str, float]] = []
    for i, a in enumerate(names):
        for b in names[i + 1:]:
            if a == b:
                continue
            j = _jaccard(toks[a], toks[b])
            if j >= 0.30:
                jaccard_pairs.append((a, b, round(j, 2)))

    embed_pairs = _embed_pairs(client, skills) if client is not None else None
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
