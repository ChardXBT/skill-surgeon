# skill-surgeon

**Your AI assistant's instruction files break silently. This finds and fixes them - with your approval on every change.**

[▶ 30-second explainer video](https://github.com/ChardXBT/skill-surgeon/raw/main/examples/video/skill-surgeon-30s.mp4)

## What it does

AI coding assistants follow small instruction files called *skills*. Over
time they rot: they point at files that no longer exist, pile up
duplicates, or hide credentials in plain text. Nothing warns you - the
assistant just quietly does the wrong thing.

Skill Surgeon scans your skill library, shows you exactly what's broken,
and proposes each repair as a visible before/after change. **Nothing gets
edited until you approve it.** Then it re-checks itself and logs the work.

## Proof it works

We scanned the largest public skill collection - **1,340 real skills -
and found 495 with errors**, including files that were referenced but never
published at all.

Then we picked one popular design skill (`ui-ux-pro-max`), fixed its three
real defects, and ran the same task with the original vs the repaired
version. The original failed twice - the agent gave up and made a generic
page. The repaired skill's design engine ran and drove a coherent page:

| Before - broken skill | After - repaired |
|---|---|
| ![before](examples/ab-benchmark/A-broken.png) | ![after](examples/ab-benchmark/B-fixed.png) |

We also ran it on the author's own 45-skill library: it caught duplicated
skills, a path that only worked on one machine, and references to files
deleted months ago - score 84 → 93, zero errors left. It even rejected 3
of its own suggested fixes when human review caught fuzzy matches. The
approval gate is real, not decoration.

Full receipts in [`examples/`](examples/): audit reports, the surgery log,
the repair patch, and the A/B test protocol.

## How it works, in one paragraph

It runs a set of plain-rule checks (missing files, duplicate names,
leftover secrets, machine-specific paths) plus optional checks from an AI
model that runs **on your own computer** - so your private skills never get
sent to a cloud service. Proposed fixes are exact text replacements you can
read before saying yes.

## It does more than lint

```bash
surgeon tailor   # rewrites skills to fit YOUR machine (paths, interpreters, tools)
surgeon test     # runs the commands a skill documents - finds dead instructions
surgeon watch    # alerts when the repo a skill describes drifts out from under it
surgeon adopt    # declares what a skill monitors so watch can track it
surgeon coverage # maps which requests your library can and can't handle
surgeon diff     # "is my library getting healthier or decaying?" vs a baseline
surgeon doctor   # checks surgeon's own setup (python, Ollama, PATH)
surgeon badge    # README score badge: ![skill-surgeon](...93/100...)
```

Every proposed fix also carries a confidence label - deterministic rewrites
are marked safe; fuzzy, ambiguous, denylist-context, or model-guessed targets
are flagged for a hard look and are never auto-applied.
And `test --run` scrubs API keys from the environment before anything
executes, so a skill's script can't read your credentials.

Every one of these exists because we watched it fail for real. A popular
skill's commands pointed at the author's machine - `tailor` finds and fixes
that. Another crashed on Windows consoles - `test` runs the commands and
catches it. `watch` keeps working after you're done: it notices when the
repo a skill describes changed underneath it.

## CI

`scan --ci` prints one line and exits non-zero on errors:

```yaml
# .github/workflows/skills.yml - see examples/ci.yml
- run: python -m surgeon scan skills/ --ci
```

## Technologies

Python standard library only - no dependencies, no install. Optional local
AI checks via [Ollama](https://ollama.com) with any open-weight model
(tested on `gemma4:e4b`). Works on `.agents`, `.claude`, `.devin` and other
skill directories. MIT licensed.

## Try it

```bash
git clone https://github.com/ChardXBT/skill-surgeon && cd skill-surgeon
pip install -e .                              # optional: puts `surgeon` on PATH
python -m surgeon scan examples/demo-skills   # finds the planted bugs
python -m surgeon scan <your-skills-folder>   # your real library
```

## Safety

- Read-only until you approve a change - it never edits on its own
- Never deletes or moves a skill
- Secrets it finds are redacted, never printed
- Works fully offline
