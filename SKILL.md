---
name: skill-surgeon
description: Audit an agent-skill library (SKILL.md files) for spec violations, dead references, secrets, non-portable paths, duplicate names, and trigger-description collisions, then propose and apply repairs one fix at a time with operator approval. Use when asked to review, lint, doctor, clean up, maintain, or improve a skills directory, when skills conflict or fail to trigger, or before sharing/publishing skills.
metadata:
  generates:
    - surgery-plan.json
    - surgery-log.md
---

# Skill Surgeon

Keep an agent's skill library healthy. Diagnose with deterministic checks plus an open-weight local model (Ollama), then repair - every change is proposed as an exact diff and applied only after the human approves it.

## Setup

The engine is the Python package beside this file:

- `python -m surgeon <command>` - run from the skill root, or add the `surgeon/` package directory to `PYTHONPATH`.
- Optional local model: Ollama serving an open-weight model (default `gemma4:e4b`, override with `--model`). If unreachable, scans degrade to structural-only mode - never a hard failure, never a cloud call.

## Procedure

1. **Discover roots.** If the user gives paths, use them. Otherwise auto-discovery covers `.agents/skills`, `.claude/skills`, `.devin/skills`, `.codex/skills`, `.cursor/skills` under the cwd and the home directory. Scan ALL roots the user cares about so duplicate-name checks see everything.
2. **Scan + plan:**
   `python -m surgeon scan <roots...> --plan surgery-plan.json --md report.md`
   Review the terminal report. Read `surgery-plan.json` - each fix carries exact `find`/`replace` strings.
3. **Present for approval.** Show each proposed fix as a diff (id, skill, rule, rationale, before/after). Group by skill if long. NEVER apply a fix the operator has not approved. Bulk approval ("apply all", "apply F-001..F-004") is fine once the operator sees the list.
4. **Apply approved fixes:**
   `python -m surgeon apply --plan surgery-plan.json --ids F-001,F-003`
   Or make the edits directly with your edit tools using the plan's find/replace strings. Either way, treat `manual` fixes as discussion items - never auto-apply.
5. **Verify.** Re-run `scan` and report the score delta. If a fix introduced a regression (e.g., a new dead reference), surface it and offer to revert.

## Hard rules

- No operator approval, no edits. Report-only by default.
- Never delete or move a skill directory yourself - propose it as a `manual` fix instead.
- Never print a matched secret literal in chat; refer to it by finding id. Rotation advice goes in the surgery log.
- Frontmatter edits only unless the fix's `find`/`replace` is in the plan. Body edits are always operator-approved individually.
- Re-scan after applying. `surgery-log.md` records every decision (applied/skipped/failed + rationale).

## Commands

| Command | Purpose |
|---|---|
| `scan [paths]` | Audit, print report, write `surgery-plan.json`, optional `--md`/`--json`/`--ci` |
| `fix [paths]` | Scan then interactively approve/apply in the terminal |
| `apply` | Apply chosen fix ids from a plan file (`--ids` / `--all`) |
| `tailor [paths]` | Find host-environment mismatches (.claude paths, `python3`, POSIX tools) and propose rewrites; `--for <platform>` ports conventions |
| `test [paths]` | Smoke-test documented commands: interpreter present, file exists, compiles; `--run` executes behind a denylist with secrets scrubbed from env |
| `watch [paths]` | Flag skills whose declared `metadata.workspace` repos changed since `metadata.verified_at` |
| `adopt [paths]` | Stamp `metadata.workspace` + `verified_at` so `watch` has a baseline; `--yes` writes, `--workspace` declares a repo |
| `coverage [paths]` | Routing map: skills without trigger phrasing, description overlap (local embeddings when available, token overlap otherwise), uncovered intents |
| `diff <baseline> [paths]` | Compare current health to a `scan --save-baseline` snapshot: new / resolved / unchanged findings and score delta |
| `badge [paths]` | Print a README score badge |
| `rules` | List all rule ids and what they check |

Exit codes: `0` clean/warnings, `1` errors present, `3` usage/IO error - usable as a CI gate.

## Beyond the audit

- **Tailor before trusting**: a skill authored for another platform fails in ways a scan can't see; run `tailor` on newly installed skills, and `test --run` when behavior matters.
- **Adopt to enable watch**: `watch` needs `metadata.workspace` + `verified_at`; `adopt --yes` stamps today after a clean scan, `adopt --workspace <repo>` declares the repo it monitors.
- **Diff proves direction**: `scan --save-baseline s.json` once, then `diff s.json` shows whether the library is getting healthier or decaying.
- **Confidence labels**: fixes tagged `[review]` use fuzzy or model-guessed targets - look at those diffs hard; the rest are deterministic rewrites.
- **Coverage maps routing**: a skill with no "use when" phrasing may never fire; overlap pairs predict router confusion (embedding-based when `nomic-embed-text` is pulled).

## What the checks mean

`S001-S012` are deterministic (spec fields, dead refs, duplicates, secrets, injection patterns, portability). `Q001-Q002` run on the local model: trigger collisions between differently-named skills, and description quality with suggested rewrites. A healthy skill scores 90+.
