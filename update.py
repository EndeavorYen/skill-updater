#!/usr/bin/env python3
"""Refresh local skills and host plugins from catalog.toml. No LLM."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import stat
import subprocess
import sys
try:
    import tomllib
except ModuleNotFoundError:  # Python < 3.11
    try:
        import tomli as tomllib
    except ModuleNotFoundError as exc:
        raise SystemExit("Need Python 3.11+ or the tomli package to read catalog.toml") from exc
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Literal

Kind = Literal["installer", "link", "link-pack", "command"]
KIND_ALIASES = {
    "junction": "link",
    "junction-pack": "link-pack",
    "symlink": "link",
    "symlink-pack": "link-pack",
}
LINK_KINDS = {"link", "link-pack"}
State = Literal[
    "ok",
    "stale",
    "missing",
    "wrong-target",
    "real-dir",
    "missing-repo",
    "missing-src",
]

ROOT = Path(__file__).resolve().parent
CATALOG_NAME = "catalog.toml"
LOCAL_CATALOG_NAME = "catalog.local.toml"


@dataclass(frozen=True)
class Host:
    name: str
    skills: Path


@dataclass(frozen=True)
class SkillEntry:
    name: str
    kind: Kind
    repo: Path
    hosts: tuple[str, ...]
    install_ps1: str | None = None
    install_sh: str | None = None
    dest_skills: tuple[str, ...] = ()
    skills_dir: str = "skills"
    argv: tuple[str, ...] = ()
    source_skill_md: str | None = None


@dataclass(frozen=True)
class Catalog:
    code_root: Path
    plugin_hosts: tuple[str, ...]
    hosts: dict[str, Host]
    skills: tuple[SkillEntry, ...]


@dataclass(frozen=True)
class DestClaim:
    host: str
    dest_name: str
    source_md: Path
    method: Kind
    source_dir: Path
    owner: str


@dataclass(frozen=True)
class Row:
    host: str
    dest: str
    owner: str
    method: str
    state: State
    detail: str = ""


def home() -> Path:
    return Path.home()


def expand_user_text(raw: str) -> str:
    text = raw.replace("{home}", str(home()))
    if text.startswith("~/"):
        return str(home() / text[2:])
    return text


def resolve_code_root(data: dict[str, Any] | None = None) -> Path:
    env = os.environ.get("UPDATE_HARNESS_CODE_ROOT")
    if env:
        return Path(expand_user_text(env))
    raw = (data or {}).get("code_root")
    if raw:
        return Path(expand_user_text(str(raw)))
    return ROOT.parent


def expand_path(raw: str, *, code_root: Path, tool_root: Path | None = None) -> Path:
    tool = tool_root or ROOT
    text = raw.replace("{code_root}", str(code_root))
    text = text.replace("{root}", str(tool))
    text = expand_user_text(text)
    grok_home = os.environ.get("GROK_HOME")
    if grok_home:
        text = text.replace("{GROK_HOME}", grok_home)
    hermes_home = os.environ.get("HERMES_HOME")
    if hermes_home:
        text = text.replace("{HERMES_HOME}", hermes_home)
    return Path(text)


def host_skills_path(name: str, spec: dict[str, Any], *, code_root: Path) -> Path:
    if name == "grok" and os.environ.get("GROK_HOME"):
        return Path(os.environ["GROK_HOME"]) / "skills"
    if name == "hermes" and os.environ.get("HERMES_HOME"):
        return Path(os.environ["HERMES_HOME"]) / "skills"
    return expand_path(spec["skills"], code_root=code_root)


def normalize_kind(raw: str) -> Kind:
    kind = KIND_ALIASES.get(raw, raw)
    if kind not in ("installer", "link", "link-pack", "command"):
        raise ValueError(f"unknown skill kind {raw!r}")
    return kind  # type: ignore[return-value]


def merge_catalog_data(base: dict[str, Any], overlay: dict[str, Any]) -> dict[str, Any]:
    out = dict(base)
    if "code_root" in overlay:
        out["code_root"] = overlay["code_root"]
    if "plugin_hosts" in overlay:
        out["plugin_hosts"] = overlay["plugin_hosts"]
    hosts = dict(base.get("hosts") or {})
    hosts.update(overlay.get("hosts") or {})
    out["hosts"] = hosts
    skills = list(base.get("skills") or [])
    skills.extend(overlay.get("skills") or [])
    out["skills"] = skills
    return out


def load_catalog(
    path: Path | None = None,
    *,
    python: str | None = None,
    root: Path | None = None,
) -> Catalog:
    base = root or ROOT
    catalog_path = path or (base / CATALOG_NAME)
    data = tomllib.loads(catalog_path.read_text(encoding="utf-8"))
    local_path = base / LOCAL_CATALOG_NAME
    if path is None and local_path.is_file():
        data = merge_catalog_data(data, tomllib.loads(local_path.read_text(encoding="utf-8")))
    code_root = resolve_code_root(data)
    py = python or sys.executable
    hosts = {}
    for name, spec in (data.get("hosts") or {}).items():
        hosts[name] = Host(name=name, skills=host_skills_path(name, spec, code_root=code_root))
    skills: list[SkillEntry] = []
    for raw in data.get("skills") or []:
        kind = normalize_kind(raw["kind"])
        repo = expand_path(raw["repo"], code_root=code_root, tool_root=base)
        argv = tuple(
            a.replace("{python}", py)
            .replace("{code_root}", str(code_root))
            .replace("{root}", str(base))
            for a in (raw.get("argv") or [])
        )
        skills.append(
            SkillEntry(
                name=raw["name"],
                kind=kind,
                repo=repo,
                hosts=tuple(raw.get("hosts") or list(hosts)),
                install_ps1=raw.get("install_ps1"),
                install_sh=raw.get("install_sh"),
                dest_skills=tuple(raw.get("dest_skills") or ()),
                skills_dir=raw.get("skills_dir") or "skills",
                argv=argv,
                source_skill_md=raw.get("source_skill_md"),
            )
        )
    return Catalog(
        code_root=code_root,
        plugin_hosts=tuple(data.get("plugin_hosts") or ()),
        hosts=hosts,
        skills=tuple(skills),
    )


def live_hosts(catalog: Catalog) -> dict[str, Host]:
    out = {}
    for name, host in catalog.hosts.items():
        if host.skills.parent.is_dir():
            out[name] = host
    return out


def pack_skill_dirs(entry: SkillEntry) -> list[Path]:
    root = entry.repo / entry.skills_dir
    if not root.is_dir():
        return []
    found: list[Path] = []
    for child in sorted(root.iterdir()):
        if child.is_dir() and (child / "SKILL.md").is_file():
            found.append(child)
    return found


def source_skill_md(entry: SkillEntry, dest_name: str) -> Path:
    if entry.source_skill_md:
        return entry.repo / entry.source_skill_md
    nested = entry.repo / dest_name / "SKILL.md"
    if nested.is_file():
        return nested
    pack = entry.repo / entry.skills_dir / dest_name / "SKILL.md"
    if pack.is_file():
        return pack
    return entry.repo / "SKILL.md"


def source_dir_for(entry: SkillEntry, dest_name: str) -> Path:
    if entry.kind == "link":
        return entry.repo
    if entry.kind == "link-pack":
        return entry.repo / entry.skills_dir / dest_name
    md = source_skill_md(entry, dest_name)
    return md.parent


def dest_names(entry: SkillEntry) -> list[str]:
    if entry.kind == "link":
        return [entry.name]
    if entry.kind == "link-pack":
        return [p.name for p in pack_skill_dirs(entry)]
    if entry.dest_skills:
        return list(entry.dest_skills)
    return [entry.name]


def claims_for(catalog: Catalog, hosts: dict[str, Host]) -> list[DestClaim]:
    by_key: dict[tuple[str, str], DestClaim] = {}
    for entry in catalog.skills:
        for dest_name in dest_names(entry):
            src_md = source_skill_md(entry, dest_name)
            src_dir = source_dir_for(entry, dest_name)
            for host_name in entry.hosts:
                if host_name not in hosts:
                    continue
                by_key[(host_name, dest_name)] = DestClaim(
                    host=host_name,
                    dest_name=dest_name,
                    source_md=src_md,
                    method=entry.kind,
                    source_dir=src_dir,
                    owner=entry.name,
                )
    return list(by_key.values())


def sha256_file(path: Path) -> str | None:
    if not path.is_file():
        return None
    h = hashlib.sha256()
    h.update(path.read_bytes())
    return h.hexdigest()


def is_reparse_point(path: Path) -> bool:
    try:
        st = path.lstat()
    except OSError:
        return False
    attrs = getattr(st, "st_file_attributes", None)
    if attrs is not None:
        return bool(attrs & 0x400)
    return path.is_symlink()


def link_target(path: Path) -> Path | None:
    if not is_reparse_point(path):
        return None
    try:
        raw = os.readlink(path)
    except OSError:
        try:
            raw = os.fspath(path.readlink())
        except OSError:
            return None
    target = Path(raw)
    if not target.is_absolute():
        target = path.parent / target
    return target


junction_target = link_target


def display_path(path: Path | str) -> str:
    text = str(path)
    if text.startswith("\\\\?\\"):
        text = text[4:]
    elif text.startswith("//?/"):
        text = text[4:]
    return text


def _canon(path: Path) -> str:
    return os.path.normcase(os.path.abspath(display_path(path)))


def same_path(a: Path | None, b: Path | None) -> bool:
    if a is None or b is None:
        return False
    try:
        return _canon(a) == _canon(b)
    except OSError:
        return os.path.normcase(str(a)) == os.path.normcase(str(b))


def classify(claim: DestClaim, hosts: dict[str, Host]) -> Row:
    host = hosts[claim.host]
    dest = host.skills / claim.dest_name
    method = claim.method
    if method in LINK_KINDS:
        if not claim.source_dir.is_dir() or not (claim.source_dir / "SKILL.md").is_file():
            return Row(claim.host, claim.dest_name, claim.owner, method, "missing-src", str(claim.source_dir))
        if not dest.exists() and not is_reparse_point(dest):
            return Row(claim.host, claim.dest_name, claim.owner, method, "missing")
        if is_reparse_point(dest):
            target = junction_target(dest)
            if target is not None and same_path(target, claim.source_dir):
                return Row(claim.host, claim.dest_name, claim.owner, method, "ok", display_path(target))
            return Row(
                claim.host,
                claim.dest_name,
                claim.owner,
                method,
                "wrong-target",
                display_path(target) if target else "?",
            )
        return Row(claim.host, claim.dest_name, claim.owner, method, "real-dir", str(dest))
    if not claim.source_md.is_file():
        state: State = "missing-repo" if not claim.source_md.parent.exists() else "missing-src"
        return Row(claim.host, claim.dest_name, claim.owner, method, state, str(claim.source_md))
    dest_md = dest / "SKILL.md"
    if not dest_md.is_file():
        return Row(claim.host, claim.dest_name, claim.owner, method, "missing")
    src_hash = sha256_file(claim.source_md)
    dst_hash = sha256_file(dest_md)
    if src_hash and dst_hash and src_hash == dst_hash:
        return Row(claim.host, claim.dest_name, claim.owner, method, "ok")
    return Row(claim.host, claim.dest_name, claim.owner, method, "stale", "SKILL.md differs")


def status_rows(catalog: Catalog, hosts: dict[str, Host]) -> list[Row]:
    rows = [classify(claim, hosts) for claim in claims_for(catalog, hosts)]
    rows.sort(key=lambda r: (r.host, r.owner, r.dest))
    return rows


def print_table(rows: list[Row]) -> None:
    if not rows:
        print("no skill rows")
        return
    widths = {
        "host": max(4, max(len(r.host) for r in rows)),
        "dest": max(4, max(len(r.dest) for r in rows)),
        "owner": max(5, max(len(r.owner) for r in rows)),
        "method": max(6, max(len(r.method) for r in rows)),
        "state": max(5, max(len(r.state) for r in rows)),
    }
    header = (
        f"{'host':<{widths['host']}}  {'dest':<{widths['dest']}}  "
        f"{'owner':<{widths['owner']}}  {'method':<{widths['method']}}  "
        f"{'state':<{widths['state']}}  detail"
    )
    print(header)
    print("-" * len(header))
    for r in rows:
        print(
            f"{r.host:<{widths['host']}}  {r.dest:<{widths['dest']}}  "
            f"{r.owner:<{widths['owner']}}  {r.method:<{widths['method']}}  "
            f"{r.state:<{widths['state']}}  {r.detail}"
        )


def counts(rows: Iterable[Row]) -> dict[str, int]:
    out: dict[str, int] = {}
    for r in rows:
        out[r.state] = out.get(r.state, 0) + 1
    return out


def which(cmd: str) -> str | None:
    return shutil.which(cmd)


def run_cmd(argv: list[str], *, cwd: Path | None = None, dry_run: bool) -> int:
    printable = " ".join(argv)
    if cwd is not None:
        printable = f"(cd {cwd}) {printable}"
    if dry_run:
        print(f"dry-run: {printable}")
        return 0
    print(f"$ {printable}")
    completed = subprocess.run(argv, cwd=str(cwd) if cwd else None)
    return completed.returncode


def create_link(src: Path, dest: Path) -> None:
    dest.parent.mkdir(parents=True, exist_ok=True)
    if os.name == "nt":
        import _winapi

        _winapi.CreateJunction(str(src), str(dest))
        return
    dest.symlink_to(src, target_is_directory=True)


create_junction = create_link


def remove_link(path: Path) -> None:
    # rmtree on a junction/symlink can delete the source tree. Never do that.
    if not (path.is_symlink() or is_reparse_point(path)):
        raise RuntimeError(f"refusing to delete non-link path {path}")
    try:
        path.unlink()
    except OSError:
        os.rmdir(path)


remove_reparse_point = remove_link


def ensure_link(src: Path, dest: Path, *, force: bool, dry_run: bool) -> str:
    src = src.resolve()
    if dest.exists() or is_reparse_point(dest):
        if is_reparse_point(dest):
            target = link_target(dest)
            if target is not None and same_path(target, src):
                return "ok"
            if dry_run:
                return "would-retarget"
            remove_link(dest)
        else:
            if not force:
                return "real-dir"
            if dry_run:
                return "would-replace-dir"
            bak = dest.with_name(dest.name + ".bak")
            n = 1
            while bak.exists():
                bak = dest.with_name(f"{dest.name}.bak{n}")
                n += 1
            dest.rename(bak)
            print(f"moved real dir {dest} -> {bak}")
    if dry_run:
        return "would-link"
    create_link(src, dest)
    return "linked"


ensure_junction = ensure_link


def installer_paths(entry: SkillEntry) -> tuple[Path | None, Path | None]:
    ps1_rel = entry.install_ps1 or "scripts/install.ps1"
    sh_rel = entry.install_sh or "scripts/install.sh"
    ps1 = entry.repo / ps1_rel
    sh = entry.repo / sh_rel
    return (ps1 if ps1.is_file() else None, sh if sh.is_file() else None)


def installer_argv(entry: SkillEntry, host_name: str) -> list[str]:
    ps1, sh = installer_paths(entry)
    if os.name == "nt":
        if ps1 is not None:
            powershell = which("powershell") or which("pwsh")
            if not powershell:
                raise FileNotFoundError("powershell not on PATH")
            return [
                powershell,
                "-NoProfile",
                "-ExecutionPolicy",
                "Bypass",
                "-File",
                str(ps1),
                host_name,
            ]
        if sh is not None:
            bash = which("bash")
            if not bash:
                raise FileNotFoundError("bash not on PATH (Git Bash) and no install.ps1")
            return [bash, str(sh), host_name]
        raise FileNotFoundError(f"{entry.name}: need scripts/install.ps1 or scripts/install.sh")
    if sh is not None:
        bash = which("bash") or which("sh")
        if not bash:
            raise FileNotFoundError("bash/sh not on PATH")
        return [bash, str(sh), host_name]
    if ps1 is not None:
        pwsh = which("pwsh") or which("powershell")
        if not pwsh:
            raise FileNotFoundError("pwsh not on PATH and no install.sh")
        return [pwsh, "-NoProfile", "-File", str(ps1), host_name]
    raise FileNotFoundError(f"{entry.name}: need scripts/install.sh or scripts/install.ps1")


def write_shim() -> None:
    bin_dir = home() / ".local" / "bin"
    bin_dir.mkdir(parents=True, exist_ok=True)
    script = ROOT / "update.py"
    python = sys.executable
    if os.name == "nt":
        shim = bin_dir / "update-harness.cmd"
        body = (
            "@echo off\r\n"
            "where py >nul 2>&1\r\n"
            "if %ERRORLEVEL%==0 (\r\n"
            f'  py -3 "{script}" %*\r\n'
            ") else (\r\n"
            f'  python "{script}" %*\r\n'
            ")\r\n"
        )
    else:
        shim = bin_dir / "update-harness"
        body = f'#!/bin/sh\nexec "{python}" "{script}" "$@"\n'
    if shim.is_file() and shim.read_text(encoding="utf-8") == body:
        return
    shim.write_text(body, encoding="utf-8", newline="\n")
    if os.name != "nt":
        mode = shim.stat().st_mode
        shim.chmod(mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
    print(f"wrote {shim}")


def apply_entry(
    entry: SkillEntry,
    hosts: dict[str, Host],
    *,
    dry_run: bool,
    force: bool,
) -> list[str]:
    actions: list[str] = []
    live = [h for h in entry.hosts if h in hosts]
    if not live:
        return [f"{entry.name}: no live hosts"]
    if not entry.repo.exists():
        return [f"{entry.name}: missing repo {entry.repo}"]
    if entry.kind == "installer":
        for host_name in live:
            try:
                argv = installer_argv(entry, host_name)
            except FileNotFoundError as exc:
                actions.append(f"{entry.name} {host_name}: {exc} FAIL")
                continue
            code = run_cmd(argv, cwd=entry.repo, dry_run=dry_run)
            actions.append(f"{entry.name} {host_name}: exit {code}")
            if code != 0:
                actions[-1] += " FAIL"
        return actions
    if entry.kind == "command":
        if not entry.argv:
            return [f"{entry.name}: argv missing"]
        code = run_cmd(list(entry.argv), cwd=entry.repo, dry_run=dry_run)
        actions.append(f"{entry.name}: exit {code}" + (" FAIL" if code != 0 else ""))
        return actions
    for dest_name in dest_names(entry):
        src = source_dir_for(entry, dest_name)
        for host_name in live:
            dest = hosts[host_name].skills / dest_name
            result = ensure_link(src, dest, force=force, dry_run=dry_run)
            actions.append(f"{entry.name} {host_name}/{dest_name}: {result}")
    if entry.name == "update-harness" and not dry_run:
        write_shim()
    return actions


def apply_skills(
    catalog: Catalog,
    hosts: dict[str, Host],
    *,
    only: str | None,
    dry_run: bool,
    force: bool,
) -> int:
    failed = 0
    for entry in catalog.skills:
        if only and entry.name != only and only not in dest_names(entry):
            continue
        for line in apply_entry(entry, hosts, dry_run=dry_run, force=force):
            print(line)
            if line.endswith("FAIL") or ": missing " in line or line.endswith("real-dir"):
                if line.endswith("real-dir"):
                    print("  (real directory in the way; re-run with --force to rename it aside, then link)")
                failed += 1
    return 1 if failed else 0


def claude_plugin_ids(payload: Any) -> list[str]:
    ids: list[str] = []
    if isinstance(payload, list):
        for item in payload:
            if isinstance(item, dict) and item.get("id"):
                ids.append(str(item["id"]))
    elif isinstance(payload, dict):
        plugins = payload.get("plugins") or payload.get("installed") or []
        if isinstance(plugins, list):
            for item in plugins:
                if isinstance(item, dict) and item.get("id"):
                    ids.append(str(item["id"]))
    return ids


def apply_plugins(catalog: Catalog, *, dry_run: bool) -> int:
    failed = 0
    for host_name in catalog.plugin_hosts:
        if host_name == "grok":
            if not which("grok"):
                print("skip grok: CLI not on PATH")
                continue
            code = run_cmd(["grok", "plugin", "update"], dry_run=dry_run)
            if code != 0:
                failed += 1
            continue
        if host_name == "claude":
            if not which("claude"):
                print("skip claude: CLI not on PATH")
                continue
            code = run_cmd(["claude", "plugin", "marketplace", "update"], dry_run=dry_run)
            if code != 0:
                failed += 1
            if dry_run:
                print("dry-run: claude plugin list --json && claude plugin update <id>")
                continue
            listed = subprocess.run(
                ["claude", "plugin", "list", "--json"],
                capture_output=True,
                text=True,
            )
            if listed.returncode != 0:
                print(listed.stderr or listed.stdout)
                failed += 1
                continue
            try:
                payload = json.loads(listed.stdout)
            except json.JSONDecodeError as exc:
                print(f"claude plugin list: not JSON ({exc})")
                failed += 1
                continue
            ids = claude_plugin_ids(payload)
            if not ids:
                print("claude: no plugins listed")
                continue
            for plugin_id in ids:
                code = run_cmd(["claude", "plugin", "update", plugin_id], dry_run=False)
                if code != 0:
                    failed += 1
            continue
        print(f"unknown plugin host {host_name}")
        failed += 1
    return 1 if failed else 0


def cmd_status(catalog: Catalog, hosts: dict[str, Host], *, as_json: bool) -> int:
    rows = status_rows(catalog, hosts)
    if as_json:
        print(json.dumps([r.__dict__ for r in rows], indent=2))
    else:
        print_table(rows)
        c = counts(rows)
        summary = ", ".join(f"{k}={v}" for k, v in sorted(c.items()))
        print()
        print(f"hosts: {', '.join(hosts) or '(none)'}")
        print(f"skills: {summary or '0'}")
        print(f"plugin hosts: {', '.join(catalog.plugin_hosts) or '(none)'}")
    bad = [r for r in rows if r.state not in ("ok",)]
    return 1 if bad else 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        description="Refresh local skills and host plugins from catalog.toml"
    )
    p.add_argument(
        "command",
        nargs="?",
        default="status",
        choices=["status", "skills", "plugins", "all"],
        help="status (default), skills, plugins, or all",
    )
    p.add_argument("--dry-run", action="store_true")
    p.add_argument("--force", action="store_true", help="rename a real dest dir aside, then link")
    p.add_argument("--only", metavar="NAME", help="one catalog name or dest skill")
    p.add_argument("--json", action="store_true", help="status as JSON")
    p.add_argument("--catalog", type=Path, help="catalog.toml path")
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    catalog = load_catalog(args.catalog)
    hosts = live_hosts(catalog)
    if args.command == "status":
        return cmd_status(catalog, hosts, as_json=args.json)
    rc = 0
    if args.command in ("skills", "all"):
        rc |= apply_skills(
            catalog, hosts, only=args.only, dry_run=args.dry_run, force=args.force
        )
    if args.command in ("plugins", "all"):
        if args.only:
            print("plugins: --only ignored")
        rc |= apply_plugins(catalog, dry_run=args.dry_run)
    if args.command in ("skills", "all", "plugins") and not args.dry_run:
        print()
        cmd_status(catalog, hosts, as_json=False)
    return rc


if __name__ == "__main__":
    raise SystemExit(main())
