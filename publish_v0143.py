#!/usr/bin/env python3
"""通过 Python urllib 发布 v0.1.43 Release（gh CLI 在 EOF 时用）"""
import os, sys, json, time, subprocess, base64
import urllib.request, urllib.error

REPO = 'kou147258/fnos-kiosk'
TAG = 'v0.1.43'
TITLE = 'v0.1.43 — 中文字体 fallback + 强制 dashboard 容器'
FPK = r'C:\Users\43457\.minimax\sessions\mvs_ae665f103f9d4619bd8cb74072a77ac9\workspace\fnos-kiosk\com.fnos.kiosk.fpk'
NOTES = r'C:\Users\43457\.minimax\sessions\mvs_ae665f103f9d4619bd8cb74072a77ac9\workspace\fnos-kiosk\release-notes-v0.1.43.md'

with open(NOTES, encoding='utf-8') as f:
    notes = f.read()

# Get token from gh CLI auth
print('Getting gh token...')
try:
    r = subprocess.run(['gh', 'auth', 'token'], capture_output=True, text=True, timeout=10)
    token = r.stdout.strip()
    print(f'  token len: {len(token)}')
except Exception as e:
    print(f'  gh auth token failed: {e}')
    token = os.environ.get('GITHUB_TOKEN', '')

if not token:
    print('No token; aborting')
    sys.exit(1)

def http(method, url, body=None, content_type=None):
    req = urllib.request.Request(url, data=body, method=method)
    req.add_header('Authorization', f'token {token}')
    req.add_header('Accept', 'application/vnd.github+json')
    if content_type:
        req.add_header('Content-Type', content_type)
    req.add_header('User-Agent', 'fnos-kiosk-publisher')
    return urllib.request.urlopen(req, timeout=30)

# 1. Create release
print('=== Creating release ===')
release_url = f'https://api.github.com/repos/{REPO}/releases'
body = json.dumps({
    'tag_name': TAG, 'name': TITLE, 'body': notes,
    'draft': False, 'prerelease': False,
}).encode()
for attempt in range(6):
    try:
        resp = http('POST', release_url, body, 'application/json')
        data = json.loads(resp.read())
        print(f'  [{attempt+1}] Created: {data["html_url"]}')
        rid = data['id']
        upload_url = data['upload_url'].replace('{?name,label}', '')
        break
    except urllib.error.HTTPError as e:
        if e.code == 422 and b'already_exists' in e.read():
            print(f'  release {TAG} already exists; will just upload asset')
            # Get existing release
            get = subprocess.run(['gh', 'release', 'view', TAG, '--repo', REPO,
                                 '--json', 'id,uploadUrl'], capture_output=True, text=True)
            try:
                d = json.loads(get.stdout)
                rid = d['id']
                upload_url = d['uploadUrl'].replace('{?name,label}', '')
                print(f'  existing release id: {rid}')
                break
            except Exception:
                pass
        print(f'  [{attempt+1}] HTTP {e.code}: {e.read().decode()[:200]}')
    except Exception as e:
        print(f'  [{attempt+1}] error: {e}')
    time.sleep(3)
else:
    print('All attempts failed')
    sys.exit(1)

# 2. Upload FPK asset
print('=== Uploading FPK ===')
fpk_name = 'com.fnos.kiosk.fpk'
fpk_size = os.path.getsize(FPK)
print(f'  file: {fpk_name} ({fpk_size} bytes)')

with open(FPK, 'rb') as f:
    fpk_data = f.read()

upload_full = f'{upload_url}?name={fpk_name}'
for attempt in range(6):
    try:
        req = urllib.request.Request(upload_full, data=fpk_data, method='POST')
        req.add_header('Authorization', f'token {token}')
        req.add_header('Accept', 'application/vnd.github+json')
        req.add_header('Content-Type', 'application/octet-stream')
        req.add_header('Content-Length', str(len(fpk_data)))
        req.add_header('User-Agent', 'fnos-kiosk-publisher')
        resp = urllib.request.urlopen(req, timeout=120)
        d = json.loads(resp.read())
        print(f'  [{attempt+1}] Uploaded: {d["browser_download_url"]}')
        print(f'  size: {d["size"]}')
        break
    except urllib.error.HTTPError as e:
        print(f'  [{attempt+1}] HTTP {e.code}: {e.read().decode()[:200]}')
        if e.code == 422 and b'already_exists' in e.read():
            print('  asset already uploaded; skipping')
            break
    except Exception as e:
        print(f'  [{attempt+1}] error: {e}')
    time.sleep(3)

print()
print('=== DONE ===')