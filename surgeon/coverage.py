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


def _tokens(text: str) -> set[str]:
    return {t for t in re.findall(r"[a-z0-9]+", text.lower())
            if t not in STOP and len(t) > 2}


def _jaccard(a: set, b: set) -> float:
    return len(a & b) / len(a | b) if a and b else 0.0


def coverage(skills: list[Skill], client=None) -> CoverageReport:
    rep = CoverageReport()
    toks = {s.slug: _tokens(s.description or "") for s in skills}

    for s in skills:
        if s.description and not TRIGGER_RE.search(s.description):
            rep.no_trigger.append(s.slug)

    names = list(toks)
    for i, a in enumerate(names):
        for b in names[i + 1:]:
            if a == b:
                continue
            j = _jaccard(toks[a], toks[b])
            if j >= 0.30:
                rep.similar_pairs.append((a, b, round(j, 2)))

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
