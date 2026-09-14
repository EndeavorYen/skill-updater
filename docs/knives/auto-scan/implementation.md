# Auto-Scan Skill and Plugin Lists — Implementation Plan

- **Line**: `update-harness`
- **Knife**: `auto-scan skill and plugin lists (#1)`
- **Issue**: https://github.com/EndeavorYen/skill-updater/issues/1
- **Branch**: `EndeavorYen/auto-scan-skill-and-plugin-lists` (single PR branch; do not open a second branch)
- **Design Reference**: `docs/knives/auto-scan/design.md`
- **Spec Reference**: `docs/progress.md` (Knife card, 完成條件 1–10)

---

## Goal

Implement the `scan` subcommand and `--write` option in `update.py` to discover local skills across `code_root` and live host skill directories, query installed host plugins via available host CLIs, and optionally append new skill entries to `catalog.local.toml` without modifying `catalog.toml`, altering existing overlay rows, or executing skill/plugin application routines.

---

## 1. Prerequisites and Structural Invariants

1. **Branch**: Work entirely on the existing branch `EndeavorYen/auto-scan-skill-and-plugin-lists`. One PR branch for this knife.
2. **Catalog Integrity**: `catalog.toml` is shipped and generic; it must remain completely untouched. Overlay writes target `catalog.local.toml` exclusively.
3. **No Overloading of State Classification**: Existing `classify(claim: DestClaim, hosts: dict[str, Host]) -> Row` determines installation state (`ok`, `stale`, `missing`, etc.) and remains dest-state only. Discovery logic must not reuse or overload this function.
4. **Filesystem Traversal Invariants**:
   - **Root Boundary**: Only scan immediate children (`iterdir()`) of `code_root` and live `host.skills` directories. Do not perform recursive directory descent.
   - **Reparse Points**: Reparse points and junctions are resolved with `link_target()`. If a junction target is already under a scan root, do not walk it twice; deduplicate using canonical paths (`_canon()` / `same_path()`). If pointing outside scan roots, classify only if it satisfies `kind_for_dir()`, without recursing.
   - **Self-Exclusion**: Compare `_canon(child)` to `_canon(ROOT)`. The checkout of `skill-updater` itself is skipped from new discovery.
   - **Host Real-Directory Copies**: Real directories directly inside a host skill directory that do not resolve to a checkout under `code_root` have `repo = None`. They appear in stdout reports but are never appended to `catalog.local.toml`.

---

## 2. Ordered Implementation Steps (TDD Order)

Follow strict red-before-green TDD for each seam: write failing tests in `tests/test_update.py`, verify red, implement in `update.py`, verify green.

### Step 1: Types and Dataclasses
- **Target File**: `update.py` (~L87)
- **Entities**:
  - `ScanHit(name: str, kind: Kind, path: Path, in_catalog: bool, repo: Path | None)`
  - `PluginHit(host: str, plugin_id: str)`
- **Action**: Define frozen dataclasses matching the signatures in `docs/knives/auto-scan/design.md` §4.

### Step 2: Seam 1 — Directory Classification (`kind_for_dir`)
- **Target Files**:
  - Tests: `tests/test_update.py`
  - Code: `update.py` (~L258)
- **Tests to add in `tests/test_update.py`**:
  - `test_kind_for_dir`:
    - `scripts/install.ps1` or `scripts/install.sh` present -> `"installer"`
    - `install.py` present -> `"command"`
    - `skills/*/SKILL.md` present (immediate subfolder under `skills/`) -> `"link-pack"`
    - `SKILL.md` present directly -> `"link"`
    - Both `scripts/install.ps1` and `install.py` present -> `"installer"` (precedence)
    - Both `install.py` and `SKILL.md` present -> `"command"` (precedence)
    - Empty or non-matching directory -> `None`
- **Function to implement in `update.py`**:
  - `kind_for_dir(path: Path) -> Kind | None`
  - Evaluates child signatures in strict first-match order: `installer` -> `command` -> `link-pack` -> `link` -> `None`.
- **完成條件**: 3

### Step 3: Seam 2 — Skill Discovery (`scan_skill_hits`)
- **Target Files**:
  - Tests: `tests/test_update.py`
  - Code: `update.py` (~L375)
- **Tests to add in `tests/test_update.py`**:
  - `test_scan_skill_hits_new_and_in_catalog`: Verifies immediate children of `code_root` and host skill dirs are scanned, marking `in_catalog=True` if matching catalog `skills` or destination names, and `in_catalog=False` otherwise.
  - `test_scan_reparse_point_dedup`: Verifies host junction pointing back to a checkout under `code_root` is deduplicated via canonical paths (`_canon()`) and does not walk the target directory twice.
  - `test_scan_self_root_exclusion`: Verifies this tool's own repository (`ROOT`) is skipped from being proposed as a new hit.
  - `test_scan_host_real_dir_unmapped`: Verifies real directories in host skill dirs without matching checkouts under `code_root` receive `repo = None`.
- **Function to implement in `update.py`**:
  - `scan_skill_hits(catalog: Catalog, hosts: dict[str, Host]) -> tuple[ScanHit, ...]`
  - Enforces root boundary, junction resolution, duplicate suppression, `ROOT` exclusion, unmapped host real-dir handling (`repo = None`), and catalog membership matching against entry names and `dest_names(entry)`.
- **完成條件**: 2, 3, 4, 8

### Step 4: Seam 3 — Overlay Formatting and Writing (`overlay_toml`, `write_overlay`)
- **Target Files**:
  - Tests: `tests/test_update.py`
  - Code: `update.py` (~L550)
- **Tests to add in `tests/test_update.py`**:
  - `test_overlay_toml_formatting`: Verifies TOML rendering across all kinds:
    - `link`: outputs `name`, `kind = "link"`, `repo = "{code_root}/<dir>"`.
    - `link-pack`: includes `skills_dir = "skills"`.
    - `installer`: omits `dest_skills`, `install_ps1`, `install_sh`, `hosts`.
    - `command`: omits `dest_skills`, `hosts`.
  - `test_write_overlay_dry_run`: Verifies dry-run returns formatted TOML lines without creating or modifying `catalog.local.toml`.
  - `test_write_overlay_append`: Verifies non-dry-run appends new `[[skills]]` blocks to existing `catalog.local.toml` preserving comments and existing rows.
  - `test_write_overlay_creates_file`: Verifies creating `catalog.local.toml` if absent.
  - `test_write_overlay_filters_in_catalog_and_none_repo`: Verifies hits with `in_catalog=True` or `repo=None` are omitted from TOML generation.
  - `test_write_overlay_dedup_dest`: Verifies candidate hits with identical destination names produce exactly one TOML entry.
- **Functions to implement in `update.py`**:
  - `overlay_toml(hit: ScanHit, code_root: Path) -> str`: Formats a single `[[skills]]` block following overlay simplification rules.
  - `write_overlay(hits: Iterable[ScanHit], local_catalog_path: Path, code_root: Path, *, dry_run: bool) -> list[str]`: Filters valid new hits (`not in_catalog` and `repo is not None`), dedups by destination name, formats blocks, and appends to `catalog.local.toml` (or prints if `dry_run`).
- **完成條件**: 4, 6, 7

### Step 5: Seam 4 — Host Plugin Listing (`list_installed_plugins`)
- **Target Files**:
  - Tests: `tests/test_update.py`
  - Code: `update.py` (~L400)
- **Tests to add in `tests/test_update.py`**:
  - `test_list_installed_plugins_missing_cli`: Mocks `which` returning `None` for grok and claude; asserts function returns empty list without raising exceptions.
  - `test_list_installed_plugins_claude_json`: Mocks subprocess output of `claude plugin list --json`; verifies parsing via existing `claude_plugin_ids()`.
  - `test_list_installed_plugins_grok_json`: Mocks subprocess output of `grok plugin list --json`; verifies parsing of plugin IDs.
- **Function to implement in `update.py`**:
  - `list_installed_plugins(catalog: Catalog) -> list[PluginHit]`
  - Queries `grok` and `claude` CLI JSON if host in `catalog.plugin_hosts` and binary exists on `PATH`. Gracefully skips missing tools or unparseable output. Read-only query; never writes to disk.
- **完成條件**: 1, 5

### Step 6: CLI Runner, Parser & Main Dispatch (`cmd_scan`, `build_parser`, `main`)
- **Target Files**:
  - Tests: `tests/test_update.py`
  - Code: `update.py` (~L685–740)
- **Tests to add in `tests/test_update.py`**:
  - `test_cmd_scan_output`: Tests formatted stdout of skill hits and installed plugin IDs.
  - `test_cmd_scan_write_flag`: Tests invocation with `write=True` calling `write_overlay`.
  - `test_parser_scan_choices`: Verifies `scan` is an accepted subcommand choice in `build_parser()`.
  - `test_parser_write_flag`: Verifies `--write` flag parsing.
  - `test_main_scan_dispatch_does_not_apply`: Verifies running `scan` via `main()` does not trigger `apply_skills` or `apply_plugins`.
- **Functions to implement / modify in `update.py`**:
  - `cmd_scan(catalog: Catalog, hosts: dict[str, Host], *, write: bool, dry_run: bool) -> int`: Runs scan and plugin query, formats stdout report, invokes `write_overlay` if `write=True`, returns 0.
  - `build_parser()`: Add `"scan"` to `command` choices (`["status", "skills", "plugins", "all", "scan"]`). Add `--write` argument (`action="store_true"`). Reuse existing `--dry-run` and `--catalog`.
  - `main(argv=None) -> int`: Add dispatch branch for `args.command == "scan"` invoking `cmd_scan(catalog, hosts, write=args.write, dry_run=args.dry_run)` directly without calling `apply_skills` or `apply_plugins`.
- **完成條件**: 1, 5, 6, 7

### Step 7: Documentation Updates
- **Target Files**:
  - `README.md`
  - `SKILL.md`
- **Actions**:
  - In `README.md`: Document `python update.py scan`, `python update.py scan --write`, and `python update.py scan --write --dry-run`. Remove *"scanning a code tree for new skills"* from the "Not this tool" non-goals list.
  - In `SKILL.md`: Add `<PYTHON> <ROOT>/update.py scan` to the Run command list.
  - Leave `catalog.toml` unchanged. Do not rewrite other skills' `SKILL.md`.
- **完成條件**: 10

---

## 3. Out of Order / Do-Not (Locked Non-Goals)

The implementer must not perform any of the following:
- Do not run `git pull` on source repositories.
- Do not rewrite or modify other skills' `SKILL.md` files.
- Do not scan `$HOME` or arbitrary directories outside `code_root` and live host skill directories.
- Do not add `status --scan` or create a dual CLI mode; `scan` is a standalone subcommand.
- Do not create a per-plugin overlay schema or write plugin IDs to `catalog.local.toml`.
- Do not list marketplace available-but-not-installed plugins.
- Do not allow `--write` to emit a `repo` pointing to a host destination real directory copy.
- Do not infer `installer` or `command` `dest_skills` from nested `SKILL.md` files.
- Do not parse `SKILL.md` frontmatter for `name`; the directory basename is the catalog name.
- Do not mutate or append `plugin_hosts` from scan results.
- Do not automate board `ensure`.
- Do not overload or alter existing `classify(claim: DestClaim, hosts: dict[str, Host]) -> Row`.
- Do not create or switch to a second branch; perform all work on `EndeavorYen/auto-scan-skill-and-plugin-lists`.
- Do not modify `catalog.toml`.

---

## 4. Definition of Done

This implementation plan is satisfied when:
1. **Code Matches Design**: All dataclasses, functions, signatures, and CLI dispatch additions in `update.py` adhere to `docs/knives/auto-scan/design.md` §4 and §6.
2. **Test Coverage**: All tests named in Steps 2–6 are added to `tests/test_update.py` and pass via `pytest`, using `tmp_path` fixtures without requiring machine-specific paths (e.g. `D:\Code`) or external network access.
3. **Invariants Preserved**: Immediate-child scanning, reparse point canonical deduplication, `ROOT` self-exclusion, unmapped host real directory handling (`repo = None`), and `classify()` isolation are strictly maintained without loosening.
4. **Observable Behavior**:
   - `python update.py scan` reports skill hits (name, kind, path, catalog status) and installed host plugins.
   - `python update.py scan --write` appends only new repo-named skills to `catalog.local.toml`.
   - `python update.py scan --write --dry-run` prints TOML output without modifying disk.
   - Missing `grok` or `claude` CLIs result in skips, not failure.
5. **Documentation Complete**: `README.md` and `SKILL.md` document `scan` per 完成條件 10; `catalog.toml` remains generic and unmodified.
