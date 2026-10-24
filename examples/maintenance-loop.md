# The maintenance loop, with receipts

The full lifecycle on real skills: **adopt → scan → tailor → test → watch → diff**.

## 1. `test` on the broken `ui-ux-pro-max` (internet skill, pre-repair)

```
  SMOKE TEST - do the documented commands work?
  os=windows shell=powershell python=python clis=[git, docker, gh, ollama, ffmpeg, curl, uv, bun] roots=3

  ui-ux-pro-max
    NOENV L93    python3 --version || python --version   `python3` not on PATH
    NOENV L100   brew install python3                    `brew` not found on PATH
    NOENV L105   sudo apt update && sudo apt install python3   `sudo` not found on PATH
    NOENV L132   python3 .claude/skills/ui-ux-pro-max/scripts/search.py "..."  `python3` not on PATH
    ... (every documented command fails identically)
  13 commands checked - 1 pass   12 broken   0 skipped (unsafe)
```

Static-only mode already isolates the exact failure layers: the documented
interpreter doesn't run on this host (Windows Store `python3` stub), and every
path is prefixed with a `.claude/` root that only exists on the author's
machine. `tailor` then proposed 11 rewrites; `apply` fixed all of them.

## 2. `watch` on a live skill library (real output)

```
  DRIFT  cs2-sales-reconciler       auto-lister    1 files changed since verification (2026-10-23)
         referenced files changed: data/manual_sales.json
  FRESH  cs2-sales-reconciler       buff-auto-lister   no workspace commits since 2026-10-23
  DRIFT  csfloat-image-auto-lister  auto-lister    1 files changed since verification
  NOGIT  csfloat-image-auto-lister  csmarket-auto-buyer   workspace is not a git repo
  DRIFT  csfloat-image-auto-lister  Csmarket Auto Buyer   4 files changed since verification
  FRESH  me-refresh                 Me             no workspace commits since 2026-10-23
```

`watch` caught real drift: `data/manual_sales.json` changed in the auto-lister
repo after two skills were last verified - the exact signal a re-review needs.

## 3. The loop closing

```
surgeon scan . --adopt-on-clean      # clean scan -> stamps verified_at
surgeon scan . --save-baseline base.json
# ... time passes, repos change ...
surgeon diff base.json               # score 94 -> 87, lists what decayed
surgeon watch                        # which referenced files changed
surgeon tailor / surgeon test        # is it still true on THIS machine
surgeon fix                          # approve repairs one at a time
```

The point isn't one clean library - it's a loop that keeps running while
everything around the skills keeps moving.
