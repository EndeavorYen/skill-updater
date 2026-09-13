from __future__ import annotations

import json
from pathlib import Path

import update


def installer_entry(repo: Path) -> update.SkillEntry:
    (repo / "scripts").mkdir(parents=True, exist_ok=True)
    (repo / "scripts" / "install.ps1").write_text("# ps1\n", encoding="utf-8")
    (repo / "scripts" / "install.sh").write_text("#!/bin/bash\n", encoding="utf-8")
    return update.SkillEntry(
        name="demo",
        kind="installer",
        repo=repo,
        hosts=("grok",),
        install_ps1="scripts/install.ps1",
        install_sh="scripts/install.sh",
    )


def write_skill(dir_path: Path, body: str = "hello") -> Path:
    dir_path.mkdir(parents=True, exist_ok=True)
    md = dir_path / "SKILL.md"
    md.write_text(body, encoding="utf-8")
    return md


def test_source_skill_md_prefers_nested(tmp_path: Path) -> None:
    repo = tmp_path / "musk-algorithm-skill"
    write_skill(repo, "algo")
    write_skill(repo / "musk-backlog", "nested-backlog")
    entry = update.SkillEntry(
        name="musk-algorithm",
        kind="installer",
        repo=repo,
        hosts=("grok",),
        dest_skills=("musk-algorithm", "musk-backlog"),
    )
    assert update.source_skill_md(entry, "musk-algorithm").read_text(encoding="utf-8") == "algo"
    assert update.source_skill_md(entry, "musk-backlog").read_text(encoding="utf-8") == "nested-backlog"


def test_last_writer_wins_dest_claim(tmp_path: Path) -> None:
    algo = tmp_path / "algo"
    backlog = tmp_path / "backlog"
    write_skill(algo, "algo")
    write_skill(algo / "musk-backlog", "nested")
    write_skill(backlog, "dedicated")
    grok_skills = tmp_path / "grok-skills"
    grok_skills.mkdir()
    catalog = update.Catalog(
        code_root=tmp_path,
        plugin_hosts=(),
        hosts={"grok": update.Host("grok", grok_skills)},
        skills=(
            update.SkillEntry(
                name="musk-algorithm",
                kind="installer",
                repo=algo,
                hosts=("grok",),
                dest_skills=("musk-algorithm", "musk-backlog"),
            ),
            update.SkillEntry(
                name="musk-backlog",
                kind="installer",
                repo=backlog,
                hosts=("grok",),
                dest_skills=("musk-backlog",),
            ),
        ),
    )
    claims = {(c.dest_name, c.owner): c for c in update.claims_for(catalog, catalog.hosts)}
    assert claims[("musk-backlog", "musk-backlog")].source_md.read_text(encoding="utf-8") == "dedicated"
    assert ("musk-algorithm", "musk-algorithm") in claims


def test_classify_stale_and_ok(tmp_path: Path) -> None:
    repo = tmp_path / "gentle"
    dest_root = tmp_path / "skills"
    write_skill(repo, "new")
    write_skill(dest_root / "gentle-grill-me", "old")
    hosts = {"grok": update.Host("grok", dest_root)}
    claim = update.DestClaim(
        host="grok",
        dest_name="gentle-grill-me",
        source_md=repo / "SKILL.md",
        method="installer",
        source_dir=repo,
        owner="gentle-grill-me",
    )
    row = update.classify(claim, hosts)
    assert row.state == "stale"
    (dest_root / "gentle-grill-me" / "SKILL.md").write_text("new", encoding="utf-8")
    assert update.classify(claim, hosts).state == "ok"


def test_classify_missing(tmp_path: Path) -> None:
    repo = tmp_path / "gentle"
    write_skill(repo, "new")
    hosts = {"grok": update.Host("grok", tmp_path / "skills")}
    claim = update.DestClaim(
        host="grok",
        dest_name="gentle-grill-me",
        source_md=repo / "SKILL.md",
        method="installer",
        source_dir=repo,
        owner="gentle-grill-me",
    )
    assert update.classify(claim, hosts).state == "missing"


def test_ensure_junction_and_refuse_real_dir(tmp_path: Path) -> None:
    src = tmp_path / "src" / "wf-ex"
    write_skill(src, "pack")
    dest_root = tmp_path / "skills"
    dest = dest_root / "wf-ex"
    result = update.ensure_junction(src, dest, force=False, dry_run=False)
    assert result == "linked"
    assert update.same_path(update.junction_target(dest), src)
    assert update.ensure_junction(src, dest, force=False, dry_run=False) == "ok"

    other = tmp_path / "other"
    write_skill(other, "other")
    retarget = update.ensure_junction(other, dest, force=False, dry_run=False)
    assert retarget == "linked"
    assert update.same_path(update.junction_target(dest), other)

    real = dest_root / "real-skill"
    write_skill(real, "copy")
    blocked = update.ensure_junction(src, real, force=False, dry_run=False)
    assert blocked == "real-dir"
    assert (real / "SKILL.md").read_text(encoding="utf-8") == "copy"

    forced = update.ensure_junction(src, real, force=True, dry_run=False)
    assert forced == "linked"
    assert update.same_path(update.junction_target(real), src)
    bak = dest_root / "real-skill.bak"
    assert (bak / "SKILL.md").read_text(encoding="utf-8") == "copy"


def test_remove_reparse_does_not_delete_source(tmp_path: Path) -> None:
    src = tmp_path / "src"
    write_skill(src, "keep")
    dest = tmp_path / "link"
    update.create_junction(src, dest)
    update.remove_reparse_point(dest)
    assert not dest.exists()
    assert (src / "SKILL.md").read_text(encoding="utf-8") == "keep"


def test_claude_plugin_ids() -> None:
    payload = [
        {"id": "pstack@x", "version": "1"},
        {"id": "omc@omc"},
    ]
    assert update.claude_plugin_ids(payload) == ["pstack@x", "omc@omc"]
    assert update.claude_plugin_ids({"plugins": payload}) == ["pstack@x", "omc@omc"]


def test_pack_skill_dirs_skips_docs_only(tmp_path: Path) -> None:
    pack = tmp_path / "skills"
    write_skill(pack / "wf-ex", "stub")
    (pack / "forge-issue-board" / "references").mkdir(parents=True)
    (pack / "forge-issue-board" / "references" / "design.md").write_text("x", encoding="utf-8")
    entry = update.SkillEntry(
        name="workflow-ex",
        kind="link-pack",
        repo=tmp_path,
        hosts=("grok",),
        skills_dir="skills",
    )
    names = [p.name for p in update.pack_skill_dirs(entry)]
    assert names == ["wf-ex"]


def test_load_catalog_interpolates(tmp_path: Path) -> None:
    catalog = tmp_path / "catalog.toml"
    catalog.write_text(
        """
code_root = "{home}/code"
plugin_hosts = ["grok"]

[hosts.grok]
skills = "~/.grok/skills"

[[skills]]
name = "example-skill"
kind = "command"
repo = "{code_root}/example-skill"
argv = ["{python}", "install.py"]
dest_skills = ["example-skill"]
hosts = ["grok"]
""",
        encoding="utf-8",
    )
    loaded = update.load_catalog(catalog, python="/usr/bin/python3")
    assert loaded.skills[0].repo == Path.home() / "code" / "example-skill"
    assert loaded.skills[0].argv[0] == "/usr/bin/python3"


def test_display_path_strips_extended_prefix() -> None:
    assert update.display_path(Path(r"\\?\D:\Code\workflow-ex")) == r"D:\Code\workflow-ex"
    assert update.display_path("//?/D:/Code/x") == "D:/Code/x"


def test_shipped_catalog_is_generic() -> None:
    loaded = update.load_catalog(update.ROOT / "catalog.toml")
    assert loaded.code_root == update.ROOT.parent
    assert [s.name for s in loaded.skills] == ["update-harness"]
    assert loaded.skills[0].kind == "link"
    assert loaded.skills[0].repo == update.ROOT
    text = (update.ROOT / "catalog.toml").read_text(encoding="utf-8")
    assert "musk-" not in text
    assert "sesstalk" not in text
    assert "workflow-ex" not in text
    assert "shuohao" not in text


def test_local_overlay_merges_after_shipped(tmp_path: Path) -> None:
    (tmp_path / "catalog.toml").write_text(
        """
plugin_hosts = ["grok"]
[hosts.grok]
skills = "~/.grok/skills"
[[skills]]
name = "update-harness"
kind = "link"
repo = "{code_root}/update-harness"
hosts = ["grok"]
""",
        encoding="utf-8",
    )
    (tmp_path / "catalog.local.toml").write_text(
        """
[[skills]]
name = "extra"
kind = "installer"
repo = "{code_root}/extra"
dest_skills = ["extra"]
hosts = ["grok"]
""",
        encoding="utf-8",
    )
    loaded = update.load_catalog(root=tmp_path)
    assert [s.name for s in loaded.skills] == ["update-harness", "extra"]


def test_explicit_catalog_skips_overlay(tmp_path: Path) -> None:
    shipped = tmp_path / "only.toml"
    shipped.write_text(
        """
plugin_hosts = []
[hosts.grok]
skills = "~/.grok/skills"
[[skills]]
name = "update-harness"
kind = "link"
repo = "{code_root}/update-harness"
hosts = ["grok"]
""",
        encoding="utf-8",
    )
    (tmp_path / "catalog.local.toml").write_text(
        """
[[skills]]
name = "extra"
kind = "link"
repo = "{code_root}/extra"
hosts = ["grok"]
""",
        encoding="utf-8",
    )
    loaded = update.load_catalog(shipped, root=tmp_path)
    assert [s.name for s in loaded.skills] == ["update-harness"]


def test_kind_alias_junction_pack(tmp_path: Path) -> None:
    catalog = tmp_path / "catalog.toml"
    catalog.write_text(
        """
plugin_hosts = []

[hosts.grok]
skills = "~/.grok/skills"

[[skills]]
name = "workflow-ex"
kind = "junction-pack"
repo = "{code_root}/workflow-ex"
skills_dir = "skills"
hosts = ["grok"]
""",
        encoding="utf-8",
    )
    loaded = update.load_catalog(catalog)
    assert loaded.skills[0].kind == "link-pack"


def test_code_root_env_override(tmp_path: Path, monkeypatch) -> None:
    catalog = tmp_path / "catalog.toml"
    catalog.write_text(
        """
plugin_hosts = []
[hosts.grok]
skills = "~/.grok/skills"
""",
        encoding="utf-8",
    )
    monkeypatch.setenv("UPDATE_HARNESS_CODE_ROOT", str(tmp_path / "src"))
    loaded = update.load_catalog(catalog)
    assert loaded.code_root == tmp_path / "src"


def test_installer_argv_windows_prefers_ps1(tmp_path: Path, monkeypatch) -> None:
    entry = installer_entry(tmp_path / "repo")
    monkeypatch.setattr(update.os, "name", "nt")
    monkeypatch.setattr(
        update,
        "which",
        lambda cmd: r"C:\Windows\System32\WindowsPowerShell\v1.0\powershell.exe"
        if cmd == "powershell"
        else None,
    )
    argv = update.installer_argv(entry, "grok")
    assert argv[0].endswith("powershell.exe")
    assert argv[-2].endswith("install.ps1")
    assert argv[-1] == "grok"


def test_installer_argv_posix_prefers_sh(tmp_path: Path, monkeypatch) -> None:
    entry = installer_entry(tmp_path / "repo")
    monkeypatch.setattr(update.os, "name", "posix")
    monkeypatch.setattr(update, "which", lambda cmd: f"/bin/{cmd}" if cmd in ("bash", "sh") else None)
    argv = update.installer_argv(entry, "claude")
    assert argv[0] == "/bin/bash"
    assert argv[1].endswith("install.sh")
    assert argv[2] == "claude"


def test_write_shim_posix(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(update.os, "name", "posix")
    monkeypatch.setattr(update, "home", lambda: tmp_path)
    update.write_shim()
    shim = tmp_path / ".local" / "bin" / "update-harness"
    text = shim.read_text(encoding="utf-8")
    assert text.startswith("#!/bin/sh\n")
    assert "update.py" in text
    assert "$@" in text


def test_status_json_roundtrip(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    write_skill(repo, "x")
    dest_root = tmp_path / "skills"
    write_skill(dest_root / "repo", "x")
    catalog = update.Catalog(
        code_root=tmp_path,
        plugin_hosts=(),
        hosts={"grok": update.Host("grok", dest_root)},
        skills=(
            update.SkillEntry(
                name="repo",
                kind="installer",
                repo=repo,
                hosts=("grok",),
                dest_skills=("repo",),
            ),
        ),
    )
    rows = update.status_rows(catalog, catalog.hosts)
    dumped = json.dumps([r.__dict__ for r in rows])
    assert '"state": "ok"' in dumped
