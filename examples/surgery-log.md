# Surgery log — 2026-10-23 (real run on a production 18-skill library)

Audit: `surgeon scan ~/.agents/skills ./Downloads/.agents/skills`
**Before:** 84/100 — 4 errors, 67 warnings, 1 suggestion, 11 proposed fixes.
**After:** 85/100 — S008 + S012 cleared; remaining errors are operator-retained duplicates.

## Applied (operator-approved)

- **F-005** csfloat-image-auto-lister (S008) — `C:\Users\ericy\OneDrive\…` → `~/OneDrive/…`
- **F-006** namewright-2026-06-22 (S012) — `name` field → `namewright`; dir renamed
  `namewright-2026-06-22/` → `namewright/`; change recorded in the skill's own
  `CHANGELOG.md`. Live registry confirms the rename took effect.

## Rejected by operator review (the gate working)

- **F-001..F-004** applied-ai-radar (S007) — fuzzy match proposed `hourly.md` →
  `assets/hourly-mode.md`, but the referenced files live in a different repo
  (`capabilities/applied-ai-radar/`) and the doc says so. Applying would have
  corrupted a correct skill.
- **F-007** privacy-surface-audit (S007) — `.sops.yaml` → `agents/openai.yaml`
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
- **9 refs confirmed dead even in the target repo** — `src/csmarket_auto_buyer/`
  does not exist; `listing_model.py`, `listing_state.json`,
  `tests/test_tournament_souvenir_policy.py`, `config/legacy_souvenir_integrity.json`,
  `config/tournament_signature_catalog.json` also absent. Genuine doc drift —
  logged as manual follow-up (rewriting requires knowing whether the feature was
  removed or renamed).

## Semantic pass (frontier agent as the reviewer)

- Trigger collisions: `cs2-sales-reconciler ↔ csfloat-image-auto-lister` share CS2
  sales/listings vocabulary but distinct actions (reconcile vs. list) — mild,
  no rewrite needed. All other descriptions reviewed individually: clear
  what/when, no vague triggers.
- The two same-name duplicate pairs are S009's job, and the operator chose to
  retain both copies for now.

## Safety notes

- No skill was edited without approval; no directory deleted.
- The two oversized skills (7.3k / 6.5k tokens) flagged for future splitting —
  risky surgery, deferred.
