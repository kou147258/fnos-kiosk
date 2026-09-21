#!/usr/bin/env python3
"""Push v0.1.40 to origin + tag via Python urllib (more reliable than git/CLI under flaky network)."""
import json, os, subprocess, sys, time, base64
import urllib.request, urllib.error

# GitHub API auth via env (set in mavis env)
token = os.environ.get('GITHUB_TOKEN')
if not token:
    # Try to read from .git/config or git credential store
    print('GITHUB_TOKEN env not set; using git credentials from system')
else:
    print(f'token len: {len(token)}')

# Get the FPK + release notes from local files
fpk_path = 'C:/Users/43457/.minimax/sessions/mvs_ae665f103f9d4619bd8cb74072a77ac9/workspace/fnos-kiosk/com.fnos.kiosk.fpk'
notes_path = 'C:/Users/43457/.minimax/sessions/mvs_ae665f103f9d4619bd8cb74072a77ac9/workspace/fnos-kiosk/release-notes-v0.1.40.md'

if not os.path.isfile(fpk_path):
    print(f'FPK not found: {fpk_path}')
    sys.exit(1)
if not os.path.isfile(notes_path):
    print(f'release notes not found: {notes_path}')
    sys.exit(1)

fpk_size = os.path.getsize(fpk_path)
print(f'FPK: {fpk_size} bytes')
with open(fpk_path, 'rb') as f:
    fpk_b64 = base64.b64encode(f.read()).decode()
with open(notes_path, 'r', encoding='utf-8') as f:
    notes = f.read()

# Try git push via subprocess with retry
print('=== Attempting git push ===')
for attempt in range(8):
    try:
        r = subprocess.run(['git', 'push', 'origin', 'master', 'v0.1.40'],
                          cwd=os.path.dirname(fpk_path),
                          capture_output=True, text=True, timeout=60)
        print(f'[{attempt+1}] exit={r.returncode}')
        if r.stdout: print(f'    stdout: {r.stdout.strip()[-200:]}')
        if r.stderr: print(f'    stderr: {r.stderr.strip()[-200:]}')
        if r.returncode == 0:
            print('PUSH OK')
            break
    except subprocess.TimeoutExpired:
        print(f'[{attempt+1}] timeout')
    time.sleep(3)
else:
    print('All retries failed; commit is local only. Continuing to create release via API.')

print()
print('=== Attempting GitHub release create via API ===')
# Even if push failed, we can still create the release pointing to the local FPK
import urllib.request
for attempt in range(5):
    try:
        url = 'https://api.github.com/repos/kou147258/fnos-kiosk/releases'
        body = json.dumps({
            'tag_name': 'v0.1.40',
            'name': 'v0.1.40 — URL 内容自动缩放填满 fb0',
            'body': notes,
            'draft': False,
            'prerelease': False,
        }).encode()
        req = urllib.request.Request(url, data=body, method='POST')
        if token:
            req.add_header('Authorization', f'token {token}')
        req.add_header('Accept', 'application/vnd.github+json')
        req.add_header('Content-Type', 'application/json')
        req.add_header('User-Agent', 'fnos-kiosk-publisher')
        with urllib.request.urlopen(req, timeout=30) as resp:
            print(f'[{attempt+1}] status={resp.status}')
            data = json.loads(resp.read())
            print(f'    release id: {data.get("id")}')
            print(f'    url: {data.get("html_url")}')
            print(f'    upload_url: {data.get("upload_url", "")[:100]}...')
            break
    except urllib.error.HTTPError as e:
        print(f'[{attempt+1}] HTTPError {e.code}: {e.read().decode()[:200]}')
        if e.code == 422 and 'already_exists' in e.read().decode():
            print('release already exists; skipping create')
            break
    except Exception as e:
        print(f'[{attempt+1}] error: {e}')
    time.sleep(3)