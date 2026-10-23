# Skill Surgeon - health report

**Score: 85/100 (B)** - 4 errors · 67 warnings · 1 suggestions

Scanned **18** skills across 2 root(s). Semantic pass (open-weight local model): enabled.

| Severity | Rule | Skill | Finding | Location |
|---|---|---|---|---|
| error | S009 | pro-ats | duplicate name also defined at: C:\Users\ericy\.agents\skills\pro-ats\SKILL.md; C:\Users\ericy\Downloads\.agents\skills\pro-ats\SKILL.md | `SKILL.md` |
| error | S009 | pro-ats | duplicate name also defined at: C:\Users\ericy\.agents\skills\pro-ats\SKILL.md; C:\Users\ericy\Downloads\.agents\skills\pro-ats\SKILL.md | `SKILL.md` |
| error | S009 | professor-research-brief | duplicate name also defined at: C:\Users\ericy\.agents\skills\professor-research-brief\SKILL.md; C:\Users\ericy\Downloads\.agents\skills\professor-research-brief\SKILL.md | `SKILL.md` |
| error | S009 | professor-research-brief | duplicate name also defined at: C:\Users\ericy\.agents\skills\professor-research-brief\SKILL.md; C:\Users\ericy\Downloads\.agents\skills\professor-research-brief\SKILL.md | `SKILL.md` |
| info | S012 | namewright-2026-06-22 | date-stamped name `namewright-2026-06-22`; prefer a stable name | `SKILL.md` |
| warn | S007 | applied-ai-radar | reference `hourly.md` not found in skill dir (verify it resolves at runtime) | `SKILL.md:22` |
| warn | S007 | applied-ai-radar | reference `daily.md` not found in skill dir (verify it resolves at runtime) | `SKILL.md:22` |
| warn | S007 | applied-ai-radar | reference `hourly-scheduler.md` not found in skill dir (verify it resolves at runtime) | `SKILL.md:22` |
| warn | S007 | applied-ai-radar | reference `daily-scheduler.md` not found in skill dir (verify it resolves at runtime) | `SKILL.md:22` |
| warn | S007 | applied-ai-radar | reference `tests/applied-ai-radar-behavioral-cases.json` not found in skill dir (verify it resolves at runtime) | `SKILL.md:40` |
| warn | S007 | chat-handoff | reference `HANDOFF.md` not found in skill dir (verify it resolves at runtime) | `SKILL.md:72` |
| warn | S006 | cloud-supervisor-migration | ~6525 tokens / 493 body lines (spec guidance: <=5000 tokens, <=500 lines) | `SKILL.md` |
| warn | S007 | cloud-supervisor-migration | reference `README.md` not found in skill dir (verify it resolves at runtime) | `SKILL.md:42` |
| warn | S007 | cloud-supervisor-migration | reference `config.yaml` not found in skill dir (verify it resolves at runtime) | `SKILL.md:42` |
| warn | S007 | cloud-supervisor-migration | reference `config.local.yaml` not found in skill dir (verify it resolves at runtime) | `SKILL.md:43` |
| warn | S007 | cloud-supervisor-migration | reference `project_controls.yaml` not found in skill dir (verify it resolves at runtime) | `SKILL.md:44` |
| warn | S007 | cloud-supervisor-migration | reference `docs/ARCHITECTURE.md` not found in skill dir (verify it resolves at runtime) | `SKILL.md:44` |
| warn | S007 | cloud-supervisor-migration | reference `docs/DESIGN_RATIONALE.md` not found in skill dir (verify it resolves at runtime) | `SKILL.md:44` |
| warn | S007 | cloud-supervisor-migration | reference `docs/MIGRATION_MAP.md` not found in skill dir (verify it resolves at runtime) | `SKILL.md:44` |
| warn | S007 | cloud-supervisor-migration | reference `docs/REPOSITORY_UPDATES.md` not found in skill dir (verify it resolves at runtime) | `SKILL.md:44` |
| warn | S007 | cloud-supervisor-migration | reference `docs/BOT_INTEGRATION_CONTRACT.md` not found in skill dir (verify it resolves at runtime) | `SKILL.md:44` |
| warn | S007 | cloud-supervisor-migration | reference `docs/SAFETY_INVARIANTS.md` not found in skill dir (verify it resolves at runtime) | `SKILL.md:46` |
| warn | S007 | cloud-supervisor-migration | reference `docs/REMOTE_GATEWAY_ARCHITECTURE.md` not found in skill dir (verify it resolves at runtime) | `SKILL.md:48` |
| warn | S007 | cloud-supervisor-migration | reference `SUPERVISOR_CLOUD_MIGRATION_AUDIT.md` not found in skill dir (verify it resolves at runtime) | `SKILL.md:50` |
| warn | S007 | cloud-supervisor-migration | reference `docs/integration_contracts/` not found in skill dir (verify it resolves at runtime) | `SKILL.md:51` |
| warn | S007 | cloud-supervisor-migration | reference `single_instance.py` not found in skill dir (verify it resolves at runtime) | `SKILL.md:435` |
| warn | S007 | cs2-sales-reconciler | reference `config.json` not found in skill dir (verify it resolves at runtime) | `SKILL.md:14` |
| warn | S007 | cs2-sales-reconciler | reference `bot_state.json` not found in skill dir (verify it resolves at runtime) | `SKILL.md:14` |
| warn | S007 | cs2-sales-reconciler | reference `data/manual_row_removals.json` not found in skill dir (verify it resolves at runtime) | `SKILL.md:14` |
| warn | S007 | cs2-sales-reconciler | reference `data/manual_price_updates.json` not found in skill dir (verify it resolves at runtime) | `SKILL.md:15` |
| warn | S007 | cs2-sales-reconciler | reference `data/manual_sales.json` not found in skill dir (verify it resolves at runtime) | `SKILL.md:15` |
| warn | S007 | cs2-sales-reconciler | reference `data/manual_reversals.json` not found in skill dir (verify it resolves at runtime) | `SKILL.md:15` |
| warn | S007 | cs2-sales-reconciler | reference `TRADE_REVERSALS.md` not found in skill dir (verify it resolves at runtime) | `SKILL.md:16` |
| warn | S007 | cs2-sales-reconciler | reference `data/marketplace_fees.json` not found in skill dir (verify it resolves at runtime) | `SKILL.md:23` |
| warn | S007 | cs2-sales-reconciler | reference `data/config.json` not found in skill dir (verify it resolves at runtime) | `SKILL.md:38` |
| warn | S007 | cs2-sales-reconciler | reference `data/listing_ledger.json` not found in skill dir (verify it resolves at runtime) | `SKILL.md:38` |
| warn | S007 | cs2-sales-reconciler | reference `data/asset_archive.json` not found in skill dir (verify it resolves at runtime) | `SKILL.md:38` |
| warn | S007 | cs2-sales-reconciler | reference `data/removed_config_items.json` not found in skill dir (verify it resolves at runtime) | `SKILL.md:39` |
| warn | S007 | cs2-sales-reconciler | reference `listing_state.json` not found in skill dir (verify it resolves at runtime) | `SKILL.md:47` |
| warn | S007 | cs2-sales-reconciler | reference `manual_sales.json` not found in skill dir (verify it resolves at runtime) | `SKILL.md:55` |
| warn | S007 | cs2-sales-reconciler | reference `manual_reversals.json` not found in skill dir (verify it resolves at runtime) | `SKILL.md:58` |
| warn | S007 | cs2-sales-reconciler | reference `data/shared/portfolio_summary.json` not found in skill dir (verify it resolves at runtime) | `SKILL.md:73` |
| warn | S006 | csfloat-image-auto-lister | ~7354 tokens / 220 body lines (spec guidance: <=5000 tokens, <=500 lines) | `SKILL.md` |
| warn | S007 | csfloat-image-auto-lister | reference `README.md` not found in skill dir (verify it resolves at runtime) | `SKILL.md:43` |
| warn | S007 | csfloat-image-auto-lister | reference `DEV_LOG.md` not found in skill dir (verify it resolves at runtime) | `SKILL.md:43` |
| warn | S007 | csfloat-image-auto-lister | reference `PORTFOLIO_OPERATIONS.md` not found in skill dir (verify it resolves at runtime) | `SKILL.md:43` |
| warn | S007 | csfloat-image-auto-lister | reference `data/config.json` not found in skill dir (verify it resolves at runtime) | `SKILL.md:49` |
| warn | S007 | csfloat-image-auto-lister | reference `data/accounts/rukia/config.json` not found in skill dir (verify it resolves at runtime) | `SKILL.md:49` |
| warn | S007 | csfloat-image-auto-lister | reference `src/auto_lister/print_inventory_assets.py` not found in skill dir (verify it resolves at runtime) | `SKILL.md:72` |
| warn | S007 | csfloat-image-auto-lister | reference `src/csmarket_auto_buyer/legacy_souvenir.py` not found in skill dir (verify it resolves at runtime) | `SKILL.md:94` |
| warn | S007 | csfloat-image-auto-lister | reference `src/csmarket_auto_buyer/tournament_souvenir.py` not found in skill dir (verify it resolves at runtime) | `SKILL.md:96` |
| warn | S007 | csfloat-image-auto-lister | reference `src/csmarket_auto_buyer/listing_parser.py` not found in skill dir (verify it resolves at runtime) | `SKILL.md:96` |
| warn | S007 | csfloat-image-auto-lister | reference `listing_model.py` not found in skill dir (verify it resolves at runtime) | `SKILL.md:96` |
| warn | S007 | csfloat-image-auto-lister | reference `config/legacy_souvenir_integrity.json` not found in skill dir (verify it resolves at runtime) | `SKILL.md:98` |
| warn | S007 | csfloat-image-auto-lister | reference `config/tournament_signature_catalog.json` not found in skill dir (verify it resolves at runtime) | `SKILL.md:98` |
| warn | S007 | csfloat-image-auto-lister | reference `tests/test_tournament_souvenir_policy.py` not found in skill dir (verify it resolves at runtime) | `SKILL.md:100` |
| warn | S007 | csfloat-image-auto-lister | reference `bot.py` not found in skill dir (verify it resolves at runtime) | `SKILL.md:169` |
| warn | S007 | csfloat-image-auto-lister | reference `data/manual_sales.json` not found in skill dir (verify it resolves at runtime) | `SKILL.md:190` |
| warn | S008 | csfloat-image-auto-lister | absolute path `C:\Users\ericy\OneDrive\Documents\GitHub\auto-lister` is machine/user-specific | `SKILL.md:8` |
| warn | S007 | me-refresh | reference `ME_UPDATE_PROTOCOL.md` not found in skill dir (verify it resolves at runtime) | `SKILL.md:3` |
| warn | S007 | me-refresh | reference `docs/UPDATER.md` not found in skill dir (verify it resolves at runtime) | `SKILL.md:3` |
| warn | S007 | me-refresh | reference `proposal-id.txt` not found in skill dir (verify it resolves at runtime) | `SKILL.md:8` |
| warn | S007 | me-refresh | reference `snapshot.json` not found in skill dir (verify it resolves at runtime) | `SKILL.md:38` |
| warn | S007 | me-refresh | reference `review.md` not found in skill dir (verify it resolves at runtime) | `SKILL.md:38` |
| warn | S007 | me-refresh | reference `proposal.json` not found in skill dir (verify it resolves at runtime) | `SKILL.md:38` |
| warn | S007 | me-refresh | reference `bundle.json` not found in skill dir (verify it resolves at runtime) | `SKILL.md:44` |
| warn | S007 | privacy-surface-audit | reference `.sops.yaml` not found in skill dir (verify it resolves at runtime) | `SKILL.md:17` |
| warn | S007 | professor-research-brief | reference `Alexander_Kroitor_Deep_Academic_Brief.pdf` not found in skill dir (verify it resolves at runtime) | `SKILL.md:251` |
| warn | S007 | professor-research-brief | reference `Alexander_Kroitor_Deep_Academic_Brief.pdf` not found in skill dir (verify it resolves at runtime) | `SKILL.md:251` |
| warn | S007 | skill-surgeon | reference `surgery-plan.json` not found in skill dir (verify it resolves at runtime) | `SKILL.md:15` |
| warn | S007 | skill-surgeon | reference `surgery-log.md` not found in skill dir (verify it resolves at runtime) | `SKILL.md:27` |
| warn | S007 | yeahwedid-import | reference `config.js` not found in skill dir (verify it resolves at runtime) | `SKILL.md:27` |

_generated by skill-surgeon_
