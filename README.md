# skill-surgeon

**The agent-skill repair loop, closed.** Every linter tells you your `SKILL.md`
files are broken. Skill Surgeon *fixes* them — proposing each repair as an
exact diff, applying it only after a human approves it, then re-scanning to
prove the library got healthier.

All semantic analysis runs on an **open-weight local model** (Ollama).
Your skills describe your private infrastructure — auditing them should never
mean shipping them to a cloud API.

```
surgeon scan ~/.agents/skills          → health report + surgery-plan.json
surgeon fix  ~/.agents/skills          → approve each diff, apply, re-verify
```

## Why it exists

Agent skills went mainstream fast (Agent Skills spec, `.claude/skills`,
`.agents/skills`, `.devin/skills`) — and every library quietly rots:
descriptions collide, files drift, duplicates pile up, secrets leak in.
Linters exist. **Nothing else performs the surgery.** And the tools that do
use LLMs send your skills to a cloud provider.

Skill Surgeon is different on both axes:

| | diagnoses | fixes | semantic checks | is itself a skill |
|---|---|---|---|---|
| linters (skill-tools, skilllint, skillmark…) | ✅ | ~6 trivial rules | ❌ or cloud-only | ❌ |
| **skill-surgeon** | ✅ | **approval-gated apply + re-verify** | **✅ local open-weight** | **✅** |

## What it checks

**Deterministic (S-rules)** — bound to the agentskills.io spec, so they don't decay:

| Rule | Sev | Catches |
|---|---|---|
| S001–S004 | error | missing/invalid frontmatter, name, or description |
| S005–S006 | warn | oversized description / body (context bloat) |
| S007 | error/warn | dead bundled refs vs unverified runtime refs |
| S008 | warn | hardcoded `C:\Users\…`, `/home/…` paths |
| S009 | error | duplicate skill names across roots |
| S010 | error | credential literals (placeholders excluded) |
| S011 | error/warn | prompt-injection phrasing, `curl\|sh` patterns |
| S012 | info | date-stamped names (`foo-2026-06-22`) |

**Open-weight (Q-rules)** — local model, index-referenced output:

- **Q001 trigger collisions** — differently-named skills that compete for the
  same requests, each with a *sharpened* suggested description.
- **Q002 description quality** — scored 0–10 with issues and a rewrite.

## The loop

1. `scan` → findings + `surgery-plan.json` (exact `find`/`replace` strings per fix)
2. operator reviews diffs — `fix` interactively, or an agent presents them via the bundled `SKILL.md`
3. `apply --ids F-001,F-003` → edits land, `surgery-log.md` records every decision
4. re-scan → score delta proves it worked

## It's a skill, too

Drop this directory into `.agents/skills/` (or `.claude/skills/`). The bundled
`SKILL.md` teaches any agent the audit → approve → apply → verify loop, so your
agent can maintain its own library. Meta, on purpose.

## Real-world proof

Audited a live 18-skill production library — the author's own — end to end,
with the approval gate engaged. Full artifacts in `examples/`
(`before-report.md`, `after-report.md`, `surgery-log.md`):

- **Found real breakage:** 2 skills silently duplicated across two roots
  (undefined which one routes), a machine-locked `C:\Users\…\OneDrive` path,
  a date-stamped skill name, an oversized 7.3k-token skill.
- **Applied 2 approved fixes**, re-scanned, verified clear.
- **Rejected 3 of its own proposals.** The fuzzy matcher wanted to point
  `hourly.md` → `assets/hourly-mode.md` — but the file lives in a *different*
  repo and the doc already said so. Operator review caught it. The gate isn't
  decoration: 3 of 11 proposals were wrong and got refused.
- **Itself passes:** scanning skill-surgeon's own SKILL.md scores 97/100.

## Install & use

```bash
# zero dependencies — Python 3.9+ stdlib only
git clone <repo> && cd skill-surgeon
python -m surgeon scan examples/demo-skills        # try the fixtures
python -m surgeon scan ~/.claude/skills            # your real library
python -m surgeon fix  ~/.claude/skills            # interactive surgery
python -m surgeon rules                            # all 14 rules
```

Semantic pass needs [Ollama](https://ollama.com) with any model pulled
(`--model` to override the `gemma4:e4b` default). Without it, structural
checks still run — nothing ever calls the cloud.

## Safety

- report-only by default; **no edit lands without approval**
- never deletes/moves a skill dir (manual proposals only)
- secret literals are redacted in fixes, never echoed in reports
- placeholder-aware: `your-api-key`, `${TOKEN}`, `YYYY-MM-DD` templates don't false-positive

MIT · contributions welcome
