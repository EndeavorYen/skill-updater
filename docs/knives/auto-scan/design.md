# Auto-Scan Skill and Plugin Lists — Design

- **Line**: `update-harness`
- **Knife**: `auto-scan skill and plugin lists (#1)`
- **Issue**: https://github.com/EndeavorYen/skill-updater/issues/1
- **Target Reader**: Implementer adding `scan` to [update.py](file:///C:/Users/simon.yen/orca/workspaces/skill-updater/auto-scan-skill-and-plugin-lists/update.py).

---

## 1. Goal & Owning Layer

### Goal
Provide `python update.py scan` to discover local skills across `code_root` and live host skill directories, list installed host plugins via host CLIs, and optionally append new skill entries to `catalog.local.toml` via `--write`.

### Owning Layer
All logic lives directly in [update.py](file:///C:/Users/simon.yen/orca/workspaces/skill-updater/auto-scan-skill-and-plugin-lists/update.py).
- No new packages, sidecars, or external dependencies.
- No schema changes or overlay writes for plugins (`catalog.local.toml` only records skills; plugins remain CLI queries).
- Existing execution commands (`status`, `skills`, `plugins`, `all`) and existing application logic (`apply_skills`, `apply_plugins`) remain untouched.

### Source of Truth
The merged catalog (`catalog.toml` + `catalog.local.toml` loaded via `load_catalog()`) is the authoritative source of truth.
- `scan` is not a third catalog layer.
- Existing overlay rules apply: overlay last-writer wins dest claims.
- Shipped `catalog.toml` stays completely generic and untouched.

### Change Class
Extend CLI parser (`scan`, `--write`), add filesystem discovery and CLI query routines, and add an overlay TOML append adapter.

### Validation
`pytest` suite using `tmp_path` fixtures for filesystem trees and mock/dummy host CLIs. Tests must not depend on real machine layouts (such as `D:\Code`) or network access. Missing host CLIs (`grok`, `claude`) are treated as skips, never test or command failures.

---

## 2. 完成條件 (Acceptance Constraints)

Source of truth: [docs/progress.md](file:///C:/Users/simon.yen/orca/workspaces/skill-updater/auto-scan-skill-and-plugin-lists/docs/progress.md) section "Knife card".

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

---

## 3. Locked 不做什麼 (Non-Goals)

- No `git pull` of source repos.
- No rewriting or modifying other skills' `SKILL.md`.
- No recursive tree scanning across `$HOME` or arbitrary directories outside `code_root` and live host skill directories.
- No `status --scan` flag or dual CLI semantics. `scan` is its own subcommand.
- No per-plugin overlay schema or writing plugin IDs to `catalog.local.toml`.
- No marketplace available-but-not-installed listings.
- No `--write` with `repo` pointing to a host destination real directory copy.
- No inferring `installer` or `command` `dest_skills` from nested `SKILL.md` files.
- No parsing `SKILL.md` frontmatter for skill `name`.
- No mutating or appending `plugin_hosts` from scan results.
- No board `ensure` automation.

---

## 4. Seams & Signatures

> [!NOTE]
> Existing `classify(claim: DestClaim, hosts: dict[str, Host]) -> Row` determines destination installation **state** (`ok`, `stale`, `missing`, `wrong-target`, `real-dir`, `missing-repo`, `missing-src`). It must **not** be overloaded for discovery.

Discovery introduces four distinct seams:

### Seam 1: Directory Kind Classification
Maps an arbitrary directory to its skill `Kind` based on on-disk signatures.

```python
def kind_for_dir(path: Path) -> Kind | None:
    """Classify a directory by checking child signatures in strict first-match order:
    1. 'installer' : repo has (scripts/install.ps1 or scripts/install.sh)
    2. 'command'   : repo has install.py
    3. 'link-pack' : repo has skills/*/SKILL.md (any immediate child of skills/ with SKILL.md)
    4. 'link'      : repo has SKILL.md directly
    5. None        : no match, skip directory
    """
    ...
```

### Seam 2: Skill Discovery & Catalog Matching
Scans scan roots, detects junctions, skips cycles and duplicates, and determines catalog presence.

```python
@dataclass(frozen=True)
class ScanHit:
    name: str
    kind: Kind
    path: Path
    in_catalog: bool
    repo: Path | None  # None if host dest real-dir without a resolvable repo checkout


def scan_skill_hits(catalog: Catalog, hosts: dict[str, Host]) -> tuple[ScanHit, ...]:
    """Scan immediate children of catalog.code_root and live host skill directories.

    Invariants:
    - Reparse points / junctions: inspect link_target(path).
    - If a junction target is outside scan roots or cannot be canonicalized, do not traverse outside.
    - If a target is already under a scan root, do not walk or produce duplicate hits (using same_path / _canon).
    - Skip the checkout of skill-updater itself (ROOT).
    - in_catalog is True if name matches any entry.name in catalog.skills OR any dest name from dest_names(entry).
    - repo is set to the checkout Path if it is a code_root child or a junction target under code_root;
      if it is a host dest real copy without a resolvable repo checkout, repo is None.
    """
    ...
```

### Seam 3: Overlay TOML Generation & Append Adapters
Renders new hits into valid `catalog.local.toml` blocks and manages disk writing.

```python
def overlay_toml(hit: ScanHit, code_root: Path) -> str:
    """Format one [[skills]] TOML table string for a ScanHit.

    Rules:
    - name = hit.name
    - kind = hit.kind
    - repo = '{code_root}/<dir>' when path/repo is a direct child of code_root
    - omit 'hosts' (catalog hosts apply by default)
    - omit 'dest_skills' for installer and command
    - set 'skills_dir = "skills"' for link-pack (omitted if default)
    - omit 'install_ps1' and 'install_sh' (apply defaults to scripts/install.{ps1,sh})
    """
    ...


def write_overlay(
    hits: Iterable[ScanHit],
    local_catalog_path: Path,
    code_root: Path,
    *,
    dry_run: bool,
) -> list[str]:
    """Append new skills to catalog.local.toml.

    Rules:
    - Filter to hits where not in_catalog and repo is not None.
    - Dedup candidate hits by destination name (one TOML entry even if discovered in multiple roots).
    - Never rewrite, format, or delete existing content in catalog.local.toml.
    - If catalog.local.toml does not exist, create it.
    - If dry_run is True, write nothing to disk and return the rendered TOML fragments for stdout.
    - If dry_run is False, append the rendered TOML fragments to local_catalog_path.
    """
    ...
```

### Seam 4: Host Plugin Listing
Adapter over host CLI JSON queries. Missing CLIs are gracefully skipped.

```python
@dataclass(frozen=True)
class PluginHit:
    host: str
    plugin_id: str


def list_installed_plugins(catalog: Catalog) -> list[PluginHit]:
    """Query installed plugins for hosts in catalog.plugin_hosts.

    Rules:
    - Grok: run `grok plugin list --json` if `grok` on PATH. Parse output. Skip if missing.
    - Claude: run `claude plugin list --json` if `claude` on PATH.
      Reuse existing `claude_plugin_ids(payload)`. Skip if missing.
    - Returns list of PluginHit.
    - Read-only; no TOML generation or overlay writing.
    """
    ...
```

---

## 5. CLI Dispatch & Command Flow

### Command Specification
`python update.py scan [--write] [--dry-run] [--catalog PATH]`

- `scan` added to subcommand choices: `choices=["status", "skills", "plugins", "all", "scan"]`.
- `--write` argument added to parser: `action="store_true"`, help="append new skills to catalog.local.toml".
- `--dry-run` is reused from existing parser flags.
- `--force` and `--only` are not used by `scan`.
- `--json` is unplanned for this cut.

### Command Runner
```python
def cmd_scan(
    catalog: Catalog,
    hosts: dict[str, Host],
    *,
    write: bool,
    dry_run: bool,
) -> int:
    """Execute scan workflow:
    1. Discover skill hits across code_root and live host skill dirs.
    2. Query installed plugins from available host CLIs.
    3. Print skill hits table: name, kind, path, catalog status (new vs in-catalog).
    4. Print installed plugin IDs per host.
    5. If write is True:
       - Invoke write_overlay for new hits with resolvable repo.
       - If dry_run is True, print the TOML blocks to stdout.
       - If dry_run is False, write to catalog.local.toml and print confirmation.
    """
    ...
```

---

## 6. Module Map (within `update.py`)

All additions stay within [update.py](file:///C:/Users/simon.yen/orca/workspaces/skill-updater/auto-scan-skill-and-plugin-lists/update.py):

| Section in `update.py` | Components |
| --- | --- |
| **Types & Dataclasses** (~L87) | Add `ScanHit`, `PluginHit` |
| **Kind Discovery** (~L258) | Add `kind_for_dir(path: Path) -> Kind \| None` |
| **Scan Routines** (~L375) | Add `scan_skill_hits(...)`, `list_installed_plugins(...)` |
| **Overlay Formatting** (~L550) | Add `overlay_toml(...)`, `write_overlay(...)` |
| **CLI & Dispatch** (~L685-740) | Add `cmd_scan(...)`, register `scan` and `--write` in `build_parser()`, dispatch in `main()` |

---

## 7. Overlay TOML Output Examples

### Link (`link`)
```toml
[[skills]]
name = "demo-link"
kind = "link"
repo = "{code_root}/demo-link"
```

### Link-Pack (`link-pack`)
```toml
[[skills]]
name = "demo-pack"
kind = "link-pack"
repo = "{code_root}/demo-pack"
skills_dir = "skills"
```

### Installer (`installer`)
```toml
[[skills]]
name = "demo-installer"
kind = "installer"
repo = "{code_root}/demo-installer"
```
*(Notice: `install_ps1` and `install_sh` are omitted because `apply_entry` defaults to `scripts/install.ps1` and `scripts/install.sh`. `hosts` and `dest_skills` are omitted.)*

### Command (`command`)
```toml
[[skills]]
name = "demo-command"
kind = "command"
repo = "{code_root}/demo-command"
```

---

## 8. Walk & Junction Invariants

1. **Root Boundary**: Only scan direct children (`iterdir()`) of `code_root` and live `host.skills` directories. Do not perform recursive directory descent.
2. **Reparse / Junction Handling**:
   - Check `is_reparse_point(child)`. If true, resolve target via `link_target(child)`.
   - If the target resolves to a path already seen under `code_root` or another host dir, skip duplicate scanning using canonical path comparison (`_canon(target) == _canon(known)`).
   - If the target points outside all scan roots, classify only if it satisfies `kind_for_dir`, but do not recurse into it.
3. **Tool Self-Exclusion**: Compare `_canon(child)` against `_canon(ROOT)`. The checkout of `skill-updater` itself is skipped from being proposed as a new skill (its link row is already shipped in generic `catalog.toml`).
4. **Host Real-Directory Copies**: If a child in a host skill directory is a real directory (not a junction/symlink) and does not map to any known checkout under `code_root`, it is classified with `repo = None`. It prints in stdout as `new` or `in_catalog`, but `--write` will never append it as a repo row.

---

## 9. Testing Strategy (Seam Verification)

All tests live in `tests/test_update.py` and run under `pytest` with `tmp_path`:

1. **`test_kind_for_dir`**:
   - Directory with `scripts/install.ps1` -> `"installer"`
   - Directory with `install.py` -> `"command"`
   - Directory with `skills/sub/SKILL.md` -> `"link-pack"`
   - Directory with `SKILL.md` -> `"link"`
   - Directory with `scripts/install.ps1` AND `install.py` -> `"installer"` (precedence check)
   - Directory with `install.py` AND `SKILL.md` -> `"command"` (precedence check)
   - Empty or unrelated directory -> `None`
2. **`test_scan_skill_hits_new_and_in_catalog`**:
   - Construct fixture with `code_root` containing existing cataloged skill and newly created uncataloged skill.
   - Assert `scan_skill_hits` returns `in_catalog=True` for cataloged, `in_catalog=False` for uncataloged.
   - Verify self checkout (`ROOT`) is omitted.
3. **`test_scan_reparse_point_dedup`**:
   - Construct a host skill directory with a junction pointing to a checkout in `code_root`.
   - Verify that the skill is not listed twice or falsely flagged as a missing/duplicate checkout.
4. **`test_write_overlay_dry_run_and_append`**:
   - Test `--write --dry-run` produces expected TOML string and does not create/modify `catalog.local.toml`.
   - Test `--write` appends `[[skills]]` block to existing `catalog.local.toml` preserving comments and existing text.
   - Test `--write` creates `catalog.local.toml` if absent.
   - Test dedup: multiple hits with same destination name generate exactly one overlay entry.
5. **`test_list_installed_plugins_missing_cli`**:
   - Mock `which` returning `None` for grok/claude. Ensure function returns empty list without error or exception.
6. **`test_list_installed_plugins_claude_json`**:
   - Mock subprocess output for `claude plugin list --json` and ensure IDs are extracted via `claude_plugin_ids`.

---

## 10. Future Documentation Updates

When `scan` is implemented, the following documentation updates will be required (outside the scope of this design document):
- [README.md](file:///C:/Users/simon.yen/orca/workspaces/skill-updater/auto-scan-skill-and-plugin-lists/README.md): Document `python update.py scan` and `python update.py scan --write`. Remove *"scanning a code tree for new skills"* from the "Not this tool" non-goals section.
- [SKILL.md](file:///C:/Users/simon.yen/orca/workspaces/skill-updater/auto-scan-skill-and-plugin-lists/SKILL.md): Add `<PYTHON> <ROOT>/update.py scan` to the command execution list.
