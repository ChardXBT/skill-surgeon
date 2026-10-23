"""Open-weight semantic analysis via a local Ollama model.

Everything here degrades gracefully: no server, missing model, or bad JSON
just means the semantic checks are skipped - never a crash, never a cloud call.
"""

from __future__ import annotations

import json
import re
import urllib.request
import urllib.error

from .model import Skill

DEFAULT_MODEL = "gemma4:e4b"
DEFAULT_HOST = "http://localhost:11434"


class OllamaClient:
    def __init__(self, model: str = DEFAULT_MODEL, host: str = DEFAULT_HOST,
                 timeout: int = 180):
        self.model, self.host, self.timeout = model, host.rstrip("/"), timeout

    def available(self) -> tuple[bool, str]:
        try:
            with urllib.request.urlopen(f"{self.host}/api/tags", timeout=4) as r:
                tags = json.loads(r.read())
        except Exception as e:
            return False, f"Ollama unreachable at {self.host} ({e})"
        names = [m.get("name", "") for m in tags.get("models", [])]
        base = self.model.split(":", 1)[0]
        if self.model in names or any(n.split(":", 1)[0] == base for n in names):
            return True, "ok"
        return False, f"model `{self.model}` not pulled (have: {', '.join(names) or 'none'})"

    def generate(self, prompt: str) -> str:
        payload = json.dumps({
            "model": self.model, "prompt": prompt, "stream": False,
            "format": "json", "options": {"temperature": 0.2},
        }).encode()
        req = urllib.request.Request(f"{self.host}/api/generate", data=payload,
                                     headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=self.timeout) as r:
            return json.loads(r.read()).get("response", "")


def extract_json(text: str):
    """Pull the first JSON object/array out of model output."""
    text = text.strip()
    try:
        return json.loads(text)
    except Exception:
        pass
    for open_c, close_c in (("{", "}"), ("[", "]")):
        i, j = text.find(open_c), text.rfind(close_c)
        if i != -1 and j > i:
            try:
                return json.loads(text[i : j + 1])
            except Exception:
                continue
    m = re.search(r"```(?:json)?\s*([\[{].*[\]}])\s*```", text, re.S)
    if m:
        try:
            return json.loads(m.group(1))
        except Exception:
            pass
    return None


_ANALYZE_PROMPT = """You are auditing an agent-skill library. Each skill below has a trigger
`description` that routers use to decide when to load the skill.

SKILLS:
{listing}

TASK - return ONE JSON object, no prose:
{{
  "collisions": [
    {{"a": <index>, "b": <index>, "reason": "<why they would compete for the same request>",
      "confidence": "high|medium|low",
      "suggest_a": "<rewritten description for a, sharpened to remove overlap>",
      "suggest_b": "<rewritten description for b, sharpened to remove overlap>"}}
  ],
  "descriptions": [
    {{"idx": <index>, "quality": <0-10>,
      "issues": ["<what is missing: e.g. no 'use when' trigger, vague verbs, no domain>"],
      "suggested": "<improved description, <=400 chars, third person, states WHAT it does and WHEN to use it>"}}
  ]
}}

Rules:
- Refer to skills ONLY by their index number, never by name.
- Two entries with the same name are a known duplicate issue - do NOT report them as a collision.
- Only list collisions between DIFFERENTLY-named skills you are at least medium-confidence about; omit the key if none.
- Only include a description entry if quality < 7 or it is missing a clear WHAT or WHEN; omit the key if none.
- A good description names the domain, the action, and the trigger conditions (e.g. "Use when...", "Use for...").
- Keep suggested descriptions faithful: same scope, no invented features.
- Output JSON only."""


def analyze(client: OllamaClient, skills: list[Skill]) -> dict:
    """One model call -> {collisions: [...], descriptions: [...]}
    Skills are referenced by index and mapped back to names here."""
    listing = "\n".join(
        f'[{i}] name: {s.slug}\n    description: {s.description or "(missing)"}'
        for i, s in enumerate(skills)
    )
    prompt = _ANALYZE_PROMPT.format(listing=listing)
    try:
        data = extract_json(client.generate(prompt))
    except Exception:
        return {}
    if not isinstance(data, dict):
        return {}

    def _name(x):
        try:
            return skills[int(x)].slug
        except (ValueError, TypeError, IndexError):
            return None

    out = {"collisions": [], "descriptions": []}
    for col in data.get("collisions") or []:
        if not isinstance(col, dict):
            continue
        a, b = _name(col.get("a")), _name(col.get("b"))
        if a and b and a != b:
            col["a"], col["b"] = a, b
            out["collisions"].append(col)
    for d in data.get("descriptions") or []:
        if not isinstance(d, dict):
            continue
        nm = _name(d.get("idx", d.get("name")))
        if nm:
            d["name"] = nm
            out["descriptions"].append(d)
    return out


_DRAFT_PROMPT = """Write a `description` frontmatter value for the agent skill below.
One line, <=400 chars, third person, states WHAT it does and WHEN to trigger it
("Use when...", "Use for..."). Return JSON: {{"description": "..."}}

name: {name}

SKILL.md body (truncated):
{body}"""


def draft_description(client: OllamaClient, skill: Skill) -> str | None:
    try:
        data = extract_json(client.generate(
            _DRAFT_PROMPT.format(name=skill.slug, body=skill.body[:1800])))
    except Exception:
        return None
    if isinstance(data, dict) and isinstance(data.get("description"), str):
        d = " ".join(data["description"].split())
        return d[:1024] if d else None
    return None


_CONDENSE_PROMPT = """Condense this skill trigger description to <=900 chars while
keeping domain, action, and trigger conditions. Return JSON: {{"description": "..."}}

description: {desc}"""


def condense_description(client: OllamaClient, desc: str) -> str | None:
    try:
        data = extract_json(client.generate(_CONDENSE_PROMPT.format(desc=desc[:3000])))
    except Exception:
        return None
    if isinstance(data, dict) and isinstance(data.get("description"), str):
        d = " ".join(data["description"].split())
        return d if d else None
    return None
