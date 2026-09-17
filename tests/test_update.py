from __future__ import annotations

import json
import subprocess
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


def test_classify_command_stale_and_ok(tmp_path: Path) -> None:
    repo = tmp_path / "gentle"
    dest_root = tmp_path / "skills"
    write_skill(repo, "new")
    write_skill(dest_root / "gentle-grill-me", "old")
    hosts = {"grok": update.Host("grok", dest_root)}
    claim = update.DestClaim(
        host="grok",
        dest_name="gentle-grill-me",
        source_md=repo / "SKILL.md",
        method="command",
        source_dir=repo,
        owner="gentle-grill-me",
    )
    row = update.classify(claim, hosts)
    assert row.state == "stale"
    (dest_root / "gentle-grill-me" / "SKILL.md").write_text("new", encoding="utf-8")
    assert update.classify(claim, hosts).state == "ok"


def test_classify_installer_ok_when_dest_skill_md_differs(tmp_path: Path) -> None:
    repo = tmp_path / "gentle"
    dest_root = tmp_path / "skills"
    write_skill(repo, "checkout")
    write_skill(dest_root / "gentle-grill-me", "github-copy")
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
    assert row.state == "ok"


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


def test_kind_for_dir(tmp_path: Path) -> None:
    d_ps1 = tmp_path / "d_ps1"
    (d_ps1 / "scripts").mkdir(parents=True)
    (d_ps1 / "scripts" / "install.ps1").write_text("# ps1\n", encoding="utf-8")
    d_sh = tmp_path / "d_sh"
    (d_sh / "scripts").mkdir(parents=True)
    (d_sh / "scripts" / "install.sh").write_text("#!/bin/bash\n", encoding="utf-8")
    d_cmd = tmp_path / "d_cmd"
    d_cmd.mkdir()
    (d_cmd / "install.py").write_text("print(1)\n", encoding="utf-8")
    d_pack = tmp_path / "d_pack"
    write_skill(d_pack / "skills" / "sub-a", "pack")
    d_link = tmp_path / "d_link"
    write_skill(d_link, "link")
    d_prec1 = tmp_path / "d_prec1"
    (d_prec1 / "scripts").mkdir(parents=True)
    (d_prec1 / "scripts" / "install.ps1").write_text("# ps1\n", encoding="utf-8")
    (d_prec1 / "install.py").write_text("print(1)\n", encoding="utf-8")
    d_prec2 = tmp_path / "d_prec2"
    write_skill(d_prec2, "link")
    (d_prec2 / "install.py").write_text("print(1)\n", encoding="utf-8")
    d_empty = tmp_path / "d_empty"
    d_empty.mkdir()
    d_unrelated = tmp_path / "d_unrelated"
    d_unrelated.mkdir()
    (d_unrelated / "README.md").write_text("x\n", encoding="utf-8")
    (d_unrelated / "setup.py").write_text("x\n", encoding="utf-8")

    assert update.kind_for_dir(d_ps1) == "installer"
    assert update.kind_for_dir(d_sh) == "installer"
    assert update.kind_for_dir(d_cmd) == "command"
    assert update.kind_for_dir(d_pack) == "link-pack"
    assert update.kind_for_dir(d_link) == "link"
    assert update.kind_for_dir(d_prec1) == "installer"
    assert update.kind_for_dir(d_prec2) == "command"
    assert update.kind_for_dir(d_empty) is None
    assert update.kind_for_dir(d_unrelated) is None


def _scan_catalog(
    tmp_path: Path,
    *,
    code_root: Path | None = None,
    skills: tuple[update.SkillEntry, ...] = (),
    plugin_hosts: tuple[str, ...] = (),
    hosts: dict[str, update.Host] | None = None,
) -> update.Catalog:
    code_root = code_root or (tmp_path / "code")
    code_root.mkdir(parents=True, exist_ok=True)
    grok = tmp_path / "grok-skills"
    grok.mkdir(parents=True, exist_ok=True)
    return update.Catalog(
        code_root=code_root,
        plugin_hosts=plugin_hosts,
        hosts=hosts or {"grok": update.Host("grok", grok)},
        skills=skills,
        source_dir=tmp_path,
    )


def test_scan_skill_hits_new_and_in_catalog(tmp_path: Path) -> None:
    code_root = tmp_path / "code"
    write_skill(code_root / "existing-skill", "old")
    write_skill(code_root / "discovered-skill", "new")
    catalog = _scan_catalog(
        tmp_path,
        code_root=code_root,
        skills=(
            update.SkillEntry(
                name="existing-skill",
                kind="link",
                repo=code_root / "existing-skill",
                hosts=("grok",),
            ),
        ),
    )
    hits = {h.name: h for h in update.scan_skill_hits(catalog, catalog.hosts)}
    hit_existing = hits["existing-skill"]
    hit_discovered = hits["discovered-skill"]
    assert hit_existing.in_catalog is True
    assert hit_existing.kind == "link"
    assert hit_existing.repo == code_root / "existing-skill"
    assert hit_discovered.in_catalog is False
    assert hit_discovered.kind == "link"
    assert hit_discovered.repo == code_root / "discovered-skill"


def test_scan_reparse_point_dedup(tmp_path: Path) -> None:
    code_root = tmp_path / "code"
    write_skill(code_root / "pack-repo" / "skills" / "item", "pack")
    grok_skills = tmp_path / "grok-skills"
    grok_skills.mkdir()
    update.create_junction(code_root / "pack-repo" / "skills" / "item", grok_skills / "item")
    catalog = _scan_catalog(
        tmp_path,
        code_root=code_root,
        hosts={"grok": update.Host("grok", grok_skills)},
    )
    hits = update.scan_skill_hits(catalog, catalog.hosts)
    pack_hits = [h for h in hits if h.name == "pack-repo"]
    assert len(pack_hits) == 1
    assert not any(h.name == "item" for h in hits)


def test_scan_self_root_exclusion(tmp_path: Path, monkeypatch) -> None:
    code_root = tmp_path / "code"
    write_skill(code_root / "skill-updater", "self")
    monkeypatch.setattr(update, "ROOT", code_root / "skill-updater")
    catalog = _scan_catalog(tmp_path, code_root=code_root)
    hits = update.scan_skill_hits(catalog, catalog.hosts)
    assert not any(h.name == "skill-updater" and not h.in_catalog for h in hits)


def test_scan_host_real_dir_unmapped(tmp_path: Path) -> None:
    grok_skills = tmp_path / "grok-skills"
    write_skill(grok_skills / "standalone-skill", "copy")
    catalog = _scan_catalog(
        tmp_path,
        hosts={"grok": update.Host("grok", grok_skills)},
    )
    hits = {h.name: h for h in update.scan_skill_hits(catalog, catalog.hosts)}
    hit = hits["standalone-skill"]
    assert hit.in_catalog is False
    assert hit.kind == "link"
    assert hit.path == grok_skills / "standalone-skill"
    assert hit.repo is None


def test_overlay_toml_formatting(tmp_path: Path) -> None:
    def hit(name: str, kind: update.Kind) -> update.ScanHit:
        return update.ScanHit(
            name=name,
            kind=kind,
            path=tmp_path / name,
            in_catalog=False,
            repo=tmp_path / name,
        )

    link = update.overlay_toml(hit("alpha", "link"), tmp_path)
    assert link == (
        "[[skills]]\n"
        'name = "alpha"\n'
        'kind = "link"\n'
        'repo = "{code_root}/alpha"\n'
    )
    pack = update.overlay_toml(hit("beta", "link-pack"), tmp_path)
    assert pack == (
        "[[skills]]\n"
        'name = "beta"\n'
        'kind = "link-pack"\n'
        'repo = "{code_root}/beta"\n'
        'skills_dir = "skills"\n'
    )
    installer = update.overlay_toml(hit("gamma", "installer"), tmp_path)
    assert installer == (
        "[[skills]]\n"
        'name = "gamma"\n'
        'kind = "installer"\n'
        'repo = "{code_root}/gamma"\n'
    )
    assert "dest_skills" not in installer
    assert "hosts" not in installer
    command = update.overlay_toml(hit("delta", "command"), tmp_path)
    assert command == (
        "[[skills]]\n"
        'name = "delta"\n'
        'kind = "command"\n'
        'repo = "{code_root}/delta"\n'
    )
    assert "dest_skills" not in command
    assert "hosts" not in command


def test_overlay_toml_installer_infers_multi_dest_skills(tmp_path: Path) -> None:
    repo = tmp_path / "musk-algorithm-skill"
    write_skill(repo, "---\nname: musk-algorithm\n---\nalgo\n")
    write_skill(repo / "musk-backlog", "nested-backlog\n")
    (repo / "scripts").mkdir(parents=True)
    (repo / "scripts" / "install.sh").write_text("#!/bin/bash\n", encoding="utf-8")
    hit = update.ScanHit(
        name="musk-algorithm-skill",
        kind="installer",
        path=repo,
        in_catalog=False,
        repo=repo,
    )
    text = update.overlay_toml(hit, tmp_path)
    assert 'dest_skills = ["musk-algorithm", "musk-backlog"]' in text
    assert "hosts" not in text


def test_overlay_toml_omits_dest_skills_when_same_as_name(tmp_path: Path) -> None:
    repo = tmp_path / "gamma"
    write_skill(repo, "---\nname: gamma\n---\nbody\n")
    (repo / "scripts").mkdir(parents=True)
    (repo / "scripts" / "install.sh").write_text("#!/bin/bash\n", encoding="utf-8")
    hit = update.ScanHit(
        name="gamma",
        kind="installer",
        path=repo,
        in_catalog=False,
        repo=repo,
    )
    assert "dest_skills" not in update.overlay_toml(hit, tmp_path)


def test_overlay_toml_command_infers_nested_dest_skills(tmp_path: Path) -> None:
    repo = tmp_path / "delta"
    repo.mkdir()
    (repo / "install.py").write_text("print(1)\n", encoding="utf-8")
    write_skill(repo / "copied-skill", "nested\n")
    hit = update.ScanHit(
        name="delta",
        kind="command",
        path=repo,
        in_catalog=False,
        repo=repo,
    )
    text = update.overlay_toml(hit, tmp_path)
    assert 'dest_skills = ["copied-skill"]' in text


def test_inferred_dest_skills_includes_pack_children(tmp_path: Path) -> None:
    repo = tmp_path / "pack-installer"
    (repo / "scripts").mkdir(parents=True)
    (repo / "scripts" / "install.sh").write_text("#!/bin/bash\n", encoding="utf-8")
    write_skill(repo / "skills" / "pack-item", "pack\n")
    assert update.inferred_dest_skills(repo, "pack-installer") == ("pack-item",)


def test_inferred_dest_skills_skips_skills_dir_skill_md(tmp_path: Path) -> None:
    repo = tmp_path / "my-command-skill"
    repo.mkdir()
    (repo / "install.py").write_text("print(1)\n", encoding="utf-8")
    write_skill(repo / "skills", "---\nname: my-command-skill\n---\nbody\n")
    assert update.inferred_dest_skills(repo, "my-command-skill") == ()
    hit = update.ScanHit(
        name="my-command-skill",
        kind="command",
        path=repo,
        in_catalog=False,
        repo=repo,
    )
    assert "dest_skills" not in update.overlay_toml(hit, tmp_path)


def test_scan_write_installer_dests_are_not_missing(tmp_path: Path) -> None:
    code_root = tmp_path / "code"
    repo = code_root / "musk-algorithm-skill"
    write_skill(repo, "---\nname: musk-algorithm\n---\nalgo\n")
    write_skill(repo / "musk-backlog", "backlog\n")
    (repo / "scripts").mkdir(parents=True)
    (repo / "scripts" / "install.sh").write_text("#!/bin/bash\n", encoding="utf-8")
    grok_skills = tmp_path / "grok-skills"
    write_skill(grok_skills / "musk-algorithm", "---\nname: musk-algorithm\n---\nalgo\n")
    write_skill(grok_skills / "musk-backlog", "backlog\n")
    catalog = _scan_catalog(
        tmp_path,
        code_root=code_root,
        hosts={"grok": update.Host("grok", grok_skills)},
    )
    overlay = tmp_path / "catalog.local.toml"
    hits = update.scan_skill_hits(catalog, catalog.hosts)
    update.write_overlay(hits, overlay, code_root, dry_run=False)
    shipped = tmp_path / "catalog.toml"
    shipped.write_text(
        f"""
plugin_hosts = []
code_root = "{code_root.as_posix()}"
[hosts.grok]
skills = "{grok_skills.as_posix()}"
""",
        encoding="utf-8",
    )
    loaded = update.load_catalog(root=tmp_path)
    entry = next(s for s in loaded.skills if s.name == "musk-algorithm-skill")
    assert update.dest_names(entry) == ["musk-algorithm", "musk-backlog"]
    rows = [r for r in update.status_rows(loaded, loaded.hosts) if r.owner == "musk-algorithm-skill"]
    assert {r.dest: r.state for r in rows} == {
        "musk-algorithm": "ok",
        "musk-backlog": "ok",
    }


def test_write_overlay_dry_run(tmp_path: Path) -> None:
    local_path = tmp_path / "catalog.local.toml"
    repo = tmp_path / "new-skill"
    hits = (
        update.ScanHit(
            name="new-skill",
            kind="link",
            path=repo,
            in_catalog=False,
            repo=repo,
        ),
    )
    blocks = update.write_overlay(hits, local_path, tmp_path, dry_run=True)
    assert any('name = "new-skill"' in b for b in blocks)
    assert not local_path.exists()


def test_write_overlay_append(tmp_path: Path) -> None:
    local_path = tmp_path / "catalog.local.toml"
    local_path.write_text(
        '# User custom comment\n[[skills]]\nname = "existing"\nkind = "link"\nrepo = "{code_root}/existing"\n',
        encoding="utf-8",
    )
    repo = tmp_path / "new-skill"
    hits = (
        update.ScanHit(
            name="new-skill",
            kind="link",
            path=repo,
            in_catalog=False,
            repo=repo,
        ),
    )
    update.write_overlay(hits, local_path, tmp_path, dry_run=False)
    text = local_path.read_text(encoding="utf-8")
    assert text.startswith('# User custom comment\n[[skills]]\nname = "existing"')
    assert text.endswith(
        '[[skills]]\nname = "new-skill"\nkind = "link"\nrepo = "{code_root}/new-skill"\n'
    )


def test_write_overlay_creates_file(tmp_path: Path) -> None:
    local_path = tmp_path / "catalog.local.toml"
    repo = tmp_path / "new-skill"
    hits = (
        update.ScanHit(
            name="new-skill",
            kind="link",
            path=repo,
            in_catalog=False,
            repo=repo,
        ),
    )
    update.write_overlay(hits, local_path, tmp_path, dry_run=False)
    assert local_path.is_file()
    assert 'name = "new-skill"' in local_path.read_text(encoding="utf-8")


def test_write_overlay_filters_in_catalog_and_none_repo(tmp_path: Path) -> None:
    local_path = tmp_path / "catalog.local.toml"
    path1 = tmp_path / "one"
    path3 = tmp_path / "three"
    hits = (
        update.ScanHit(name="one", kind="link", path=path1, in_catalog=True, repo=path1),
        update.ScanHit(
            name="two",
            kind="link",
            path=tmp_path / "two",
            in_catalog=False,
            repo=None,
        ),
        update.ScanHit(name="three", kind="link", path=path3, in_catalog=False, repo=path3),
    )
    blocks = update.write_overlay(hits, local_path, tmp_path, dry_run=False)
    assert len(blocks) == 1
    text = local_path.read_text(encoding="utf-8")
    assert 'name = "three"' in text
    assert 'name = "one"' not in text
    assert 'name = "two"' not in text


def test_write_overlay_dedup_dest(tmp_path: Path) -> None:
    local_path = tmp_path / "catalog.local.toml"
    repo = tmp_path / "duplicate-dest"
    hits = (
        update.ScanHit(
            name="duplicate-dest",
            kind="link",
            path=repo,
            in_catalog=False,
            repo=repo,
        ),
        update.ScanHit(
            name="duplicate-dest",
            kind="link",
            path=tmp_path / "other",
            in_catalog=False,
            repo=repo,
        ),
    )
    update.write_overlay(hits, local_path, tmp_path, dry_run=False)
    assert local_path.read_text(encoding="utf-8").count('name = "duplicate-dest"') == 1


def test_list_installed_plugins_missing_cli(tmp_path: Path, monkeypatch) -> None:
    catalog = _scan_catalog(tmp_path, plugin_hosts=("grok", "claude"))
    monkeypatch.setattr(update, "which", lambda cmd: None)
    assert update.list_installed_plugins(catalog) == []


def test_list_installed_plugins_claude_json(tmp_path: Path, monkeypatch) -> None:
    catalog = _scan_catalog(tmp_path, plugin_hosts=("claude",))
    monkeypatch.setattr(
        update, "which", lambda cmd: "/bin/claude" if cmd == "claude" else None
    )
    monkeypatch.setattr(
        update.subprocess,
        "run",
        lambda *a, **kw: subprocess.CompletedProcess(
            a[0], 0, stdout='[{"id": "plugin-1"}, {"id": "plugin-2"}]', stderr=""
        ),
    )
    result = update.list_installed_plugins(catalog)
    assert result == [
        update.PluginHit(host="claude", plugin_id="plugin-1"),
        update.PluginHit(host="claude", plugin_id="plugin-2"),
    ]
    assert update.claude_plugin_ids({"plugins": [{"id": "plugin-3"}]}) == ["plugin-3"]


def test_list_installed_plugins_grok_json(tmp_path: Path, monkeypatch) -> None:
    catalog = _scan_catalog(tmp_path, plugin_hosts=("grok",))
    monkeypatch.setattr(update, "which", lambda cmd: "/bin/grok" if cmd == "grok" else None)
    monkeypatch.setattr(
        update.subprocess,
        "run",
        lambda *a, **kw: subprocess.CompletedProcess(
            a[0], 0, stdout='[{"id": "grok-tool"}]', stderr=""
        ),
    )
    assert update.list_installed_plugins(catalog) == [
        update.PluginHit(host="grok", plugin_id="grok-tool")
    ]


def test_cmd_scan_output(tmp_path: Path, monkeypatch, capsys) -> None:
    code_root = tmp_path / "code"
    write_skill(code_root / "existing-skill", "old")
    write_skill(code_root / "discovered-skill", "new")
    catalog = _scan_catalog(
        tmp_path,
        code_root=code_root,
        plugin_hosts=("grok",),
        skills=(
            update.SkillEntry(
                name="existing-skill",
                kind="link",
                repo=code_root / "existing-skill",
                hosts=("grok",),
            ),
        ),
    )
    monkeypatch.setattr(update, "which", lambda cmd: "/bin/grok" if cmd == "grok" else None)
    monkeypatch.setattr(
        update.subprocess,
        "run",
        lambda *a, **kw: subprocess.CompletedProcess(
            a[0], 0, stdout='[{"id": "demo-plugin"}]', stderr=""
        ),
    )
    code = update.cmd_scan(catalog, catalog.hosts, write=False, dry_run=False)
    assert code == 0
    out = capsys.readouterr().out
    assert "in-catalog" in out
    assert "new" in out
    assert "demo-plugin" in out
    assert "marketplace" not in out.lower()


def test_cmd_scan_write_flag(tmp_path: Path) -> None:
    code_root = tmp_path / "code"
    write_skill(code_root / "fresh-skill", "x")
    catalog = _scan_catalog(tmp_path, code_root=code_root)
    code = update.cmd_scan(catalog, catalog.hosts, write=True, dry_run=False)
    assert code == 0
    local = tmp_path / "catalog.local.toml"
    assert local.is_file()
    assert 'name = "fresh-skill"' in local.read_text(encoding="utf-8")


def test_parser_scan_choices() -> None:
    args = update.build_parser().parse_args(["scan"])
    assert args.command == "scan"
    assert args.write is False
    assert args.dry_run is False


def test_parser_write_flag() -> None:
    args = update.build_parser().parse_args(["scan", "--write", "--dry-run"])
    assert args.command == "scan"
    assert args.write is True
    assert args.dry_run is True


def test_main_scan_dispatch_does_not_apply(monkeypatch) -> None:
    monkeypatch.setattr(
        update,
        "apply_skills",
        lambda *a, **kw: (_ for _ in ()).throw(AssertionError("apply_skills called")),
    )
    monkeypatch.setattr(
        update,
        "apply_plugins",
        lambda *a, **kw: (_ for _ in ()).throw(AssertionError("apply_plugins called")),
    )
    monkeypatch.setattr(update, "cmd_scan", lambda *a, **kw: 0)
    assert update.main(["scan"]) == 0


def test_cmd_scan_write_dry_run(tmp_path: Path, capsys) -> None:
    code_root = tmp_path / "code"
    write_skill(code_root / "fresh-skill", "x")
    catalog = _scan_catalog(tmp_path, code_root=code_root)
    code = update.cmd_scan(catalog, catalog.hosts, write=True, dry_run=True)
    assert code == 0
    out = capsys.readouterr().out
    assert 'name = "fresh-skill"' in out
    assert not (tmp_path / "catalog.local.toml").exists()


def test_overlay_toml_escapes_quotes(tmp_path: Path) -> None:
    hit = update.ScanHit(
        name='odd"name',
        kind="link",
        path=tmp_path / 'odd"name',
        in_catalog=False,
        repo=tmp_path / 'odd"name',
    )
    text = update.overlay_toml(hit, tmp_path)
    assert 'name = "odd\\"name"' in text
    assert 'name = "odd"name"' not in text


def test_load_catalog_write_dir_is_catalog_parent(tmp_path: Path) -> None:
    catalog_path = tmp_path / "catalog.toml"
    catalog_path.write_text(
        """
plugin_hosts = []
[hosts.grok]
skills = "~/.grok/skills"
""",
        encoding="utf-8",
    )
    loaded = update.load_catalog(catalog_path)
    assert loaded.source_dir == catalog_path.parent
    assert loaded.source_dir != update.ROOT


def test_scan_skips_reparse_outside_roots(tmp_path: Path) -> None:
    code_root = tmp_path / "code"
    outside = tmp_path / "outside" / "ext-skill"
    write_skill(outside, "away")
    code_root.mkdir()
    update.create_junction(outside, code_root / "ext-skill")
    catalog = _scan_catalog(tmp_path, code_root=code_root, hosts={})
    hits = update.scan_skill_hits(catalog, {})
    assert not any(h.name == "ext-skill" for h in hits)


def test_write_overlay_oserror_does_not_raise(tmp_path: Path, monkeypatch, capsys) -> None:
    repo = tmp_path / "new-skill"
    hits = (
        update.ScanHit(
            name="new-skill",
            kind="link",
            path=repo,
            in_catalog=False,
            repo=repo,
        ),
    )
    local_path = tmp_path / "catalog.local.toml"

    def boom(*a, **kw):
        raise OSError("permission denied")

    monkeypatch.setattr(Path, "write_text", boom)
    blocks = update.write_overlay(hits, local_path, tmp_path, dry_run=False)
    assert blocks == []
    err = capsys.readouterr().err
    assert "permission denied" in err or "skip write" in err.lower() or "could not write" in err.lower()


def test_scan_missing_code_root(tmp_path: Path) -> None:
    catalog = update.Catalog(
        code_root=tmp_path / "no-such-code",
        plugin_hosts=(),
        hosts={},
        skills=(),
        source_dir=tmp_path,
    )
    hits = update.scan_skill_hits(catalog, {})
    assert hits == ()


def test_write_overlay_skips_names_already_in_file(tmp_path: Path) -> None:
    local_path = tmp_path / "catalog.local.toml"
    local_path.write_text(
        '[[skills]]\nname = "fresh-skill"\nkind = "link"\nrepo = "{code_root}/fresh-skill"\n',
        encoding="utf-8",
    )
    repo = tmp_path / "fresh-skill"
    hits = (
        update.ScanHit(
            name="fresh-skill",
            kind="link",
            path=repo,
            in_catalog=False,
            repo=repo,
        ),
    )
    blocks = update.write_overlay(hits, local_path, tmp_path, dry_run=False)
    assert blocks == []
    assert local_path.read_text(encoding="utf-8").count('name = "fresh-skill"') == 1


def test_write_overlay_skips_invalid_toml(tmp_path: Path, capsys) -> None:
    local_path = tmp_path / "catalog.local.toml"
    original = 'this is not toml\nname = "fresh-skill"\n'
    local_path.write_text(original, encoding="utf-8")
    repo = tmp_path / "fresh-skill"
    hits = (
        update.ScanHit(
            name="fresh-skill",
            kind="link",
            path=repo,
            in_catalog=False,
            repo=repo,
        ),
    )
    blocks = update.write_overlay(hits, local_path, tmp_path, dry_run=False)
    assert blocks == []
    assert local_path.read_text(encoding="utf-8") == original
    err = capsys.readouterr().err.lower()
    assert "skip write" in err or "invalid" in err


def test_cmd_scan_oserror_does_not_print_wrote(
    tmp_path: Path, monkeypatch, capsys
) -> None:
    code_root = tmp_path / "code"
    write_skill(code_root / "fresh-skill", "x")
    catalog = _scan_catalog(tmp_path, code_root=code_root)
    local_path = tmp_path / "catalog.local.toml"
    local_path.write_text("# keep\n", encoding="utf-8")
    real = Path.write_text

    def boom(self, *a, **kw):
        if self == local_path:
            raise OSError("denied")
        return real(self, *a, **kw)

    monkeypatch.setattr(Path, "write_text", boom)
    code = update.cmd_scan(catalog, catalog.hosts, write=True, dry_run=False)
    assert code == 0
    captured = capsys.readouterr()
    assert "wrote" not in captured.out
    assert "denied" in captured.err or "skip write" in captured.err.lower()
    assert local_path.read_text(encoding="utf-8") == "# keep\n"
