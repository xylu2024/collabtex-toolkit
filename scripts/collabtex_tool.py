#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Collabtex Toolkit: Smart Diff & 3-Way Merge Tool
Provides non-destructive visual diffing and Git-powered 3-way text merging
for Overleaf / Overleaf Community Edition (Collabtex) and local LaTeX projects.

Authors: Dipl.-Ing. Xueyong Lu & Ji Yu (汲羽)
License: MIT
"""

import os
import sys
import io
import re
import shutil
import zipfile
import subprocess
import difflib
from pathlib import Path

# Ensure utf-8 output across Windows PowerShell and Unix terminals
if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except Exception:
        pass

PROJECT_DIR = Path(__file__).resolve().parent.parent
SCRIPTS_DIR = Path(__file__).resolve().parent
CACHE_DIR = PROJECT_DIR / ".collabtex_cache"
REMOTE_CACHE = CACHE_DIR / "remote"
BASE_CACHE = CACHE_DIR / "base"
BACKUP_DIR = CACHE_DIR / "backup"


def get_auth_file():
    local_auth = PROJECT_DIR / ".olauth"
    if local_auth.is_file():
        return str(local_auth)
    user_auth = Path.home() / ".olauth"
    if user_auth.is_file():
        return str(user_auth)
    raise FileNotFoundError(
        "Authentication file (.olauth) not found!\n"
        "Please create .olauth in project root or user home directory using .olauth.template."
    )


def get_server_url():
    import json
    try:
        auth_file = get_auth_file()
        with open(auth_file, "r", encoding="utf-8") as f:
            data = json.load(f)
            return data.get("server", "https://collabtex.helmholtz.cloud")
    except Exception:
        return "https://collabtex.helmholtz.cloud"


def get_project_name():
    # 1. Check .olproject file
    olproject = PROJECT_DIR / ".olproject"
    if olproject.is_file():
        for line in olproject.read_text(encoding="utf-8", errors="ignore").splitlines():
            line = line.strip()
            if line and not line.startswith("#"):
                return line

    # 2. Check push-collabtex.ps1
    push_script = SCRIPTS_DIR / "push-collabtex.ps1"
    if push_script.is_file():
        try:
            content = push_script.read_text(encoding="utf-8", errors="ignore")
            match = re.search(r'-n\s+["\']([^"\']+)["\']', content)
            if match:
                val = match.group(1).strip()
                if val and not val.startswith("YOUR_"):
                    return val
        except Exception:
            pass

    raise ValueError(
        "Project name not configured!\n"
        "Please specify your Overleaf project name in '.olproject' or in 'scripts/push-collabtex.ps1' (-n 'PROJECT_NAME')."
    )


def fetch_remote_files(project_name=None):
    if project_name is None:
        project_name = get_project_name()

    server = get_server_url()
    print(f"[>>] Fetching latest remote snapshot from {server} for project: '{project_name}'...")
    from olsync.olsync import load_client

    auth_path = get_auth_file()
    client = load_client(auth_path, server=server)

    target_project = None
    all_projs = client.all_projects()
    for p in all_projs:
        if p["name"] == project_name:
            target_project = p
            break

    if not target_project:
        # Fallback to substring matching
        for p in all_projs:
            if project_name in p["name"]:
                target_project = p
                break

    if not target_project:
        available = [p["name"] for p in all_projs]
        raise ValueError(
            f"Project '{project_name}' not found on server!\n"
            f"Available projects on {server}:\n  - " + "\n  - ".join(available)
        )

    zip_bytes = client.download_project(target_project["id"])
    zf = zipfile.ZipFile(io.BytesIO(zip_bytes))

    # Safe clean remote cache directory
    REMOTE_CACHE.mkdir(parents=True, exist_ok=True)
    for p in REMOTE_CACHE.glob("**/*"):
        if p.is_file():
            try:
                p.unlink()
            except Exception:
                pass

    extracted_files = []
    for item in zf.infolist():
        # Only cache source texts, bibs, classes, and tables
        if item.filename.endswith((".tex", ".bib", ".sty", ".cls")):
            zf.extract(item, REMOTE_CACHE)
            extracted_files.append(item.filename)

    print(f"[OK] Successfully cached remote source snapshot ({len(extracted_files)} files).")
    return extracted_files


def find_tracked_text_files():
    """Find text files that are tracked in project root and tables/."""
    tracked = []
    for f in PROJECT_DIR.glob("*.tex"):
        tracked.append(f.name)
    for f in PROJECT_DIR.glob("*.bib"):
        tracked.append(f.name)
    tables_dir = PROJECT_DIR / "tables"
    if tables_dir.is_dir():
        for f in tables_dir.glob("*.tex"):
            tracked.append(f"tables/{f.name}")
    return tracked


def update_base():
    """Updates the common base snapshot after a successful push or pull."""
    BASE_CACHE.mkdir(parents=True, exist_ok=True)
    tracked = find_tracked_text_files()
    count = 0
    for rel_path in tracked:
        src = PROJECT_DIR / rel_path
        dst = BASE_CACHE / rel_path
        if src.is_file():
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, dst)
            count += 1
    print(f"[*] Base synchronization snapshot updated ({count} files recorded).")


def do_diff():
    tracked = fetch_remote_files()
    local_files = find_tracked_text_files()
    all_targets = sorted(list(set(tracked) | set(local_files)))

    differences = []
    print("\n" + "=" * 60)
    print("   Collabtex Source Differences Check (Local vs Remote)")
    print("=" * 60)

    for rel_path in all_targets:
        local_f = PROJECT_DIR / rel_path
        remote_f = REMOTE_CACHE / rel_path

        if local_f.is_file() and not remote_f.is_file():
            print(f"  [+] Local only:  {rel_path}")
            differences.append((rel_path, "local_only"))
        elif not local_f.is_file() and remote_f.is_file():
            print(f"  [-] Remote only: {rel_path} (Added on Overleaf)")
            differences.append((rel_path, "remote_only"))
        elif local_f.is_file() and remote_f.is_file():
            loc_bytes = local_f.read_bytes()
            rem_bytes = remote_f.read_bytes()
            if loc_bytes == rem_bytes:
                print(f"  [=] Identical:   {rel_path}")
            else:
                print(f"  [*] Modified:    {rel_path}  <-- Diverged!")
                differences.append((rel_path, "differ"))

    print("=" * 60)
    diff_files = [p for p, status in differences if status == "differ"]

    if not diff_files:
        print("[OK] Local and remote source files are completely in sync! No divergence.\n")
        return

    print(f"\n[!] Detected differences in {len(diff_files)} file(s).")
    for df in diff_files:
        loc_f = PROJECT_DIR / df
        rem_f = REMOTE_CACHE / df
        print(f"\nLaunching VS Code visual side-by-side diff for: {df} ...")
        try:
            subprocess.run(["code", "--diff", str(loc_f), str(rem_f)], shell=True)
            print(f"  -> Diff opened in VS Code: Left = Local, Right = Remote.")
        except Exception as e:
            print(f"  -> Unable to launch VS Code: {e}")


def do_merge():
    fetch_remote_files()
    local_files = find_tracked_text_files()
    differing_files = []

    for rel_path in local_files:
        loc_f = PROJECT_DIR / rel_path
        rem_f = REMOTE_CACHE / rel_path
        if loc_f.is_file() and rem_f.is_file():
            if loc_f.read_bytes() != rem_f.read_bytes():
                differing_files.append(rel_path)

    if not differing_files:
        print("\n[OK] Local and remote are completely identical. No merge required!")
        return

    print("\n" + "=" * 60)
    print("   Collabtex Smart 3-Way Merge")
    print("=" * 60)
    print("Files with differences ready for merging:")
    for df in differing_files:
        print(f"  - {df}")

    git_available = shutil.which("git") is not None
    if not git_available:
        print("[!] Git CLI not detected. Falling back to VS Code side-by-side manual review.")
        for df in differing_files:
            subprocess.run(["code", "--diff", str(PROJECT_DIR / df), str(REMOTE_CACHE / df)], shell=True)
        return

    # Create safety backup
    BACKUP_DIR.mkdir(parents=True, exist_ok=True)
    import time
    stamp = time.strftime("%Y%m%d_%H%M%S")
    cur_backup = BACKUP_DIR / stamp
    cur_backup.mkdir(parents=True, exist_ok=True)
    for df in differing_files:
        loc_f = PROJECT_DIR / df
        shutil.copy2(loc_f, cur_backup / Path(df).name)
    print(f"[*] Safety backup created at: .collabtex_cache/backup/{stamp}/")

    merged_clean = []
    merged_conflicts = []

    for df in differing_files:
        loc_f = PROJECT_DIR / df
        rem_f = REMOTE_CACHE / df
        base_f = BASE_CACHE / df

        if not base_f.is_file():
            print(f"\n[*] File '{df}' has no historical base snapshot.")
            print(f"    Opening VS Code side-by-side diff for manual inspection...")
            subprocess.run(["code", "--diff", str(loc_f), str(rem_f)], shell=True)
            continue

        print(f"\n[>>] Merging: {df} ...")
        cmd = [
            "git",
            "merge-file",
            "-L",
            "Local (My Edits)",
            "-L",
            "Base (Last Sync)",
            "-L",
            "Remote (Overleaf)",
            str(loc_f),
            str(base_f),
            str(rem_f),
        ]
        ret = subprocess.run(cmd, capture_output=True, text=True)

        if ret.returncode == 0:
            print(f"  [SUCCESS] Auto-merged successfully with zero conflicts!")
            merged_clean.append(df)
        elif ret.returncode > 0:
            print(f"  [CONFLICT] {ret.returncode} conflict(s) detected! Conflict markers inserted.")
            merged_conflicts.append(df)
            try:
                subprocess.run(["code", str(loc_f)], shell=True)
                print(f"  -> Opened {df} in VS Code. Please click 'Resolve in Merge Editor'.")
            except Exception:
                pass
        else:
            print(f"  [ERROR] Merge error: {ret.stderr}")

    print("\n" + "=" * 60)
    print("   Merge Summary")
    print("=" * 60)
    if merged_clean:
        print(f"[OK] Seamlessly merged ({len(merged_clean)}): {', '.join(merged_clean)}")
    if merged_conflicts:
        print(f"[!] Requires resolution ({len(merged_conflicts)}): {', '.join(merged_conflicts)}")
        print("    After resolving conflicts, run 'collabtex-push' to push the merged state.")
    elif merged_clean:
        print("[*] All divergent files merged cleanly! Compile locally to verify, then run 'collabtex-push'.")
        update_base()


def main():
    if len(sys.argv) < 2:
        print("Usage: collabtex_tool.py [diff | merge | update-base]")
        sys.exit(1)

    cmd = sys.argv[1].lower()
    if cmd == "diff":
        do_diff()
    elif cmd == "merge":
        do_merge()
    elif cmd in ("update-base", "update_base"):
        update_base()
    else:
        print(f"Unknown command: {cmd}")
        sys.exit(1)


if __name__ == "__main__":
    main()
