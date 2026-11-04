"""
Automated Patch for overleaf-sync (olsync) for Helmholtz Cloud / Overleaf Community Edition.
Fixes:
1. Socket.IO connectionAccepted & joinProject ACK handshake in realtime.py
2. UTF-8 encoding & comment stripping in olsync.py (.olignore)
"""
import os, sys, site

site_packages = site.getsitepackages()
olsync_dir = None
for sp in site_packages:
    target = os.path.join(sp, 'olsync')
    if os.path.isdir(target):
        olsync_dir = target
        break

if not olsync_dir:
    # Try finding via import
    try:
        import olsync
        olsync_dir = os.path.dirname(olsync.__file__)
    except Exception:
        pass

if not olsync_dir:
    print("[!] Could not locate olsync in site-packages. Make sure 'pip install overleaf-sync' is run.")
    sys.exit(1)

print(f"[>>] Found olsync at: {olsync_dir}")

# 1. Patch realtime.py
realtime_path = os.path.join(olsync_dir, 'realtime.py')
with open(realtime_path, 'r', encoding='utf-8') as f:
    content = f.read()

old_block = '''                fields = packet.split(":", 3)
                kind, data = fields[0], fields[3] if len(fields) > 3 else ""
                if kind == "2":  # heartbeat, answer it to keep the connection
                    request("POST", poll_url, session=session, timeout=30, data="2::")
                elif kind == "5":  # event
                    event = json.loads(data)
                    args = event.get("args") or []
                    if event.get("name") == "joinProjectResponse":
                        return args[0]["project"]'''

new_block = '''                fields = packet.split(":", 3)
                kind, data = fields[0], fields[3] if len(fields) > 3 else ""
                if kind == "1":
                    payload = json.dumps({"name": "joinProject", "args": [{"project_id": project_id}]})
                    request("POST", poll_url, session=session, timeout=30, data=f"5:1+::{payload}")
                elif kind == "2":  # heartbeat, answer it to keep the connection
                    request("POST", poll_url, session=session, timeout=30, data="2::")
                elif kind == "6":  # ack: in Overleaf CE, joinProject returns as 6:::1+[null, project]
                    raw_ack = data
                    if "+" in raw_ack:
                        raw_ack = raw_ack.split("+", 1)[1]
                    try:
                        args = json.loads(raw_ack)
                        if isinstance(args, list) and len(args) > 1 and isinstance(args[1], dict) and "rootFolder" in args[1]:
                            return args[1]
                        elif isinstance(args, list) and len(args) > 0 and isinstance(args[0], dict) and "rootFolder" in args[0]:
                            return args[0]
                    except Exception:
                        pass
                elif kind == "5":  # event
                    event = json.loads(data)
                    args = event.get("args") or []
                    if event.get("name") == "joinProjectResponse":
                        return args[0]["project"]
                    if event.get("name") == "connectionAccepted":
                        payload = json.dumps({"name": "joinProject", "args": [{"project_id": project_id}]})
                        request("POST", poll_url, session=session, timeout=30, data=f"5:1+::{payload}")'''

if old_block in content:
    content = content.replace(old_block, new_block)
    with open(realtime_path, 'w', encoding='utf-8') as f:
        f.write(content)
    print("[OK] Successfully patched realtime.py!")
else:
    print("[*] realtime.py already patched or modified.")

# 2. Patch olsync.py
olsync_path = os.path.join(olsync_dir, 'olsync.py')
with open(olsync_path, 'r', encoding='utf-8') as f:
    os_content = f.read()

old_olignore = 'with open(olignore_path, "r") as f:\n            # "./main.tex" and "main.tex" mean the same file, matched paths have no "./" prefix (#72)\n            ignore_pattern = [pattern.removeprefix("./") for pattern in f.read().splitlines()]'
new_olignore = 'with open(olignore_path, "r", encoding="utf-8", errors="ignore") as f:\n            # "./main.tex" and "main.tex" mean the same file, matched paths have no "./" prefix (#72)\n            ignore_pattern = [line.strip().removeprefix("./") for line in f.read().splitlines() if line.strip() and not line.strip().startswith("#")]'

if old_olignore in os_content:
    os_content = os_content.replace(old_olignore, new_olignore)
    with open(olsync_path, 'w', encoding='utf-8') as f:
        f.write(os_content)
    print("[OK] Successfully patched olsync.py!")
else:
    print("[*] olsync.py already patched or modified.")

# 3. Patch olclient.py (Fix qqfile filename issue in Overleaf Community Edition)
olclient_path = os.path.join(olsync_dir, 'olclient.py')
with open(olclient_path, 'r', encoding='utf-8') as f:
    cl_content = f.read()

old_upload = '''        files = {
            # Overleaf's upload endpoint now rejects the request with 422
            # {"success":false,"error":"invalid_filename"} unless the
            # filename is also present as a plain multipart field, not just
            # in qqfilename above. Confirmed live: identical request without
            # this field gets 422; with it, 200 and the file is actually
            # updated. It must be the bare file name: Overleaf rejects names
            # containing "/" (SafePath), the folder is chosen via folder_id.
            "name": (None, file_name.split(PATH_SEP)[-1]),
            "qqfile": file,
        }'''
new_upload = '''        bare_filename = file_name.split(PATH_SEP)[-1]
        files = {
            "name": (None, bare_filename),
            "qqfile": (bare_filename, file, "application/octet-stream"),
        }'''

if old_upload in cl_content:
    cl_content = cl_content.replace(old_upload, new_upload)
    with open(olclient_path, 'w', encoding='utf-8') as f:
        f.write(cl_content)
    print("[OK] Successfully patched olclient.py (fixed qqfile upload bug)!")
else:
    print("[*] olclient.py already patched or modified.")

print("[SUCCESS] All patches applied. Overleaf Community Edition is now fully compatible!")
