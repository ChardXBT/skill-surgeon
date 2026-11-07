# Implicit State Machines — skill-surgeon

Audit of tracked source for mutually-exclusive state encoded **without** a
single declared state model. Report only — no refactor.

## Smoke-test command outcome (`CmdResult.status`)

**States** (8): `ok` | `missing_file` | `missing_interp` | `syntax_fail` |
`crashed` | `unsafe_skipped` | `timeout` | `unverified`

**Encoded as**: a free-form `str` field (`surgeon/smoke.py:97`, documented
only in an inline comment) returned from ~10 different `return CmdResult(...)`
sites in `check_command` (`surgeon/smoke.py:200-264`). The read side is three
hand-maintained decoders in `surgeon/cli.py`:
- `mark` map — cli.py:393-395 (`.get(r.status, "info")`)
- `tag` map — cli.py:396-398 (`.get(r.status, "?")`)
- the "broken" set `("missing_file", "missing_interp", "syntax_fail",
  "crashed")` — cli.py:402, which drives the exit code (cli.py:408)
Plus per-status counting in `SmokeReport.counts()` (`smoke.py:105-109`).

**Invalid combos**: any string outside the 8 is representable — a typo at one
of the ~10 set sites compiles and runs fine.

**Transitions**: set in `check_command` (`smoke.py:208, 211, 219, 222, 235,
238, 242, 246, 257, 259, 262, 264`); counted `smoke.py:108`; decoded/decisioned
`cli.py:393-408`; serialized to agent JSON `cli.py:380`.

**Risk** — *high*. A new failure status (or a typo like `"missing_inter"`)
silently renders as `?`/`info`, is excluded from the `bad` tuple, and the
command exits `0` — a CI gate reporting green on a broken skill. The three
decoders must be updated in lockstep; nothing enforces it.

## Workspace drift status (`WatchResult.status`)

**States** (5): `fresh` | `drifted` | `untracked` | `not_git` | `missing`

**Encoded as**: `str` field declared `surgeon/watch.py:26` (states only in a
comment); assigned at five sites in `watch_skill` (`watch.py:101, 103, 109,
112, 121, 133`). Decoded by two parallel dicts indexed directly —
`cli.py:434-435` (`{...}[r.status]`, twice) — and an exit predicate listing
states by hand (`cli.py:443-445`).

**Invalid combos**: any unlisted string is representable; unlike the smoke
decoders these dicts have no `.get` default, so an unknown status raises
`KeyError` and crashes `surgeon watch` mid-print. Also `"untracked"` is
overloaded for two distinct causes (git missing on PATH, `git log` failed —
`watch.py:109` vs `121`).

**Transitions**: `watch.py:101` (initial `fresh`), `103` (missing),
`109`/`112` (untracked/not_git fork on `shutil.which`), `121` (untracked),
`133` (drifted).

**Risk** — *medium*. Adding a state in `watch.py` without touching both dicts
is a runtime `KeyError`, not a caught error. A state that should fail CI but
isn't added to the `cli.py:443` predicate exits `0` silently (e.g. `drifted`
counts only when `changed_refs` is non-empty — `cli.py:439,443`).

## Finding severity (`Finding.severity`)

**States** (3): `error` | `warn` | `info`

**Encoded as**: raw string literals at ~40 `Finding(...)` construction sites
(`surgeon/rules_structural.py:205-415`, `surgeon/tailor.py:139-250`,
`surgeon/fixes.py:312-336`), plus the `RULES`/`T_RULES` tables
(`rules_structural.py:15-28`, `tailor.py:18`). A declared constant
`SEVERITIES = ("error","warn","info")` exists (`model.py:8`) but is **never
referenced anywhere** — a dead source of truth.

**Invalid combos**: any string is representable, and readers disagree about
what to do with one: `report.py:46` `sev_order[x.severity]` raises `KeyError`
(crashing `surgeon scan`'s terminal render); `report.py:82`
`.get(..., 3)` tolerates it; `model.py:126` `counts()` and `model.py:133`
`_SEV_PENALTY.get(..., 0)` silently treat an unknown severity as zero-penalty
(score inflates); `cli.py:127`/`365` `== "error"` treats it as non-error.

**Transitions**: set at every `Finding(...)`/`RULES` literal site; consumed
`cli.py:94-96, 127, 353, 365`; `report.py:40-46, 69, 80-86`;
`model.py:124-133`.

**Risk** — *high*. One mistyped literal (e.g. `"errors"`) is a `KeyError`
crash on the terminal path **and** a silently-inflated score on the JSON/CI
path (`--ci` prints `score=...` before rendering) — same bad datum, opposite
failure modes depending on output flag.

## Fix lifecycle status (`Fix.status`)

**States** (4): `pending` | `applied` | `skipped` | `failed`

**Encoded as**: `str` field (`model.py:90`), round-tripped through the plan
JSON (`model.py:98, 109`). Written at `cli.py:144` (`applied`/`failed`) and
`cli.py:195` (`skipped`). **Never read for a decision**: `cmd_apply`
(`cli.py:240-242`) selects on `kind`/`auto`/`confidence` only and ignores
`status` entirely.

**Invalid combos**: a plan entry marked `"applied"` or `"failed"` is
re-attempted by `surgeon apply` — prevented from rewriting only by
`apply_fix`'s find-string heuristic ("already applied", `report.py:135-136`),
not by the status field. `cmd_fix` mutates status in memory then discards it
(only the prose log records outcomes, `cli.py:204`), so plan JSON always
claims `"pending"`.

**Transitions**: `model.py:109` (deserialize → `pending` default),
`cli.py:144`, `cli.py:195`.

**Risk** — *medium*. The serialized state lies to any consumer (the plan is
agent-facing input, `cli.py:244`): replaying a plan re-runs every entry, and
double-apply is avoided only accidentally via text-absence. `replace_all`
fixes or overlapping `find` strings can genuinely double-apply.

## Fix eligibility triple (`Fix.kind` + `Fix.auto` + `Fix.confidence`)

**States**: `kind` = `replace_text` | `rename_dir` | `manual`
(`model.py:73-77`), crossed with `auto` (bool, `model.py:87`) and
`confidence` = `safe` | `review` (`model.py:89`). The effective lifecycle is
{auto-apply, auto-apply-but-guessed, manual-only} encoded redundantly across
three fields.

**Encoded as**: three independently-set fields. `rename_dir` is a **dead
state** — documented (`model.py:75`) but no construction site exists.
`confidence="review"` + `auto=True` is a reachable combo (`fixes.py:327-328,
344-345`: `auto` is set by slug uniqueness while confidence stays `review`).

**Invalid combos**: `kind="manual", auto=True` is representable; a crafted
plan JSON can set any combination (`Fix.from_dict` `model.py:102-110`
performs no validation — the plan file is agent-facing input).

**Transitions**: set `fixes.py:158-159, 169-171, 270-271, 284-289, 328, 345`;
`tailor.py:175-176, 227-228`. Decisions re-implement the eligibility
predicate four different ways: `cli.py:167` (`f.auto and f.kind ==
"replace_text"` — ignores confidence), `cli.py:240-242` (adds confidence only
under `--safe-only`), `cli.py:268-275` `_skip_reason` (ordered cascade),
`report.py:115` (kind only).

**Risk** — *medium*. `surgeon apply --all` applies `confidence="review"`
(guessed-target) fixes with no flag; only opt-in `--safe-only` gates them.
The four predicate sites can drift: a fix judged "manual" in one place
(`_skip_reason`'s cascade) and auto-eligible in another (`cli.py:167` ignores
confidence) gets inconsistent treatment between `fix` and `apply`.

## Frontmatter parse outcome (`fm_start` / `fm_end` / `parse_error`)

**States** (5): `unreadable` | `no-fence` | `unclosed-fence` |
`yaml-degraded` | `ok` — none of them named.

**Encoded as**: sentinel `-1`s on two int fields plus a free-text error
string: `split_frontmatter` returns `(None, text, -1, -1)` for no fence and
`(None, text, i, -1)` for an opening `---` with no close
(`frontmatter.py:26-34`); `load_skill` layers `parse_error` values
(`discover.py:71-82`: `"unreadable: ..."`, `"no frontmatter block"`,
`"yaml parse failed ...; used lenient parser"`). The unclosed-fence state is
`fm_start >= 0 and fm_end == -1` — distinguishable only by checking *both*
sentinels.

**Invalid combos**: `fm_start >= 0 / fm_end == -1` (unclosed) is reachable
and every reader handles it only by accident: `model.py:55` `body_offset`
keys solely on `fm_end != -1`, so an unclosed-fence file reports offset 0;
`fixes.py:103,121` check only `fm_start == -1` and rely on
`range(fm_start+1, fm_end)` being empty for the unclosed case. A reader using
`fm_start != -1` to mean "has frontmatter" misclassifies unclosed files.

**Transitions**: set `frontmatter.py:27,31,34`, `discover.py:71-82`; read
`model.py:55`; `rules_structural.py:204` (`fm_end == -1` → S001 error),
`209-210` (`parse_error` truthy → S001 warn), `225` (`fm_end != -1`);
`fixes.py:84,103,121`; `frontmatter.py:230`.

**Risk** — *medium*. State is inferred per-reader from sentinel arithmetic;
the degraded/yaml-fallback case (`meta` partial + `parse_error` set) produces
both an S001 warn and downstream rules running on partial metadata. Wrong
line anchors on unclosed-fence skills.

## Adoption outcome flags (`Adoption.updates` / `already` / `applied` / `error` / `detected`)

**States** (≈5): `planned` | `applied` | `failed` | `already-declared` |
`no-op` — encoded by which of five fields are non-empty.

**Encoded as**: presence/absence of fields on the `Adoption` dataclass
(`adopt.py:26-33`). Display precedence is re-derived at read time:
`cli.py:298-306` (`ad.error` → failed; `elif ad.updates` → will-write;
`else` → "already declared"); `cli.py:133-134` counts `ad.applied`.

**Invalid combos**: `error` set + `updates` non-empty (rendered "failed" —
fine) or `applied=True` + `error` set (representable, nonsense). Two **dead /
write-only states**: `ad.updates` is never empty because `verified_at` is
stamped unconditionally (`adopt.py:89`), so the `else` → "already declared"
branch (`cli.py:305-306`) is unreachable; `ad.already` is appended at
`adopt.py:87` but **read nowhere**.

**Transitions**: `adopt.py:84-89` (plan: updates/already), `adopt.py:95-107`
(apply: error/applied), `adopt.py:115` (`yes and ad.updates` gate).

**Risk** — *low*. Mostly cosmetic today (dead display branch, dead field),
but it shows the outcome model has drifted from its readers: anyone adding an
`already`-only skill (workspace declared, no re-stamp desired) finds the
display can't represent it.

---

### Minor observations (not full findings)

- `Report.semantic_ok` + `semantic_note` (`model.py:119-120`): a 3-state
  {disabled | unavailable | ok} encoded in a bool+string pair
  (`cli.py:54-66`; read `report.py:32,75`, `cli.py:72`). `semantic_ok=False`
  with empty note renders `"off - "`. Single decision site — watch only.
- `Environment.os` (`env.py:34`): `windows|linux|macos` string, one set site
  with a normalizing map (`env.py:81`), consumed via
  `INAPPLICABLE_TOOLS.get(env.os, ())` (`tailor.py:233`) — an unrecognized
  label silently disables platform checks. Contained today.
- `CoverageReport.model_note` (`coverage.py:39`): 4-ish states
  (`"off"|"on"|"model returned no usable JSON"|"failed (...)"`) but only one
  decision read (`cli.py:491` `!= "off"`). Per audit criteria: single
  comparison site, not a machine.
