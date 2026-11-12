#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Collabtex Toolkit: Content-Verified Diff, 3-Way Merge & Asset Sync Tool
Provides SHA-256 content-hash verification across both LaTeX text sources
and binary assets (figures/*.pdf, figures/*.png), non-destructive visual
diffing, and Git-powered 3-way text merging for Overleaf / Overleaf CE.

Authors: Dipl.-Ing. Xueyong Lu & Ji Yu (汲羽)
License: MIT
"""

import os
import sys
import io
import re
import json
import time
import shutil
import fnmatch
import hashlib
import zipfile
import subprocess
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
BASE_MANIFEST = CACHE_DIR / "base_manifest.json"
REMOTE_MANIFEST = CACHE_DIR / "remote_manifest.json"

TEXT_EXTS = {".tex", ".bib", ".sty", ".cls", ".txt", ".md"}


def is_text_file(rel_path: str) -> bool:
    return Path(rel_path).suffix.lower() in TEXT_EXTS


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def format_size(num_bytes: int) -> str:
    if num_bytes < 1024:
        return f"{num_bytes} B"
    if num_bytes < 1024 * 1024:
        return f"{num_bytes / 1024:.1f} KB"
    return f"{num_bytes / (1024 * 1024):.2f} MB"


def texts_equal_ignoring_eol(b1: bytes, b2: bytes) -> bool:
    return b1 == b2 or b1.replace(b"\r\n", b"\n") == b2.replace(b"\r\n", b"\n")


def get_auth_file() -> str:
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


def get_server_url() -> str:
    try:
        auth_file = get_auth_file()
        with open(auth_file, "r", encoding="utf-8") as f:
            data = json.load(f)
            return data.get("server", "https://collabtex.helmholtz.cloud")
    except Exception:
        return "https://collabtex.helmholtz.cloud"


def get_project_name() -> str:
    # 1. Check .olproject file
    olproject = PROJECT_DIR / ".olproject"
    if olproject.is_file():
        for line in olproject.read_text(encoding="utf-8", errors="ignore").splitlines():
            line = line.strip()
            if line and not line.startswith("#"):
                return line

    # 2. Check push-collabtex.ps1 (-n "NAME" or $projectName = "NAME")
    push_script = SCRIPTS_DIR / "push-collabtex.ps1"
    if push_script.is_file():
        try:
            content = push_script.read_text(encoding="utf-8", errors="ignore")
            m = re.search(r'-n\s+["\']([^"\']+)["\']', content)
            if not m:
                m = re.search(r'\$projectName\s*=\s*["\']([^"\']+)["\']', content)
            if m:
                val = m.group(1).strip()
                if val and not val.startswith("YOUR_"):
                    return val
        except Exception:
            pass

    raise ValueError(
        "Project name not configured!\n"
        "Please specify your Overleaf project name in '.olproject' or in 'scripts/push-collabtex.ps1'."
    )


def load_olignore_patterns() -> list[str]:
    olignore = PROJECT_DIR / ".olignore"
    if not olignore.is_file():
        return []
    patterns = []
    for raw_line in olignore.read_text(encoding="utf-8", errors="ignore").splitlines():
        line = raw_line.strip().removeprefix("./")
        if line and not line.startswith("#"):
            patterns.append(line.replace("\\", "/"))
    return patterns


def matches_olignore(rel_path: str, patterns: list[str]) -> bool:
    rel_posix = rel_path.replace("\\", "/").removeprefix("./")
    parts = rel_posix.split("/")
    # Hidden dotfiles/dotdirs (like .git, .olauth, .collabtex_cache, .history) are always ignored
    if any(p.startswith(".") for p in parts):
        return True
    rel_os = os.path.normpath(rel_posix)
    for pat in patterns:
        pat_os = os.path.normpath(pat)
        if fnmatch.fnmatch(rel_posix, pat) or fnmatch.fnmatch(rel_os, pat_os):
            return True
        # Match directory prefix pattern like "build/*" or "figures/old/**"
        if pat.endswith("/*") or pat.endswith("/**"):
            prefix = pat.split("/*")[0].rstrip("/")
            if rel_posix == prefix or rel_posix.startswith(prefix + "/"):
                return True
    return False


def find_local_tracked_files() -> list[str]:
    """Return all local whitelisted files (text sources + binary figures/PDFs) respecting .olignore."""
    patterns = load_olignore_patterns()
    tracked = []
    for root, dirs, files in os.walk(PROJECT_DIR):
        # Prune hidden directories in-place for speed and cleanliness
        dirs[:] = [d for d in dirs if not d.startswith(".")]
        rel_root = Path(root).relative_to(PROJECT_DIR).as_posix()
        for fname in files:
            if fname.startswith("."):
                continue
            rel_path = fname if rel_root == "." else f"{rel_root}/{fname}"
            if not matches_olignore(rel_path, patterns):
                tracked.append(rel_path)
    return sorted(tracked)


def load_base_manifest() -> dict:
    if not BASE_MANIFEST.is_file():
        return {}
    try:
        return json.loads(BASE_MANIFEST.read_text(encoding="utf-8"))
    except Exception:
        return {}


def save_base_manifest(manifest: dict):
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    BASE_MANIFEST.write_text(json.dumps(manifest, indent=2, sort_keys=True), encoding="utf-8")


def update_base():
    """Update both text base snapshots and SHA-256 base_manifest.json for all tracked files."""
    BASE_CACHE.mkdir(parents=True, exist_ok=True)
    tracked = find_local_tracked_files()
    tracked_set = set(tracked)

    # Clean stale text snapshots in BASE_CACHE
    for existing in BASE_CACHE.glob("**/*"):
        if existing.is_file():
            rel = existing.relative_to(BASE_CACHE).as_posix()
            if rel not in tracked_set:
                try:
                    existing.unlink()
                except Exception:
                    pass

    manifest = {}
    text_count = 0
    asset_count = 0

    for rel_path in tracked:
        src = PROJECT_DIR / rel_path
        if not src.is_file():
            continue
        data = src.read_bytes()
        manifest[rel_path] = {
            "sha256": sha256_bytes(data),
            "size": len(data),
        }
        if is_text_file(rel_path):
            dst = BASE_CACHE / rel_path
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, dst)
            text_count += 1
        else:
            asset_count += 1

    save_base_manifest(manifest)
    print(f"[*] Base snapshot updated: {text_count} text source(s) + {asset_count} binary asset(s) (SHA-256 recorded).")


def refresh_auth_csrf(quiet=False):
    """Verify current cookie and automatically sync .olauth CSRF token when empty or stale."""
    from olsync import auth
    from olsync.olclient import OverleafClient

    auth_path = get_auth_file()
    login = auth.load_auth(auth_path)
    server = get_server_url() or login["server"]
    stored_csrf = login.get("csrf", "") or ""
    probe = OverleafClient(login["cookies"], stored_csrf, base_url=server)
    live_csrf = probe.fetch_csrf()
    if live_csrf is None:
        raise RuntimeError(
            "The session cookie in .olauth has expired or is invalid. Please update sharelatex.sid from your browser."
        )
    if live_csrf != stored_csrf:
        auth.save_auth(auth_path, login["cookies"], live_csrf, login["server"])
        if not quiet:
            print("[OK] Stale or empty CSRF token in .olauth has been automatically refreshed for the active cookie.")
        return OverleafClient(login["cookies"], live_csrf, base_url=server)
    if not quiet:
        print("[*] CSRF token in .olauth matches the active session cookie.")
    return probe


def resolve_project(project_name=None):
    if project_name is None:
        project_name = get_project_name()

    server = get_server_url()
    client = refresh_auth_csrf(quiet=True)

    target_project = None
    all_projs = client.all_projects()
    for p in all_projs:
        if p["name"] == project_name:
            target_project = p
            break
    if not target_project:
        for p in all_projs:
            if project_name in p["name"]:
                target_project = p
                break
    if not target_project:
        available = [p["name"] for p in all_projs]
        raise ValueError(
            f"Project '{project_name}' not found on {server}!\n"
            f"Available projects:\n  - " + "\n  - ".join(available)
        )
    return client, target_project, server


def fetch_remote_snapshot(project_name=None, client=None, target_project=None, server=None, quiet=False):
    if client is None or target_project is None:
        client, target_project, server = resolve_project(project_name)

    if not quiet:
        print(f"[>>] Fetching remote snapshot from {server} for '{target_project['name']}'...")

    zip_bytes = client.download_project(target_project["id"])
    zf = zipfile.ZipFile(io.BytesIO(zip_bytes))

    # Clean REMOTE_CACHE safely
    REMOTE_CACHE.mkdir(parents=True, exist_ok=True)
    for p in REMOTE_CACHE.glob("**/*"):
        if p.is_file():
            try:
                p.unlink()
            except Exception:
                pass

    remote_meta = {}
    for item in zf.infolist():
        if item.is_dir() or item.filename.endswith("/"):
            continue
        rel_path = item.filename.replace("\\", "/").removeprefix("./")
        data = zf.read(item.filename)
        remote_meta[rel_path] = {
            "sha256": sha256_bytes(data),
            "size": len(data),
            "zip_name": item.filename,
        }
        out_path = REMOTE_CACHE / rel_path
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_bytes(data)

    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    REMOTE_MANIFEST.write_text(json.dumps(remote_meta, indent=2, sort_keys=True), encoding="utf-8")

    if not quiet:
        n_txt = sum(1 for k in remote_meta if is_text_file(k))
        n_bin = len(remote_meta) - n_txt
        print(f"[OK] Cached remote snapshot ({n_txt} text source(s), {n_bin} binary asset(s)).")

    return client, target_project, server, zf, remote_meta


def sync_olsync_state(server: str, project_id: str, remote_meta: dict):
    """Align .olsync-state.json hashes with actual remote zip and local files."""
    try:
        from olsync import syncstate

        tracked = find_local_tracked_files()
        new_state = {}
        for rel_path in sorted(set(tracked) | set(remote_meta)):
            loc_f = PROJECT_DIR / rel_path
            if loc_f.is_file() and rel_path in remote_meta:
                new_state[rel_path] = {
                    "local": sha256_file(loc_f),
                    "remote": remote_meta[rel_path]["sha256"],
                }
        syncstate.save_state(str(PROJECT_DIR), server, project_id, new_state)
    except Exception as e:
        print(f"[!] Warning: Could not update .olsync-state.json: {e}")


def do_diff():
    _, _, _, _, remote_meta = fetch_remote_snapshot()
    patterns = load_olignore_patterns()
    local_files = find_local_tracked_files()
    all_targets = sorted(set(local_files) | set(remote_meta.keys()))
    base_manifest = load_base_manifest()

    diff_text_files = []
    diff_binary_files = []
    local_only_files = []
    remote_only_active = []
    remote_only_ignored = []

    print("\n" + "=" * 72)
    print("   Collabtex Content-Hash Diff (Local vs Remote via SHA-256)")
    print("=" * 72)

    for rel_path in all_targets:
        loc_f = PROJECT_DIR / rel_path
        rem_f = REMOTE_CACHE / rel_path
        in_local = loc_f.is_file() and not matches_olignore(rel_path, patterns)
        in_remote = rel_path in remote_meta

        if in_local and not in_remote:
            sz = format_size(loc_f.stat().st_size)
            tag = "Text" if is_text_file(rel_path) else "Asset"
            print(f"  [+] Local only ({tag:5s}): {rel_path}  ({sz})")
            local_only_files.append(rel_path)
        elif not in_local and in_remote:
            if matches_olignore(rel_path, patterns):
                remote_only_ignored.append(rel_path)
            else:
                sz = format_size(remote_meta[rel_path]["size"])
                tag = "Text" if is_text_file(rel_path) else "Asset"
                print(f"  [-] Remote only ({tag:5s}): {rel_path}  ({sz}) [Added on Overleaf or deleted locally]")
                remote_only_active.append(rel_path)
        elif in_local and in_remote:
            loc_bytes = loc_f.read_bytes()
            rem_bytes = rem_f.read_bytes()
            loc_sha = sha256_bytes(loc_bytes)
            rem_sha = remote_meta[rel_path]["sha256"]

            if loc_sha == rem_sha:
                print(f"  [=] Identical:          {rel_path}")
            elif is_text_file(rel_path) and texts_equal_ignoring_eol(loc_bytes, rem_bytes):
                print(f"  [=] Identical (EOL):    {rel_path}  (CRLF/LF only)")
            elif is_text_file(rel_path):
                print(f"  [*] Modified (Text):    {rel_path}  [Local {loc_sha[:8]} != Remote {rem_sha[:8]}]")
                diff_text_files.append(rel_path)
            else:
                loc_sz = format_size(len(loc_bytes))
                rem_sz = format_size(len(rem_bytes))
                base_hint = ""
                if rel_path in base_manifest:
                    b_sha = base_manifest[rel_path]["sha256"]
                    if loc_sha != b_sha and rem_sha == b_sha:
                        base_hint = " | Local updated (ready to push)"
                    elif loc_sha == b_sha and rem_sha != b_sha:
                        base_hint = " | Remote updated (ready to pull)"
                    else:
                        base_hint = " | BOTH sides changed!"
                print(
                    f"  [*] Modified (Asset):   {rel_path}\n"
                    f"      Local:  {loc_sz} (SHA256: {loc_sha[:8]}) | Remote: {rem_sz} (SHA256: {rem_sha[:8]}){base_hint}"
                )
                diff_binary_files.append(rel_path)

    if remote_only_ignored:
        print(f"  [~] Remote-only legacy/ignored files (filtered by .olignore): {len(remote_only_ignored)} file(s)")
        for rp in remote_only_ignored:
            print(f"      - {rp}")

    print("=" * 72)

    if not diff_text_files and not diff_binary_files and not local_only_files and not remote_only_active:
        print("[OK] Local and remote files (all text sources & binary figures) match 100% by SHA-256!\n")
        return

    if diff_binary_files:
        print(f"\n[!] Detected {len(diff_binary_files)} modified binary asset(s) with identical filenames:")
        for bf in diff_binary_files:
            print(f"    - {bf}")
        print("    Tip: Run 'collabtex-push' to overwrite remote with your updated figure(s),")
        print("         or 'collabtex-merge' / 'collabtex-pull' to sync from Overleaf.")

    if diff_text_files:
        print(f"\n[!] Detected {len(diff_text_files)} modified text source(s). Launching VS Code diff...")
        for df in diff_text_files:
            loc_f = PROJECT_DIR / df
            rem_f = REMOTE_CACHE / df
            try:
                subprocess.run(["code", "--diff", str(loc_f), str(rem_f)], shell=True)
                print(f"    -> Opened diff: {df} (Left = Local, Right = Remote)")
            except Exception as e:
                print(f"    -> Unable to launch VS Code for {df}: {e}")


def do_merge():
    _, _, _, _, remote_meta = fetch_remote_snapshot()
    local_files = find_local_tracked_files()
    base_manifest = load_base_manifest()

    diff_text_files = []
    diff_binary_files = []

    for rel_path in local_files:
        if rel_path not in remote_meta:
            continue
        loc_f = PROJECT_DIR / rel_path
        rem_f = REMOTE_CACHE / rel_path
        loc_bytes = loc_f.read_bytes()
        rem_bytes = rem_f.read_bytes()
        if is_text_file(rel_path):
            if not texts_equal_ignoring_eol(loc_bytes, rem_bytes):
                diff_text_files.append(rel_path)
        else:
            if sha256_bytes(loc_bytes) != remote_meta[rel_path]["sha256"]:
                diff_binary_files.append(rel_path)

    if not diff_text_files and not diff_binary_files:
        print("\n[OK] Local and remote are completely identical (SHA-256 verified). No merge required!")
        return

    print("\n" + "=" * 72)
    print("   Collabtex Smart 3-Way Merge (Text & SHA-256 Binary Tracking)")
    print("=" * 72)

    stamp = time.strftime("%Y%m%d_%H%M%S")
    cur_backup = BACKUP_DIR / stamp
    cur_backup.mkdir(parents=True, exist_ok=True)
    for rel_path in diff_text_files + diff_binary_files:
        src = PROJECT_DIR / rel_path
        dst = cur_backup / rel_path
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dst)
    print(f"[*] Safety backup created at: .collabtex_cache/backup/{stamp}/")

    merged_clean = []
    merged_conflicts = []

    # 1. Text 3-way merge
    if diff_text_files:
        git_available = shutil.which("git") is not None
        if not git_available:
            print("[!] Git CLI not detected. Opening VS Code side-by-side manual diff for text files.")
            for df in diff_text_files:
                subprocess.run(["code", "--diff", str(PROJECT_DIR / df), str(REMOTE_CACHE / df)], shell=True)
        else:
            for df in diff_text_files:
                loc_f = PROJECT_DIR / df
                rem_f = REMOTE_CACHE / df
                base_f = BASE_CACHE / df

                if not base_f.is_file():
                    print(f"\n[*] Text file '{df}' has no historical base snapshot. Opening side-by-side diff...")
                    subprocess.run(["code", "--diff", str(loc_f), str(rem_f)], shell=True)
                    merged_conflicts.append(df)
                    continue

                print(f"\n[>>] 3-way merging text: {df} ...")
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
                    print(f"  [SUCCESS] Auto-merged cleanly with zero conflicts!")
                    merged_clean.append(df)
                elif ret.returncode > 0:
                    print(f"  [CONFLICT] {ret.returncode} conflict(s) detected! Markers inserted.")
                    merged_conflicts.append(df)
                    try:
                        subprocess.run(["code", str(loc_f)], shell=True)
                    except Exception:
                        pass
                else:
                    print(f"  [ERROR] Merge error: {ret.stderr}")
                    merged_conflicts.append(df)

    # 2. Binary Asset 3-Way SHA-256 Evaluation (e.g. figures/*.png, figures/*.pdf)
    binary_local_kept = []
    binary_remote_pulled = []
    binary_conflicts = []

    if diff_binary_files:
        print("\n--- Binary Figure / Asset Check (SHA-256 3-Way Analysis) ---")
        for bf in diff_binary_files:
            loc_f = PROJECT_DIR / bf
            rem_f = REMOTE_CACHE / bf
            loc_sha = sha256_file(loc_f)
            rem_sha = remote_meta[bf]["sha256"]
            base_sha = base_manifest.get(bf, {}).get("sha256")

            loc_sz = format_size(loc_f.stat().st_size)
            rem_sz = format_size(remote_meta[bf]["size"])

            if base_sha and loc_sha != base_sha and rem_sha == base_sha:
                print(f"  [LOCAL NEWER]  {bf} ({loc_sz}, {loc_sha[:8]}) -> Keeping local figure (push when ready).")
                binary_local_kept.append(bf)
            elif base_sha and loc_sha == base_sha and rem_sha != base_sha:
                print(f"  [REMOTE NEWER] {bf}: Overleaf has updated version ({rem_sz}, {rem_sha[:8]}).")
                ans = input(f"    Update local '{bf}' from Overleaf? [Y/n]: ").strip().lower()
                if ans in ("", "y", "yes"):
                    shutil.copy2(rem_f, loc_f)
                    print(f"    [OK] Updated local '{bf}' (previous local copy backed up).")
                    binary_remote_pulled.append(bf)
                else:
                    print("    [SKIP] Kept local version.")
                    binary_local_kept.append(bf)
            else:
                rem_bak = cur_backup / f"remote_conflict_{Path(bf).name}"
                shutil.copy2(rem_f, rem_bak)
                print(
                    f"  [CONFLICT]     {bf}: Changed on BOTH sides or missing Base history!\n"
                    f"                 Local:  {loc_sz} ({loc_sha[:8]})\n"
                    f"                 Remote: {rem_sz} ({rem_sha[:8]}) -> Saved copy to {rem_bak.name}"
                )
                binary_conflicts.append(bf)

    print("\n" + "=" * 72)
    print("   Merge Summary")
    print("=" * 72)
    if merged_clean:
        print(f"[OK] Auto-merged text ({len(merged_clean)}): {', '.join(merged_clean)}")
    if binary_remote_pulled:
        print(f"[OK] Pulled remote-updated assets ({len(binary_remote_pulled)}): {', '.join(binary_remote_pulled)}")
    if binary_local_kept:
        print(f"[*] Preserved local-updated assets ({len(binary_local_kept)}): {', '.join(binary_local_kept)}")
    if merged_conflicts or binary_conflicts:
        print(f"[!] Conflicts requiring attention ({len(merged_conflicts) + len(binary_conflicts)}): {', '.join(merged_conflicts + binary_conflicts)}")
        print("    Resolve manually, verify local build, and then run 'collabtex-push'.")
    else:
        print("[*] Merge completed cleanly! Run 'collabtex-push' when ready to publish.")
        # Do not overwrite base for un-pushed local_kept assets, unless no local_kept assets remain
        if not binary_local_kept:
            update_base()


def do_verify_push(force=False):
    """
    Post-push SHA-256 verification & self-healing upload engine.
    Guarantees updated same-name binary figures/PDFs are NEVER skipped or left stale on Overleaf.
    """
    client, project, server, _, remote_meta = fetch_remote_snapshot(quiet=True)
    local_files = find_local_tracked_files()

    missing_remote = []
    stale_remote = []

    for rel_path in local_files:
        loc_f = PROJECT_DIR / rel_path
        loc_bytes = loc_f.read_bytes()
        loc_sha = sha256_bytes(loc_bytes)

        if rel_path not in remote_meta:
            missing_remote.append((rel_path, loc_sha, len(loc_bytes), None, 0))
            continue

        rem_sha = remote_meta[rel_path]["sha256"]
        rem_sz = remote_meta[rel_path]["size"]
        rem_bytes = (REMOTE_CACHE / rel_path).read_bytes()

        if is_text_file(rel_path):
            if not texts_equal_ignoring_eol(loc_bytes, rem_bytes):
                stale_remote.append((rel_path, loc_sha, len(loc_bytes), rem_sha, rem_sz))
        else:
            if loc_sha != rem_sha:
                stale_remote.append((rel_path, loc_sha, len(loc_bytes), rem_sha, rem_sz))

    mismatches = missing_remote + stale_remote
    n_figs = sum(1 for p in local_files if not is_text_file(p))

    if not mismatches:
        print(f"[OK] SHA-256 Verification Passed: All {len(local_files)} file(s) ({n_figs} binary asset(s)) match Overleaf byte-for-byte.")
        sync_olsync_state(server, project["id"], remote_meta)
        update_base()
        return

    print("\n" + "!" * 72)
    print("   SHA-256 Verification Alert: Stale / Un-synced File(s) Detected on Remote!")
    print("!" * 72)
    for rel_path, loc_sha, loc_sz, rem_sha, rem_sz in mismatches:
        status = "MISSING on remote" if rem_sha is None else "STALE on remote (same name, old content)"
        rem_info = "-" if rem_sha is None else f"{format_size(rem_sz)} ({rem_sha[:8]})"
        print(
            f"  [!] {rel_path}\n"
            f"      Status: {status}\n"
            f"      Local:  {format_size(loc_sz)} ({loc_sha[:8]})  |  Remote: {rem_info}"
        )

    if not force:
        ans = input(f"\nForce upload & overwrite these {len(mismatches)} file(s) to Overleaf? [Y/n]: ").strip().lower()
        if ans not in ("", "y", "yes"):
            print("[x] Force synchronization cancelled by user. Note: remote files remain outdated!")
            return

    print("\n[>>] Synchronizing mismatched files directly via Overleaf API...")
    project_infos = client.get_project_infos(project["id"])

    for rel_path, loc_sha, loc_sz, rem_sha, _ in mismatches:
        data = (PROJECT_DIR / rel_path).read_bytes()
        # For stale binary assets, delete-and-reupload guarantees Overleaf CE clears cached filestore blobs
        if rem_sha is not None and not is_text_file(rel_path):
            print(f"  [~] Replacing binary asset cleanly: {rel_path} ...")
            try:
                client.delete_file(project["id"], project_infos, rel_path)
                project_infos = client.get_project_infos(project["id"])
            except Exception as e:
                print(f"      (Pre-delete note: {e}; attempting direct overwrite...)")
        else:
            print(f"  [>] Uploading: {rel_path} ...")

        ok = client.upload_file(project["id"], project_infos, rel_path, len(data), io.BytesIO(data))
        if not ok:
            raise IOError(f"Failed to upload '{rel_path}' to Overleaf!")
        # Refresh tree metadata if subfolders might have been created
        if "/" in rel_path:
            project_infos = client.get_project_infos(project["id"])

    # Final cryptographic re-verification
    print("[>>] Re-verifying remote SHA-256 hashes...")
    _, _, _, _, fresh_meta = fetch_remote_snapshot(
        client=client, target_project=project, server=server, quiet=True
    )

    still_bad = []
    for rel_path, loc_sha, _, _, _ in mismatches:
        loc_bytes = (PROJECT_DIR / rel_path).read_bytes()
        if rel_path not in fresh_meta:
            still_bad.append(rel_path)
        elif is_text_file(rel_path):
            rem_bytes = (REMOTE_CACHE / rel_path).read_bytes()
            if not texts_equal_ignoring_eol(loc_bytes, rem_bytes):
                still_bad.append(rel_path)
        else:
            if sha256_bytes(loc_bytes) != fresh_meta[rel_path]["sha256"]:
                still_bad.append(rel_path)

    if still_bad:
        raise RuntimeError(f"Post-upload verification failed for: {', '.join(still_bad)}")

    print(f"[OK] 100% Verified! All {len(mismatches)} file(s) now match local SHA-256 on Overleaf.")
    sync_olsync_state(server, project["id"], fresh_meta)
    update_base()


def do_verify_pull(force=False):
    """
    Post-pull SHA-256 check to catch updated same-name remote assets skipped by ols -r.
    Safely defaults to 'No' on unexpected diffs unless --force is passed.
    """
    client, project, server, _, remote_meta = fetch_remote_snapshot(quiet=True)
    patterns = load_olignore_patterns()
    local_files = set(find_local_tracked_files())

    mismatches = []
    for rel_path, meta in sorted(remote_meta.items()):
        if matches_olignore(rel_path, patterns):
            continue
        loc_f = PROJECT_DIR / rel_path
        if not loc_f.is_file():
            mismatches.append((rel_path, "MISSING locally", None, 0, meta["sha256"], meta["size"]))
            continue
        loc_bytes = loc_f.read_bytes()
        rem_bytes = (REMOTE_CACHE / rel_path).read_bytes()
        if is_text_file(rel_path):
            if not texts_equal_ignoring_eol(loc_bytes, rem_bytes):
                mismatches.append((rel_path, "DIFFERS (Text)", sha256_bytes(loc_bytes), len(loc_bytes), meta["sha256"], meta["size"]))
        else:
            loc_sha = sha256_bytes(loc_bytes)
            if loc_sha != meta["sha256"]:
                mismatches.append((rel_path, "DIFFERS (Asset)", loc_sha, len(loc_bytes), meta["sha256"], meta["size"]))

    if not mismatches:
        print(f"[OK] SHA-256 Verification Passed: Local workspace matches Overleaf ({len(local_files)} tracked files).")
        sync_olsync_state(server, project["id"], remote_meta)
        update_base()
        return

    print("\n" + "!" * 72)
    print("   Post-Pull Notice: Remaining Differences Between Local and Remote")
    print("!" * 72)
    for rel_path, kind, loc_sha, loc_sz, rem_sha, rem_sz in mismatches:
        loc_info = "-" if loc_sha is None else f"{format_size(loc_sz)} ({loc_sha[:8]})"
        print(
            f"  [!] {rel_path} [{kind}]\n"
            f"      Local:  {loc_info}  |  Remote: {format_size(rem_sz)} ({rem_sha[:8]})"
        )

    if not force:
        ans = input(
            f"\nOverwrite local workspace with these {len(mismatches)} remote file(s)?\n"
            "(Choose 'N' if you intentionally have unpushed local edits; run 'collabtex-diff' or 'collabtex-merge') [y/N]: "
        ).strip().lower()
        if ans not in ("y", "yes"):
            print("[*] Kept local differing files. Run 'collabtex-merge' or 'collabtex-diff' to inspect.")
            return

    stamp = time.strftime("%Y%m%d_%H%M%S")
    cur_backup = BACKUP_DIR / f"pull_backup_{stamp}"
    cur_backup.mkdir(parents=True, exist_ok=True)

    for rel_path, _, _, _, _, _ in mismatches:
        dst = PROJECT_DIR / rel_path
        dst.parent.mkdir(parents=True, exist_ok=True)
        if dst.is_file():
            bak = cur_backup / rel_path
            bak.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(dst, bak)
        shutil.copy2(REMOTE_CACHE / rel_path, dst)
        print(f"  [<] Pulled: {rel_path}")

    print(f"[OK] Synced {len(mismatches)} file(s) from remote (backups in .collabtex_cache/backup/pull_backup_{stamp}/).")
    sync_olsync_state(server, project["id"], remote_meta)
    update_base()


def main():
    if len(sys.argv) < 2:
        print("Usage: collabtex_tool.py [diff | merge | update-base | verify-push | verify-pull | refresh-auth] [--force]")
        sys.exit(1)

    cmd = sys.argv[1].lower()
    force = any(a.lower() in ("-f", "--force", "-force") for a in sys.argv[2:])

    if cmd == "diff":
        do_diff()
    elif cmd == "merge":
        do_merge()
    elif cmd in ("update-base", "update_base"):
        update_base()
    elif cmd in ("verify-push", "verify_push"):
        do_verify_push(force=force)
    elif cmd in ("verify-pull", "verify_pull"):
        do_verify_pull(force=force)
    elif cmd in ("refresh-auth", "refresh_auth"):
        refresh_auth_csrf(quiet=False)
    else:
        print(f"Unknown command: {cmd}")
        sys.exit(1)


if __name__ == "__main__":
    main()
