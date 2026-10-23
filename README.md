# skill-surgeon

**Linters tell you your skills are broken. This one fixes them.**

Point it at a folder of `SKILL.md` files. It finds the problems — dead
references, duplicate names, secrets, machine-locked paths, colliding
triggers — proposes each repair as an exact diff, waits for your approval,
applies it, then re-scans to prove the library got healthier.

Semantic analysis runs on a **local open-weight model** via Ollama.
Your skills describe your infrastructure — auditing them shouldn't mean
sending them to a cloud API. (No Ollama? Deterministic checks still run.)

```bash
python -m surgeon scan ~/.agents/skills    # health report + surgery-plan.json
python -m surgeon fix  ~/.agents/skills    # approve each diff, apply, re-verify
```

Zero dependencies. Python 3.9+ stdlib only.

## The loop

```
scan ──► review diffs ──► approve ──► apply ──► re-scan
           (nothing edits                              (score delta
            without a yes)                              proves it worked)
```

Every proposed fix is an exact `find`/`replace` string in `surgery-plan.json`
— reviewable, skippable, idempotent. Decisions land in `surgery-log.md`.

## What it checks

**Deterministic — 12 rules bound to the agentskills.io spec**

- frontmatter validity · name/description rules · name↔dir mismatch
- oversized skills (context bloat) · dead bundled references
- hardcoded `C:\Users\…` paths · secrets · prompt-injection patterns
- duplicate names (identical deploy copies → info, divergent → error)
- date-stamped names like `foo-2026-06-22`

**Local-model — 2 semantic rules**

- **trigger collisions** — differently-named skills competing for the same
  requests, each with a suggested sharper description
- **description quality** — scored 0–10 with a proposed rewrite

It also understands real libraries: `metadata.workspace` declares where
cross-repo references live, `metadata.generates` lists files a skill
produces at runtime, and same-name agent *variants* under a shared
`variants/` dir are recognized as intentional.

## It's a skill, too

Drop the repo into `.agents/skills/` (or `.claude/skills/`). The bundled
`SKILL.md` teaches any agent the audit → approve → apply → verify loop, so
your agent can maintain its own library. Meta, on purpose.

## Proof

We ran it on three real libraries — artifacts in `examples/`:

**The author's production library** — 45 skills, 4 roots, end-to-end with
the approval gate on: found duplicated deploy copies, a machine-locked
OneDrive path, a dated skill name, and 9 references to files deleted from a
target repo. Score **84 → 93/100, 0 errors**.
(`before-report.md` · `after-report.md` · `surgery-log.md`)

**The internet's biggest skill collection** — 1,340 skills scanned:
**495 errors** including skills shipping references to files that were never
published. (`internet-scan` in `examples/`)

**A controlled A/B test** — repaired a popular UI-design skill's 3 real
defects (10 commands pointing at `.claude/`-only paths, a wrong-path data
reference, a Windows console crash), then ran both variants agent-faithful.
Original failed twice and improvised a generic gradient page; repaired
skill's design-system engine drove a coherent page. Screenshots, protocol
and patch in `examples/ab-benchmark/`.

**The gate earned its keep.** On the first live run, the fuzzy matcher
proposed 11 fixes — 3 were wrong and operator review refused them. Approval
isn't decoration.

## Install & commands

```bash
git clone https://github.com/ChardXBT/skill-surgeon && cd skill-surgeon
python -m surgeon scan examples/demo-skills   # try the broken fixtures
python -m surgeon rules                        # all 14 rules
python -m surgeon apply --plan surgery-plan.json --ids F-001,F-003
```

Semantic pass: install [Ollama](https://ollama.com), pull any model,
`--model` to override the `gemma4:e4b` default.

## Safety

- Report-only by default — **no edit lands without approval**
- Never deletes or moves a skill dir
- Secret literals are redacted in fixes, never echoed in reports
- Placeholder-aware: `your-api-key`, `${TOKEN}`, `YYYY-MM-DD` don't flag

MIT · contributions welcome
