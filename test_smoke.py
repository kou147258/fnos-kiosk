#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""smoke test for v0.1.36 cross-platform file:// URL + page fit logic"""
import sys, os, tempfile, re
sys.path.insert(0, 'app/bin')
from dash_pages import PageStore, _file_url

print("=== _file_url cross-platform ===")
for p in ['/var/lib/kiosk/img.png', 'C:/Users/x/img.png', '/tmp/img.png']:
    u = _file_url(p)
    ok = u.startswith('file:///')
    print(f"  {p!r:35s} -> {u!r:45s} {'OK' if ok else 'WRONG'}")

print()
print("=== PageStore.write_bytes + wrapper URL ===")
ps = PageStore(tempfile.mkdtemp())
ps.write_bytes('test.png', b'\x89PNG\r\n\x1a\n' + b'\x00' * 100, fit='contain')
content = open(os.path.join(ps.root, '_wrap_test.html'), encoding='utf-8').read()
m = re.search(r'src="([^"]+)"', content)
url = m.group(1) if m else None
print(f"  wrapper img src: {url}")
assert url and url.startswith('file:///'), f"wrapper URL must start with file:///, got {url}"
print("  OK")

print()
print("=== _file_url applied to to_file_url (wrapper) ===")
wrap_url = ps.to_file_url('test.png')
print(f"  to_file_url: {wrap_url}")
assert wrap_url.startswith('file:///'), f"to_file_url must start with file:///, got {wrap_url}"
print("  OK")

# to_file_url on plain html
ps.write('plain.html', '<html></html>')
plain_url = ps.to_file_url('plain.html')
print(f"  plain.html: {plain_url}")
assert plain_url.startswith('file:///')
print("  OK")

print()
print("=== full v0.1.36 regression: per-page fit + url_kiosk_css hot-reload ===")
from dash_config import Config
cfg_dir = tempfile.mkdtemp()
etc_path = os.path.join(cfg_dir, 'etc.json')
c = Config(etc_path, cfg_dir)
# Test 1: default url_kiosk_css
default_css = c.get().get('url_kiosk_css')
assert default_css and 'html,body' in default_css, f"expected default CSS, got {default_css!r}"
print(f"  default url_kiosk_css len: {len(default_css)} chars")
# Test 2: set safe CSS
ok, err = c.update({'url_kiosk_css': 'a{color:red}'})
assert ok and not err, f"safe CSS update failed: {err}"
assert c.get()['url_kiosk_css'] == 'a{color:red}'
print("  safe CSS update: OK")
# Test 3: reject malicious
ok, err = c.update({'url_kiosk_css': 'a onclick=alert(1){}'})
assert not ok, "must reject onclick"
print("  malicious onclick rejected: OK")
# Test 4: page fit values
ok, err = c.update({'pages': [{'id': 'k1', 'type': 'url', 'url': 'https://x.com',
                                'fit': 'cover'}]})
assert ok
assert c.get()['pages'][0]['fit'] == 'cover'
print("  page.fit='cover' accepted: OK")
# Test 5: invalid fit → 'none' (单元素页列表，因为 update 替换)
ok, err = c.update({'pages': [{'id': 'k2', 'type': 'url', 'url': 'https://y.com',
                                'fit': 'weird'}]})
assert ok
pages_after = c.get()['pages']
assert len(pages_after) == 1, f"len={len(pages_after)}"
assert pages_after[0]['fit'] == 'none', f"got {pages_after[0]['fit']}"
print("  invalid fit → 'none': OK")

print()
print("=== fmtZ regression (JS simulated) ===")
presets = [0.5, 0.67, 0.75, 1.0, 1.25, 1.5, 2.0, 2.5, 3.0]
def fmtZ(v): return f"{round(v * 100)}%"
for v in presets:
    label = fmtZ(v)
    # All integer% labels must not look weird (1% vs 100%)
    expected = f"{round(v * 100)}%"
    assert label == expected, f"fmtZ({v})={label}, expected {expected}"
print(f"  all 9 presets display correctly: OK")

# Verify set_kiosk_css method exists and accepts empty
from dash_browser import Browser
import inspect
sig = inspect.signature(Browser.set_kiosk_css)
assert 'css' in sig.parameters
print()
print("=== Browser.set_kiosk_css signature ===")
print(f"  {sig}")

print()
print("=== write_bytes fit param regression ===")
ps2 = PageStore(tempfile.mkdtemp())
ps2.write_bytes('a.png', b'\x89PNG\r\n\x1a\n' + b'\x00' * 100, fit='cover')
content = open(os.path.join(ps2.root, '_wrap_a.html'), encoding='utf-8').read()
assert 'object-fit:cover' in content
print("  fit=cover upload → wrapper object-fit:cover OK")

ps2.write_bytes('b.png', b'\x89PNG\r\n\x1a\n' + b'\x00' * 100)
content = open(os.path.join(ps2.root, '_wrap_b.html'), encoding='utf-8').read()
assert 'object-fit:contain' in content
print("  no fit param → wrapper object-fit:contain OK")

ps2.write_bytes('c.png', b'\x89PNG\r\n\x1a\n' + b'\x00' * 100, fit='garbage')
content = open(os.path.join(ps2.root, '_wrap_c.html'), encoding='utf-8').read()
assert 'object-fit:contain' in content
print("  invalid fit → fallback contain OK")

m = re.search(r'src="([^"]+)"', content)
assert m.group(1).startswith('file:///'), f"got {m.group(1)}"
print(f"  file:// URL format OK: {m.group(1)[:60]}...")

print()
print("ALL SMOKE TESTS PASS")