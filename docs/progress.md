# update-harness living map

as-of: 2026-09-14 Taipei
owner: EndeavorYen
line: update-harness
knife: auto-scan skill and plugin lists (#1)

`knife:` names the cut this spine belongs to. `knife: idle` = no named knife; it does **not** mean this line is finished. **Forbidden:** `line: idle` to mean “no knife”. One knife per map.

Statuses: **done** | **current** | **missing** | **n/a** | **unplanned**

Issue: https://github.com/EndeavorYen/skill-updater/issues/1
Close log: `.gentle-grill/grill-log.jsonl` (session). Decisions below are the on-disk copy.

write-gate:
- spec: 已過 — knife card in this file
- design: 已過 — `docs/knives/auto-scan/design.md`
- implementation: 已過 — `docs/knives/auto-scan/implementation.md`
- test-plan: 已過 — `docs/knives/auto-scan/test-plan.md`
現在哪一份: n/a (write-gate complete)

## Spine (status per stage)

| Stage | Status | Note |
| --- | --- | --- |
| Spec | done | knife card below; issue #1 + grill close |
| Contract | done | design + implementation + test-plan 已過 |
| Implement | done | scan on this branch; catalog.toml untouched |
| Verify | done | pytest 47 passed; invalid-TOML skip oracle |
| Debug | n/a | Verify never red (not unplanned) |
| Adversarial | done | independent oracles + claims table + jtm hunt 0 in-scope |
| Ablation (optional) | unplanned | optional after green |
| Ship prep | done | commit / push / PR; not merge |
| Merge gate | current | human squash-merge; then this map |

## current

Merge gate — human squash-merge; close #1; then this map (`knife: idle` or next named knife).

## missing

- Merge gate

## n/a

- Debug (Verify never red)

## unplanned

- Ablation (optional after green)
- Optional CR (not a spine cell)
- `scan --json` (global `--json` exists; not a 完成條件)

## Knife card

### Goal

A `scan` command that discovers skills and installed plugins on this machine and can append **new skill** rows to the gitignored overlay. Shipped `catalog.toml` stays generic. Hand-written overlay rows still win.

### 完成條件

1. `python update.py scan` is a parser command. Missing grok/claude CLIs are skip, not fail.
2. Scan immediate children of `code_root` and of live host skill dirs from the catalog. Do not follow junctions/symlinks out of those roots in a way that walks the filesystem twice.
3. Classify first-match: `installer` (`scripts/install.ps1` or `scripts/install.sh`) → `command` (`install.py`) → `link-pack` (`skills/*/SKILL.md`) → `link` (dir has `SKILL.md`). Skip dirs that match none. Skip this tool's own checkout except the existing self `link` row.
4. Catalog `name` (and dest) = directory name. `installer` / `command` `--write` omits `dest_skills`. `link-pack` still lists `skills/*`. Written rows omit `hosts` (catalog hosts apply).
5. Default stdout: each skill hit as name, kind, path, already-in-catalog vs new; plus installed grok/claude plugin ids from host CLI JSON. No marketplace available-but-not-installed.
6. `--write` appends only **new** `[[skills]]` to `catalog.local.toml` (create if needed) for a checkout we can name as repo (`code_root` child, or a junction target still under a scan root). Does not rewrite or delete existing overlay rows. Does not write `catalog.toml`. Does not write plugin rows or `plugin_hosts`. Host dest real-copies print only.
7. `--write --dry-run` prints the TOML that would be appended and does not write the file.
8. Explicit overlay rows still override scan guesses for the same dest (existing last-writer dest claim).
9. Tests cover classify + merge (new vs already catalogued) with fixtures; they do not require this machine's `D:\Code` layout.
10. README documents `scan` (no longer lists scanning a code tree as out of scope). SKILL.md run list includes `scan`.

### 不做什麼

- `git pull` of source repos
- rewriting other skills' SKILL.md
- scanning `$HOME` or arbitrary extra trees unless later catalog config names them
- `status --scan` or dual CLI
- per-plugin overlay schema; plugin ids in `catalog.local.toml`
- marketplace available-but-not-installed listing
- `--write` with `repo` = a host dest real-copy path
- inferring installer/command `dest_skills` from nested `SKILL.md`
- parsing SKILL.md frontmatter for `name`
- appending `plugin_hosts` from scan
- board `ensure` (not requested this cut)

### Where artifacts live

| Artifact | Path |
| --- | --- |
| CLI / classify / overlay write | `update.py` |
| Tests | `tests/test_update.py` |
| Agent run list | `SKILL.md` |
| Human docs | `README.md` |
| Shipped catalog (unchanged generic) | `catalog.toml` |
| Overlay (gitignored, runtime) | `catalog.local.toml` |
| This map | `docs/progress.md` |
| Design (before first Implement) | `docs/knives/auto-scan/design.md` |
| Implementation plan | `docs/knives/auto-scan/implementation.md` |
| Test plan | `docs/knives/auto-scan/test-plan.md` |
| Grill close log (session) | `.gentle-grill/grill-log.jsonl` |

### poteto

`python update.py scan` on a tmp catalog prints new vs already-catalogued skill hits plus installed plugin names; `--write` appends only new `[[skills]]` to `catalog.local.toml` for repo-named checkouts and never writes plugin rows; `--write --dry-run` prints that TOML and writes nothing; pytest covers classify+merge without `D:\Code`; README and SKILL.md name `scan`.
