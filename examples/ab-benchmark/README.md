# A/B Benchmark — does the repaired skill actually perform better?

Controlled test: two identical agent sessions, one with the upstream skill,
one with the skill-surgeon repair. Same model, same prompt, same task.

## Subject: `ui-ux-pro-max`

Source: [`mit-network/antigravity-awesome-skills`](https://github.com/mit-network/antigravity-awesome-skills)
(`skills/ui-ux-pro-max`, community-sourced). A UI design-intelligence skill:
BM25 search over 20 CSVs of palettes, typography, styles, landing patterns and
UX rules; emits a complete recommended design system for a product brief.

**What the audit found:**

| Defect | Effect on the agent |
|---|---|
| 10 commands hardcoded to `.claude/skills/ui-ux-pro-max/scripts/search.py` | Every documented command fails when the skill is installed anywhere else (`.agents/skills`, `.devin/skills`, custom root) |
| `ui-reasoning.csv` referenced bare — file lives at `data/ui-reasoning.csv` | Agent reads the wrong path; reasoning-rules file appears missing |
| `scripts/search.py` crashes on non-UTF-8 consoles (Windows cp1252) printing `⚡`/`✓` glyphs | `UnicodeEncodeError` mid-task on the world's most common dev OS |

Three defects, all invisible until the agent actually *runs* the skill.

**What the repair is** (`ui-ux-pro-max.patch`, 101-line diff):

- All 10 commands → `scripts/search.py` relative to the skill root, with one
  line telling the agent to resolve from the SKILL.md directory
- `ui-reasoning.csv` → `data/ui-reasoning.csv`
- `sys.stdout.reconfigure(encoding="utf-8", errors="replace")` in `search.py`

## Protocol

**Chat A — control.** Install the *unmodified* upstream skill:

```
cp -r internet-skills/skills/ui-ux-pro-max  <workspace>/.agents/skills/ui-ux-pro-max
```

**Chat B — treatment.** Install the repaired skill the same way (the repo copy
already has the patch applied — `ui-ux-pro-max-fixed/`).

**Identical prompt for both chats** (do not name the skill — let it trigger):

> Build a landing page for a luxury day spa called "Serenity Spa" — a calm,
> premium wellness brand. Include a hero, services grid, pricing section, and
> a booking CTA. Then open it in a browser preview.

## What to watch

| Signal | Expected in A (broken) | Expected in B (fixed) |
|---|---|---|
| First tool call | `python3 .claude/skills/...` → *No such file* | `scripts/search.py` runs |
| Design system | skipped or improvised | real output: palette, fonts, pattern, anti-patterns |
| On Windows | script may also `UnicodeEncodeError` | runs clean |
| Final page | generic gradient UI | coherent system: matched palette + font pairing + recommended layout |

Score blind: shuffle the two outputs, pick the better page, then unblind.

## Result (ran locally, agent-faithful)

Terminal truth of the failure cascade in A:

```
$ python .claude/skills/ui-ux-pro-max/scripts/search.py ...
-> can't open file: No such file or directory
$ python scripts/search.py ...            # agent finds the script itself
-> UnicodeEncodeError: 'charmap' codec can't encode ⚡   (cp1252)
```

Agent gave up and improvised. In B the same console ran the same script
cleanly and returned a full design system — and the page was built
**strictly from its output** (Soft UI Evolution, `#10B981`/`#8B5CF6`/`#ECFDF5`,
Lora + Raleway, anti-patterns honored).

| A — broken skill (`A-broken.png`) | B — repaired (`B-fixed.png`) |
|---|---|
| generic purple-gradient hero | curated pastel system (mint/cream/gold) |
| emoji icons | stroke SVGs, consistent weight |
| clashing gold CTA on purple | single accent violet CTA |
| no social proof | trust strip per recommended pattern |
| default sans-serif | specified Lora/Raleway pairing |

## Reproduce the audit

```bash
python -m surgeon scan internet-skills/skills/ui-ux-pro-max
# S007 warning: ui-reasoning.csv not found at referenced path
# (the .claude/ path bug is caught by reading the skill — agents, not linters,
#  follow command strings)
```
