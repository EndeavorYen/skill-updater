# update-harness

Refresh local agent skills and host plugins from a catalog. No LLM.
Windows / macOS / Linux. Python 3.11+ (or 3.10 + `tomli`).

```bash
git clone https://github.com/EndeavorYen/skill-updater.git
cd skill-updater
python3 update.py --help
python3 update.py install-shim
python3 update.py scan --write
python3 update.py all
python3 update.py status
python3 update.py sync
```

Windows: `python` if there is no `python3`. `status` is the default. Exit 1 means stale / missing / wrong-target, not a crash; `status` then prints a next-step hint.

Any non-`--dry-run` command writes `~/.local/bin/update-harness` (`.cmd` on Windows), or run `install-shim` first. If that directory is on PATH:

```bash
update-harness scan --write   # discover skills, create catalog.local.toml
update-harness all            # link/install skills and update host plugins
update-harness status         # check health
update-harness sync           # scan --write if needed, then all
update-harness skills --dry-run
```

## Catalog

| File | Role |
| --- | --- |
| `catalog.toml` | Shipped. Host skill dirs + this tool. No personal repos. |
| `catalog.local.toml` | Your overlay. Gitignored. Last `dest_skill` row wins. |
| `catalog.example.toml` | Copy-paste rows for the overlay. |

`code_root` defaults to the parent of this repo (sibling checkouts). Override with `UPDATE_HARNESS_CODE_ROOT` or `code_root = "{home}/Code"` in either catalog file. `--catalog PATH` loads that file only (no overlay).

Missing grok/claude CLIs are skipped, not a failure.

## Kinds

- **installer** — Windows: `scripts/install.ps1`. macOS / Linux: `scripts/install.sh`. If only one file exists, that one runs (`pwsh` or Git Bash as fallback). `status` treats dest `SKILL.md` as present or missing only; it does not hash against the local checkout, because installers often copy a GitHub clone rather than `{code_root}`.
- **command** — argv, `{python}` is `sys.executable`.
- **link / link-pack** — Windows junction, macOS / Linux symlink. `junction` / `junction-pack` still parse.
- **plugins** — `grok plugin update`; Claude marketplace update then each installed plugin.

`GROK_HOME` / `HERMES_HOME` win over `~/.grok` / `~/.hermes` when set.

## Not this tool

- `git pull` of source repos
- rewriting SKILL.md
- deleting a real directory to make a link (`--force` renames it to `.bak` first)

`scan` lists skills under `code_root` and live host skill dirs, plus installed grok/claude plugins. `--write` appends only **new** skill rows to `catalog.local.toml`. It does not rewrite shipped `catalog.toml`. For `installer` / `command` rows, `--write` sets `dest_skills` from the root `SKILL.md` frontmatter `name:` plus nested `*/SKILL.md` (and `skills/*/SKILL.md`) when those dest names are not just the repo directory name. `--write` does not rewrite an existing overlay row; delete that row or hand-edit `dest_skills`, then scan again. Later overlay rows still win dest claims.
