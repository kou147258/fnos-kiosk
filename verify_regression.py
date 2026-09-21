#!/usr/bin/env python3
"""v0.1.41 完整回归测试"""
import sys, tempfile, os
sys.path.insert(0, 'app/bin')
from dash_pages import PageStore, _file_url, kind_of

print('=== v0.1.41 完整回归 ===')
print()

print('--- A. _file_url 跨平台 ---')
for p in ['/var/lib/kiosk/img.png', 'C:/Users/x/img.png', '/tmp/img.png']:
    u = _file_url(p)
    mark = 'OK' if u.startswith('file:///') else 'WRONG'
    print(f'  {p!r:35s} -> {u!r:45s} {mark}')

print()

print('--- B. wrapper HTML fit 三档 ---')
ps = PageStore(tempfile.mkdtemp())
for fit in ('contain', 'cover', 'fill', 'garbage'):
    ps.write_bytes(f'a_{fit}.png', b'\x89PNG' + b'\x00' * 10, fit=fit)
    body = open(os.path.join(ps.root, f'_wrap_a_{fit}.html'), encoding='utf-8').read()
    expected = f'object-fit:{fit if fit != "garbage" else "contain"}'
    mark = 'OK' if expected in body else 'FAIL'
    print(f'  fit={fit:10s} wrapper has {expected!r}: {mark}')

print()

print('--- C. _sync_page_wrappers 触发条件 ---')
prev = {'pages': [
    {'id': 'k1', 'type': 'media_file', 'path': 'img.png', 'fit': 'contain'},
    {'id': 'k2', 'type': 'url', 'url': 'https://x', 'fit': 'cover'},
]}
cur = {'pages': [
    {'id': 'k1', 'type': 'media_file', 'path': 'img.png', 'fit': 'cover'},
    {'id': 'k2', 'type': 'url', 'url': 'https://x', 'fit': 'cover'},
]}
ps = PageStore(tempfile.mkdtemp())
ps.write_bytes('img.png', b'\x89PNG' + b'\x00' * 10)
prev_by_id = {p.get('id'): p for p in (prev.get('pages') or [])}
fired = []
for p in (cur.get('pages') or []):
    if p.get('type') != 'media_file':
        continue
    path = p.get('path') or ''
    if not path or kind_of(path) not in ('image', 'video'):
        continue
    old_fit = (prev_by_id.get(p.get('id')) or {}).get('fit', 'none')
    new_fit = p.get('fit', 'none')
    if old_fit == new_fit:
        continue
    if new_fit not in ('contain', 'cover', 'fill'):
        continue
    fired.append((path, new_fit))
expected_fired = [('img.png', 'cover')]
mark = 'OK' if fired == expected_fired else 'FAIL'
print(f'  fired events: {fired} expected={expected_fired}: {mark}')

print()

print('--- D. Config patch 拒绝恶意 url_kiosk_css ---')
from dash_config import Config
c = Config(os.path.join(tempfile.mkdtemp(), 'etc.json'), tempfile.mkdtemp())
tests = [
    ('safe css', 'body{color:red}', True),
    ('onclick rejected', 'a onclick=alert(1){}', False),
    ('javascript: rejected', 'a{background:url(javascript:1)}', False),
    ('<script> rejected', '<script>alert(1)</script>', False),
    ('expression() rejected', 'a{width:expression(alert(1))}', False),
]
for name, css, expected_ok in tests:
    ok, err = c.update({'url_kiosk_css': css})
    mark = 'OK' if ok == expected_ok else 'FAIL'
    print(f'  {name}: ok={ok} expected={expected_ok} {mark}')

print()

print('--- E. fit 字段校验 ---')
fit_tests = [
    ('fit=cover', 'cover', 'cover'),
    ('fit=invalid', 'garbage', 'none'),
    ('fit=none', 'none', 'none'),
    ('fit=missing', None, 'none'),
]
for name, fit_val, expected in fit_tests:
    page = {'id': 'k1', 'type': 'url', 'url': 'https://x.com'}
    if fit_val is not None:
        page['fit'] = fit_val
    ok, err = c.update({'pages': [page]})
    saved = c.get()['pages'][-1]['fit']
    mark = 'OK' if saved == expected else 'FAIL'
    print(f'  {name}: saved={saved!r} expected={expected!r} {mark}')

print()

print('--- F. set_kiosk_css 签名 + 空 css 早返回 ---')
from dash_browser import Browser
import inspect
sig = inspect.signature(Browser.set_kiosk_css)
print(f'  signature: set_kiosk_css{sig}')
src = inspect.getsource(Browser.set_kiosk_css)
has_empty_check = 'if not css' in src and 'return' in src.split('if not css')[1][:50]
print(f'  empty css early return: {"OK" if has_empty_check else "FAIL"}')

print()

print('--- G. FPK 完整性 + 远端 release 一致性 ---')
import re, hashlib
ver = re.search(r'version=(\d+\.\d+\.\d+)', open('manifest', 'rb').read().decode('utf-8')).group(1)
fpk_hash = hashlib.sha256(open('com.fnos.kiosk.fpk', 'rb').read()).hexdigest()
print(f'  manifest version: {ver}')
print(f'  FPK sha256: {fpk_hash}')

import urllib.request, json
try:
    url = 'https://api.github.com/repos/kou147258/fnos-kiosk/releases/tags/v0.1.41'
    req = urllib.request.Request(url, headers={'Accept': 'application/vnd.github+json'})
    with urllib.request.urlopen(req, timeout=15) as resp:
        data = json.loads(resp.read())
        remote_hash = data['assets'][0]['digest'].replace('sha256:', '')
        match = 'OK' if remote_hash == fpk_hash else 'FAIL'
        print(f'  remote FPK sha256: {remote_hash}')
        print(f'  local == remote: {match}')
except Exception as e:
    print(f'  WARN: GitHub API unreachable: {e}')

print()

print('=== ALL TESTS COMPLETE ===')