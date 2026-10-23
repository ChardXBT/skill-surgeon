# Surgery log - 2026-10-23 (real run on a production 18-skill library)

Audit: `surgeon scan ~/.agents/skills ./Downloads/.agents/skills`
**Before:** 84/100 - 4 errors, 67 warnings, 1 suggestion, 11 proposed fixes.
**After:** 87/100 - S008 + S012 cleared, 4 loose refs repointed to verified data/ paths.
Remaining errors are operator-retained duplicates + genuinely-dead feature docs.

## Applied (operator-approved)

- **F-005** csfloat-image-auto-lister (S008) - `C:\Users\ericy\OneDrive\…` → `~/OneDrive/…`
- **F-006** namewright-2026-06-22 (S012) - `name` field → `namewright`; dir renamed
  `namewright-2026-06-22/` → `namewright/`; change recorded in the skill's own
  `CHANGELOG.md`. Live registry confirms the rename took effect.

## Rejected by operator review (the gate working)

- **F-001..F-004** applied-ai-radar (S007) - fuzzy match proposed `hourly.md` →
  `assets/hourly-mode.md`, but the referenced files live in a different repo
  (`capabilities/applied-ai-radar/`) and the doc says so. Applying would have
  corrupted a correct skill.
- **F-007** privacy-surface-audit (S007) - `.sops.yaml` → `agents/openai.yaml`
  wrong fuzzy match.

## Deep-scan layer (agent-driven, beyond the CLI)

Cross-repo verification of flagged runtime refs against the real checkout
(`~/OneDrive/Documents/GitHub/auto-lister`):

- **13 refs verified live:** `data/manual_sales.json`, `data/manual_reversals.json`,
  `data/manual_price_updates.json`, `data/manual_row_removals.json`,
  `TRADE_REVERSALS.md`, `data/marketplace_fees.json`, `data/listing_ledger.json`,
  `data/shared/portfolio_summary.json`, `data/removed_config_items.json`,
  `src/auto_lister/print_inventory_assets.py`, `bot.py`, `README.md`,
  `DEV_LOG.md`, `PORTFOLIO_OPERATIONS.md`.
- **9 refs confirmed dead even in the target repo** - `src/csmarket_auto_buyer/`
  does not exist; `listing_model.py`, `listing_state.json`,
  `tests/test_tournament_souvenir_policy.py`, `config/legacy_souvenir_integrity.json`,
  `config/tournament_signature_catalog.json` also absent. Genuine doc drift -
  logged as manual follow-up (rewriting requires knowing whether the feature was
  removed or renamed).

## Semantic pass (frontier agent as the reviewer)

- Trigger collisions: `cs2-sales-reconciler ↔ csfloat-image-auto-lister` share CS2
  sales/listings vocabulary but distinct actions (reconcile vs. list) - mild,
  no rewrite needed. All other descriptions reviewed individually: clear
  what/when, no vague triggers.
- The two same-name duplicate pairs are S009's job, and the operator chose to
  retain both copies for now.

## Safety notes

- No skill was edited without approval; no directory deleted.
- The two oversized skills (7.3k / 6.5k tokens) flagged for future splitting -
  risky surgery, deferred.

## Workspace declarations added

 on
cs2-sales-reconciler and csfloat-image-auto-lister - refs now resolve against
the real checkout. Effect: warnings 66→35 (verified refs stop counting), and
refs that STILL miss escalate to errors - surfacing the 9 dead
-era refs as real doc drift instead of noise.
4 loose paths corrected ( →  etc.).

## Round 2 - full-root scan (23 skills, 4 roots incl. ai-skills repo)

- Workspace declarations: csfloat (3 workspaces: auto-lister + csmarket-auto-buyer x2),
  cs2-sales-reconciler (2: auto-lister + buff-auto-lister), yeahwedid-import (yeahwedid),
  me-refresh (~/Me), cloud-supervisor-migration (~/Downloads/bot-supervisor).
- Repointed to verified paths: data/config.json, data/bot_state.json,
  data/manual_sales.json, data/manual_reversals.json (cs2); listing_model.py and
  listing_state.json full paths; bot_supervisor/single_instance.py.
- The 9 "dead" csfloat refs mostly resolved - they point at the separate
  csmarket-auto-buyer repo, not auto-lister. Not drift: cross-repo references.
- Newly visible in ai-skills root: third copies of pro-ats / professor-research-brief,
  second privacy-surface-audit, and the stale namewright-2026-06-22 repo copy.
- Still open (operator decisions): duplicates policy, ai-skills repo rename,
  me-refresh generated-artifact refs (outputs, not dead links), 2 oversized skills.

## Round 3 - divergence-aware duplicates + ancestor resolution

Score: **93/100 A, 0 errors** across 45 skills / 4 roots (was 84→86).

- S009 now distinguishes deploy copies (identical content → info) from
  divergent copies (error). All Eric's cross-root duplicates turned out
  content-identical - deployment, not a bug. The real divergence was
  deployed-vs-source drift, fixed by syncing deployed edits into ai-skills
  capabilities/ source (pushed: bd83467, c3c042f).
- S007 resolves refs against ancestor dirs - variant skills legitimately
  share the parent skill's bundled references/ and scripts/.
- metadata.generates declared on me-refresh, chat-handoff,
  professor-research-brief, skill-surgeon - files a skill produces at
  runtime are no longer mistaken for dead references.
- namewright: repo already moved it to capabilities/namewright with new
  content; only the frontmatter name still said the dated slug - fixed and
  pushed to ChardXBT/ai-skills.
- Open by design: discord-monitor/finish agent variants share a name under
  variants/ (intentional, info-level); 2 oversized skills; remaining warns
  are unverified refs in not-yet-deployed capabilities skills.
