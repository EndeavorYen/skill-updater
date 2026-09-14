# Auto-Scan Skill and Plugin Lists — Test Plan

- **Line**: `update-harness`
- **Knife**: `auto-scan skill and plugin lists (#1)`
- **Spec SoT**: `docs/progress.md` (Knife card, 完成條件 1–10)
- **Design SoT**: `docs/knives/auto-scan/design.md` (§9)
- **Implementation SoT**: `docs/knives/auto-scan/implementation.md` (steps 2–6)
- **Target Audience**: Developer running pytest or executing TDD for `scan`.

---

## 1. Test Runner & Isolation Rules

- **Runner**: `pytest` executed against `tests/test_update.py`.
- **Filesystem Isolation**: Every test uses the pytest `tmp_path` fixture for repositories, catalogs, and host directories.
- **Zero Host Layout Dependencies**: No test may depend on `D:\Code`, real user profiles, or fixed host paths.
- **Zero Network & CLI Dependencies**: Tests never invoke live `grok`, `claude`, or external network commands. Host CLIs and filesystem helpers are isolated using `monkeypatch` over `update.which` and `update.subprocess.run`.
- **Skip Semantics**: Missing host binaries evaluate to graceful skips returning empty collections, never exceptions or test failures.
- **Independent Oracle**: Assertions inspect explicit return values (dataclasses, tuples, lists, ints), exact file text (`read_text(encoding="utf-8")`), and captured stdout substrings. No assertions rely on vague heuristic matches or mirror internal private helpers beyond the four public seams and CLI dispatch.

---

## 2. Master Test Inventory

| Test Name | Seam | 完成條件 | Oracle & Expected Values |
| --- | --- | --- | --- |
| `test_kind_for_dir` | Seam 1 (`kind_for_dir`) | 3 | Strict precedence: `installer` > `command` > `link-pack` > `link` > `None`. |
| `test_scan_skill_hits_new_and_in_catalog` | Seam 2 (`scan_skill_hits`) | 2, 3, 4, 8, 9 | Returns `ScanHit` tuples: cataloged items have `in_catalog=True`; uncataloged have `in_catalog=False`. Matches `entry.name` and `dest_names(entry)`. |
| `test_scan_reparse_point_dedup` | Seam 2 (`scan_skill_hits`) | 2, 8, 9 | Junction/symlink in host dir pointing to `code_root` child is deduplicated via canonical paths (`_canon`); no duplicate hit, no double traversal. |
| `test_scan_self_root_exclusion` | Seam 2 (`scan_skill_hits`) | 3, 9 | Tool repository checkout (`ROOT`) is skipped; never emitted as an uncataloged `ScanHit`. |
| `test_scan_host_real_dir_unmapped` | Seam 2 (`scan_skill_hits`) | 2, 4, 6, 9 | Real directory in host skills with no matching checkout in `code_root` receives `repo=None` and `in_catalog=False`. |
| `test_overlay_toml_formatting` | Seam 3 (`overlay_toml`) | 4, 6 | Exact string matches for `link`, `link-pack`, `installer`, and `command`. Omits `hosts` and `dest_skills`. |
| `test_write_overlay_dry_run` | Seam 3 (`write_overlay`) | 6, 7 | Returns list of TOML block strings; asserts target file does not exist on disk. |
| `test_write_overlay_append` | Seam 3 (`write_overlay`) | 6 | Existing file text and comments remain untouched; new `[[skills]]` block appended to file. |
| `test_write_overlay_creates_file` | Seam 3 (`write_overlay`) | 6 | Target file created when initially absent; contents equal rendered TOML block. |
| `test_write_overlay_filters_in_catalog_and_none_repo` | Seam 3 (`write_overlay`) | 4, 6 | Hits with `in_catalog=True` or `repo=None` are excluded from overlay writing. |
| `test_write_overlay_dedup_dest` | Seam 3 (`write_overlay`) | 6 | Multiple hits sharing identical destination name produce exactly one `[[skills]]` entry. |
| `test_list_installed_plugins_missing_cli` | Seam 4 (`list_installed_plugins`) | 1 | `which` returns `None`; function returns `[]` without raising exceptions. |
| `test_list_installed_plugins_claude_json` | Seam 4 (`list_installed_plugins`) | 1, 5 | Mocked JSON list/dict parsed via `claude_plugin_ids`; returns `list[PluginHit]` with host `"claude"`. |
| `test_list_installed_plugins_grok_json` | Seam 4 (`list_installed_plugins`) | 1, 5 | Mocked JSON parsed; returns `list[PluginHit]` with host `"grok"`. |
| `test_cmd_scan_output` | Seam 5 (`cmd_scan`) | 5 | Return code is `0`; stdout contains hit names, kinds, `in-catalog` vs `new`, and host plugin IDs. |
| `test_cmd_scan_write_flag` | Seam 5 (`cmd_scan`) | 6, 7 | `write=True` invokes `write_overlay` and appends to `catalog.local.toml`; stdout reports appended entry. |
| `test_parser_scan_choices` | Seam 5 (`build_parser`) | 1 | `build_parser().parse_args(["scan"])` yields `command="scan"`, `write=False`, `dry_run=False`. |
| `test_parser_write_flag` | Seam 5 (`build_parser`) | 1, 6, 7 | `build_parser().parse_args(["scan", "--write", "--dry-run"])` yields `write=True`, `dry_run=True`. |
| `test_main_scan_dispatch_does_not_apply` | Seam 5 (`main`) | 1 | Invoking `main(["scan"])` executes `cmd_scan` without calling `apply_skills` or `apply_plugins`. |

---

## 3. Concrete Test Specifications

### Seam 1: Directory Classification (`kind_for_dir`)

#### `test_kind_for_dir(tmp_path: Path)`
- **Seam**: `update.kind_for_dir(path: Path) -> Kind | None`
- **完成條件**: 3
- **Test Matrix**:
  | Subfolder Fixture | Signature Files Created | Expected Return Value |
  | --- | --- | --- |
  | `d_ps1` | `scripts/install.ps1` | `"installer"` |
  | `d_sh` | `scripts/install.sh` | `"installer"` |
  | `d_cmd` | `install.py` | `"command"` |
  | `d_pack` | `skills/sub-a/SKILL.md` | `"link-pack"` |
  | `d_link` | `SKILL.md` | `"link"` |
  | `d_prec1` | `scripts/install.ps1` + `install.py` | `"installer"` (precedence: installer over command) |
  | `d_prec2` | `install.py` + `SKILL.md` | `"command"` (precedence: command over link) |
  | `d_empty` | *(empty directory)* | `None` |
  | `d_unrelated` | `README.md`, `setup.py` | `None` |
- **Oracle**: Direct equality assertion `assert update.kind_for_dir(d) == expected`.

---

### Seam 2: Skill Discovery & Catalog Matching (`scan_skill_hits`)

#### `test_scan_skill_hits_new_and_in_catalog(tmp_path: Path)`
- **Seam**: `update.scan_skill_hits(catalog: Catalog, hosts: dict[str, Host]) -> tuple[ScanHit, ...]`
- **完成條件**: 2, 3, 4, 8, 9
- **Setup**:
  - `code_root = tmp_path / "code"`
  - `code_root / "existing-skill" / "SKILL.md"` created.
  - `code_root / "discovered-skill" / "SKILL.md"` created.
  - Catalog initialized with `skills = (SkillEntry(name="existing-skill", kind="link", repo=code_root / "existing-skill", hosts=("grok",)),)`.
- **Oracle**:
  - `hits = update.scan_skill_hits(catalog, catalog.hosts)`
  - Find hit by name:
    - `hit_existing.in_catalog == True`
    - `hit_existing.kind == "link"`
    - `hit_existing.repo == code_root / "existing-skill"`
    - `hit_discovered.in_catalog == False`
    - `hit_discovered.kind == "link"`
    - `hit_discovered.repo == code_root / "discovered-skill"`

#### `test_scan_reparse_point_dedup(tmp_path: Path)`
- **Seam**: `update.scan_skill_hits(catalog: Catalog, hosts: dict[str, Host]) -> tuple[ScanHit, ...]`
- **完成條件**: 2, 8, 9
- **Setup**:
  - `code_root / "pack-repo" / "skills" / "item" / "SKILL.md"` created.
  - Host skills dir `grok_skills / "item"` created as a directory link/junction pointing to `code_root / "pack-repo" / "skills" / "item"`.
- **Oracle**:
  - `scan_skill_hits` resolves targets using canonical path comparison (`_canon`).
  - Exactly one hit is recorded for `pack-repo`; the host junction target is not re-scanned as a separate duplicate skill.

#### `test_scan_self_root_exclusion(tmp_path: Path, monkeypatch)`
- **Seam**: `update.scan_skill_hits(catalog: Catalog, hosts: dict[str, Host]) -> tuple[ScanHit, ...]`
- **完成條件**: 3, 9
- **Setup**:
  - `code_root / "skill-updater"` created with `SKILL.md`.
  - `monkeypatch.setattr(update, "ROOT", code_root / "skill-updater")`.
- **Oracle**:
  - `hits = update.scan_skill_hits(catalog, catalog.hosts)`
  - `assert not any(h.name == "skill-updater" and not h.in_catalog for h in hits)`: the tool's own repository is never proposed as a new uncataloged skill.

#### `test_scan_host_real_dir_unmapped(tmp_path: Path)`
- **Seam**: `update.scan_skill_hits(catalog: Catalog, hosts: dict[str, Host]) -> tuple[ScanHit, ...]`
- **完成條件**: 2, 4, 6, 9
- **Setup**:
  - Host directory `grok_skills / "standalone-skill"` created as a real directory containing `SKILL.md`.
  - No matching checkout exists under `code_root`.
- **Oracle**:
  - Find hit for `"standalone-skill"`:
    - `hit.in_catalog == False`
    - `hit.kind == "link"`
    - `hit.path == grok_skills / "standalone-skill"`
    - `hit.repo is None`: unmapped host copies cannot be referenced as a repo checkout.

---

### Seam 3: Overlay Formatting & Writing (`overlay_toml`, `write_overlay`)

#### `test_overlay_toml_formatting(tmp_path: Path)`
- **Seam**: `update.overlay_toml(hit: ScanHit, code_root: Path) -> str`
- **完成條件**: 4, 6
- **Test Cases**:
  1. `kind="link"`:
     - `ScanHit(name="alpha", kind="link", path=tmp_path / "alpha", in_catalog=False, repo=tmp_path / "alpha")`
     - Output matches:
       ```toml
       [[skills]]
       name = "alpha"
       kind = "link"
       repo = "{code_root}/alpha"
       ```
  2. `kind="link-pack"`:
     - `ScanHit(name="beta", kind="link-pack", path=tmp_path / "beta", in_catalog=False, repo=tmp_path / "beta")`
     - Output matches:
       ```toml
       [[skills]]
       name = "beta"
       kind = "link-pack"
       repo = "{code_root}/beta"
       skills_dir = "skills"
       ```
  3. `kind="installer"`:
     - `ScanHit(name="gamma", kind="installer", path=tmp_path / "gamma", in_catalog=False, repo=tmp_path / "gamma")`
     - Output matches:
       ```toml
       [[skills]]
       name = "gamma"
       kind = "installer"
       repo = "{code_root}/gamma"
       ```
     - Assert `"dest_skills" not in output` and `"hosts" not in output`.
  4. `kind="command"`:
     - `ScanHit(name="delta", kind="command", path=tmp_path / "delta", in_catalog=False, repo=tmp_path / "delta")`
     - Output matches:
       ```toml
       [[skills]]
       name = "delta"
       kind = "command"
       repo = "{code_root}/delta"
       ```
     - Assert `"dest_skills" not in output` and `"hosts" not in output`.

#### `test_write_overlay_dry_run(tmp_path: Path)`
- **Seam**: `update.write_overlay(hits, local_catalog_path, code_root, dry_run=True)`
- **完成條件**: 6, 7
- **Setup**: `local_path = tmp_path / "catalog.local.toml"`. One uncataloged `ScanHit`.
- **Oracle**:
  - Returns `list[str]` containing the formatted TOML blocks.
  - `assert not local_path.exists()`: dry-run must not create or modify files.

#### `test_write_overlay_append(tmp_path: Path)`
- **Seam**: `update.write_overlay(hits, local_catalog_path, code_root, dry_run=False)`
- **完成條件**: 6
- **Setup**:
  - `local_path = tmp_path / "catalog.local.toml"`
  - Initial content: `"# User custom comment\n[[skills]]\nname = \"existing\"\nkind = \"link\"\nrepo = \"{code_root}/existing\"\n"`
  - New hit: `ScanHit(name="new-skill", kind="link", ...)`
- **Oracle**:
  - Content after write starts with `"# User custom comment\n[[skills]]\nname = \"existing\""`.
  - Ends with `[[skills]]\nname = "new-skill"\nkind = "link"\nrepo = "{code_root}/new-skill"\n`.
  - No existing text or comments removed or reordered.

#### `test_write_overlay_creates_file(tmp_path: Path)`
- **Seam**: `update.write_overlay(hits, local_catalog_path, code_root, dry_run=False)`
- **完成條件**: 6
- **Setup**: `local_path = tmp_path / "catalog.local.toml"` does not exist.
- **Oracle**:
  - `assert local_path.is_file()`
  - `assert "name = \"new-skill\"" in local_path.read_text(encoding="utf-8")`

#### `test_write_overlay_filters_in_catalog_and_none_repo(tmp_path: Path)`
- **Seam**: `update.write_overlay(hits, local_catalog_path, code_root, dry_run=False)`
- **完成條件**: 4, 6
- **Setup**:
  - Hit 1: `in_catalog=True`, `repo=path1`
  - Hit 2: `in_catalog=False`, `repo=None` (host real-copy)
  - Hit 3: `in_catalog=False`, `repo=path3` (valid candidate)
- **Oracle**:
  - Returned list has length 1.
  - Written TOML contains only Hit 3's block. Hit 1 and Hit 2 are absent.

#### `test_write_overlay_dedup_dest(tmp_path: Path)`
- **Seam**: `update.write_overlay(hits, local_catalog_path, code_root, dry_run=False)`
- **完成條件**: 6
- **Setup**: Two distinct hits both having `name="duplicate-dest"` and `repo=path`.
- **Oracle**:
  - Output contains exactly one occurrence of `name = "duplicate-dest"`.

---

### Seam 4: Host Plugin Listing (`list_installed_plugins`)

#### `test_list_installed_plugins_missing_cli(tmp_path: Path, monkeypatch)`
- **Seam**: `update.list_installed_plugins(catalog: Catalog) -> list[PluginHit]`
- **完成條件**: 1
- **Setup**:
  - Catalog has `plugin_hosts = ("grok", "claude")`.
  - `monkeypatch.setattr(update, "which", lambda cmd: None)`.
- **Oracle**:
  - `result = update.list_installed_plugins(catalog)`
  - `assert result == []` (graceful skip without raising `FileNotFoundError`).

#### `test_list_installed_plugins_claude_json(tmp_path: Path, monkeypatch)`
- **Seam**: `update.list_installed_plugins(catalog: Catalog) -> list[PluginHit]`
- **完成條件**: 1, 5
- **Setup**:
  - Catalog has `plugin_hosts = ("claude",)`.
  - `monkeypatch.setattr(update, "which", lambda cmd: "/bin/claude" if cmd == "claude" else None)`.
  - Mock `subprocess.run` returning `CompletedProcess(returncode=0, stdout='[{"id": "plugin-1"}, {"id": "plugin-2"}]')`.
- **Oracle**:
  - `result == [PluginHit(host="claude", plugin_id="plugin-1"), PluginHit(host="claude", plugin_id="plugin-2")]`.
  - Also verify object-payload schema `{"plugins": [{"id": "plugin-3"}]}` resolves via `claude_plugin_ids`.

#### `test_list_installed_plugins_grok_json(tmp_path: Path, monkeypatch)`
- **Seam**: `update.list_installed_plugins(catalog: Catalog) -> list[PluginHit]`
- **完成條件**: 1, 5
- **Setup**:
  - Catalog has `plugin_hosts = ("grok",)`.
  - `monkeypatch.setattr(update, "which", lambda cmd: "/bin/grok" if cmd == "grok" else None)`.
  - Mock `subprocess.run` returning `CompletedProcess(returncode=0, stdout='[{"id": "grok-tool"}]')`.
- **Oracle**:
  - `result == [PluginHit(host="grok", plugin_id="grok-tool")]`.

---

### Seam 5: CLI Dispatch & Runner (`cmd_scan`, `build_parser`, `main`)

#### `test_cmd_scan_output(tmp_path: Path, monkeypatch, capsys)`
- **Seam**: `update.cmd_scan(catalog, hosts, write=False, dry_run=False) -> int`
- **完成條件**: 5
- **Setup**:
  - Catalog with 1 cataloged skill, 1 new skill, and mocked host plugin list returning 1 plugin.
- **Oracle**:
  - `code = update.cmd_scan(catalog, hosts, write=False, dry_run=False)`
  - `assert code == 0`
  - Captured stdout contains:
    - `"in-catalog"` for cataloged hit
    - `"new"` for uncataloged hit
    - Plugin ID under host section
    - Does not contain marketplace available-but-not-installed listings.

#### `test_cmd_scan_write_flag(tmp_path: Path, monkeypatch)`
- **Seam**: `update.cmd_scan(catalog, hosts, write=True, dry_run=False) -> int`
- **完成條件**: 6, 7
- **Setup**:
  - Catalog pointing to `tmp_path / "catalog.toml"`.
  - Scan discovers one uncataloged skill.
- **Oracle**:
  - `code = update.cmd_scan(...)`
  - `assert code == 0`
  - `assert (tmp_path / "catalog.local.toml").is_file()`
  - Appended block present in `catalog.local.toml`.

#### `test_parser_scan_choices()`
- **Seam**: `update.build_parser() -> argparse.ArgumentParser`
- **完成條件**: 1
- **Oracle**:
  - `args = update.build_parser().parse_args(["scan"])`
  - `assert args.command == "scan"`
  - `assert args.write is False`
  - `assert args.dry_run is False`

#### `test_parser_write_flag()`
- **Seam**: `update.build_parser() -> argparse.ArgumentParser`
- **完成條件**: 1, 6, 7
- **Oracle**:
  - `args = update.build_parser().parse_args(["scan", "--write", "--dry-run"])`
  - `assert args.command == "scan"`
  - `assert args.write is True`
  - `assert args.dry_run is True`

#### `test_main_scan_dispatch_does_not_apply(monkeypatch)`
- **Seam**: `update.main(argv: list[str]) -> int`
- **完成條件**: 1
- **Setup**:
  - `monkeypatch.setattr(update, "apply_skills", lambda *a, **kw: (_ for _ in ()).throw(AssertionError("apply_skills called")))`
  - `monkeypatch.setattr(update, "apply_plugins", lambda *a, **kw: (_ for _ in ()).throw(AssertionError("apply_plugins called")))`
  - `monkeypatch.setattr(update, "cmd_scan", lambda *a, **kw: 0)`
- **Oracle**:
  - `exit_code = update.main(["scan"])`
  - `assert exit_code == 0`: `scan` delegates directly to `cmd_scan` without invoking application routines.

---

## 4. Non-Pytest Verification Gate (完成條件 10)

完成條件 10 governs documentation synchronization and is verified prior to knife close:

| Document | Path | Verification Criteria |
| --- | --- | --- |
| README | `README.md` | Documents `python update.py scan` and `python update.py scan --write`. Removes "scanning a code tree for new skills" from out-of-scope non-goals. |
| Agent Run List | `SKILL.md` | Includes `<PYTHON> <ROOT>/update.py scan` in the executable command list. |
| Generic Catalog | `catalog.toml` | Remains generic and completely unmodified by scan tests and commands. |

---

## 5. Explicit Out of Scope (Locked Non-Goals)

The test suite enforces that the following features are not implemented:
1. **Marketplace Queries**: No queries for uninstalled or available plugins from registries; stdout reports only currently installed host plugins.
2. **`status --scan` Dual Mode**: `scan` is a standalone parser command. `status` accepts no `--scan` argument.
3. **Plugin Overlay Rows**: `catalog.local.toml` never contains plugin entries or `plugin_hosts` blocks.
4. **Frontmatter Parsing**: Directory names serve as catalog skill names. `SKILL.md` YAML frontmatter is not parsed or asserted for naming.
5. **Fixed Layout Assumptions**: No assertions or fixture setups reference `D:\Code` or real machine roots.
