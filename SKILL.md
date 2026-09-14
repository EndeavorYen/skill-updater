---
name: update-harness
description: >
  update: refresh local skills and host plugins from catalog.toml.
  Use when the user says update skills, update plugins, update harness,
  scan skills, scan plugins, sync skills to grok/claude/cursor/codex,
  or runs /update-harness. Run the script. Do not copy SKILL.md by hand.
  Do not rewrite skills.
---

# update-harness

A script owns this job. Do not copy files with the file tools. Do not
rewrite a SKILL.md to "update" it.

## Run

Probe `python3`, then `python`, then `py -3`. First one that prints
JSON from `update.py status --json` (exit 0 or 1) is `<PYTHON>`.
The script picks install.ps1 vs install.sh and junction vs symlink.

`<ROOT>` is this skill directory (the folder that holds this SKILL.md).

```text
<PYTHON> <ROOT>/update.py status
<PYTHON> <ROOT>/update.py skills
<PYTHON> <ROOT>/update.py plugins
<PYTHON> <ROOT>/update.py all
<PYTHON> <ROOT>/update.py scan
```

Pass the user's extra words through (`--dry-run`, `--only NAME`, `--force`,
`--json`, `--write`). No extra words → `status`. Extra words `scan` → `scan`.

Print the script stdout. Stop. Do not open a knife. Personal skill rows go
in `catalog.local.toml`. Do not put machine paths or private repos in
`catalog.toml`.
