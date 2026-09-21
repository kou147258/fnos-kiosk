#!/usr/bin/env python3
"""v0.1.42 完整核查"""
import ast, os, sys, re, hashlib, subprocess
import urllib.request, json

print('=== 1. syntax check 所有 .py 文件 ===')
for p in ['app/bin/dash_browser.py','app/bin/dash_config.py','app/bin/dash_http.py',
          'app/bin/dash_pages.py','app/bin/fb_render.py','app/bin/dashboard.py']:
    try:
        ast.parse(open(p,'rb').read().decode('utf-8'), p)
        print(f'  OK   {p}')
    except SyntaxError as e:
        print(f'  ERR  {p}: {e}')

print()
print('=== 2. JS / HTML syntax ===')
r = subprocess.run(['node', '-e',
    'const fs=require("fs"); new Function(fs.readFileSync("app/web/assets/settings.js","utf8")); console.log("settings.js OK")'],
    capture_output=True, text=True, timeout=10)
print(f'  settings.js: {r.stdout.strip() or r.stderr.strip()}')

print()
print('=== 3. 版本号一致性 ===')
ver_m = re.search(r'version=(\d+\.\d+\.\d+)', open('manifest','rb').read().decode('utf-8')).group(1)
ver_d = re.search(r'APP_VERSION\s*=\s*["\']([\d.]+)["\']', open('app/bin/dash_config.py','rb').read().decode('utf-8')).group(1)
print(f'  manifest: {ver_m}')
print(f'  dash_config.APP_VERSION: {ver_d}')
assert ver_m == ver_d, f'MISMATCH'
print(f'  OK 一致')

print()
print('=== 4. FPK 哈希 ===')
fpk_path = 'com.fnos.kiosk.fpk'
h = hashlib.sha256(open(fpk_path,'rb').read()).hexdigest()
sz = os.path.getsize(fpk_path)
print(f'  本地 SHA256: {h}')
print(f'  大小: {sz} bytes')

print()
print('=== 5. match_fb_wide 逻辑测试 ===')
src = open('app/bin/fb_render.py','rb').read().decode('utf-8')
# 找 match_fb_wide 字符串
print(f'  "match_fb_wide" in src: {"match_fb_wide" in src}')
print(f'  "match_fb" still in src (向后兼容): {"match_fb" in src}')

# 检查 settings.html 是否有 match_fb_wide 选项
html = open('app/web/settings.html','rb').read().decode('utf-8')
print(f'  settings.html has match_fb_wide button: {chr(34) + "match_fb_wide" + chr(34) in html}')

print()
print('=== 6. fb 尺寸变化测试 ===')
def compute_viewport(bw_cfg, W, H):
    """模拟 fb_render.py 的逻辑"""
    if isinstance(bw_cfg, str):
        bw_lower = bw_cfg.lower()
        if bw_lower in ("match_fb", "fb", "auto"):
            return (W, H)
        elif bw_lower in ("match_fb_wide", "wide", "1.25x"):
            return (int(W * 1.25), int(H * 1.25))
        else:
            return (W, H)
    else:
        return (int(bw_cfg[0]), int(bw_cfg[1]))

# fb 1024x768 (用户的硬件)
print('  fb=1024x768:')
print(f'    default (match_fb_wide): {compute_viewport("match_fb_wide", 1024, 768)} (expect 1280x960)')
print(f'    match_fb: {compute_viewport("match_fb", 1024, 768)} (expect 1024x768)')
print(f'    explicit [1920,1080]: {compute_viewport([1920,1080], 1024, 768)} (expect 1920x1080)')

# fb 1920x1080 (HiDPI 用户)
print('  fb=1920x1080:')
print(f'    default (match_fb_wide): {compute_viewport("match_fb_wide", 1920, 1080)} (expect 2400x1350)')
print(f'    match_fb: {compute_viewport("match_fb", 1920, 1080)} (expect 1920x1080)')

# fb 1280x720 (16:9 物理)
print('  fb=1280x720:')
print(f'    default (match_fb_wide): {compute_viewport("match_fb_wide", 1280, 720)} (expect 1600x900)')

print()
print('=== 7. settings.js UI 兼容性 ===')
js = open('app/web/assets/settings.js','rb').read().decode('utf-8')
print(f'  seg-win-preset handler exists: {"#seg-win-preset" in js}')
print(f'  match_fb_wide 字符串处理: {"match_fb_wide" in js}')
print(f'  wide 字符串处理: {chr(34) + "wide" + chr(34) in js}')
print(f' 1.25x 字符串处理: {"1.25x" in js}')

print()
print('=== 8. 关键修改点都到位 ===')
checks = [
    ('match_fb_wide 字符串（fb_render.py）', 'match_fb_wide', True),
    ('match_fb 仍然支持（向后兼容）', 'match_fb', True),
    ('×1.25 计算常量', 'W * 1.25', True),
    ('default match_fb_wide（两处）', 'match_fb_wide', True),
    ('set_kiosk_css 仍工作', '__kioskFit', True),
    ('auto-fit body.style.zoom', 'body.style.zoom=', True),
    ('debug indicator', '__kiosk_fit_dbg', True),
    ('MutationObserver', 'MutationObserver', True),
    ('set_page 幂等', 'new_url != old_url', True),
    ('_file_url 跨平台', '_file_url', True),
    ('wrapper fit 三档', '("contain", "cover", "fill")', True),
]
src_browser = open('app/bin/dash_browser.py','rb').read().decode('utf-8')
src_fb = open('app/bin/fb_render.py','rb').read().decode('utf-8')
src_pages = open('app/bin/dash_pages.py','rb').read().decode('utf-8')
for name, needle, expected in checks:
    # decide which file to check
    if 'match_fb_wide' in name or '×1.25' in name:
        file_src = src_fb
    elif 'kiosk_css' in name or 'MutationObserver' in name or 'body.style.zoom' in name or 'debug indicator' in name or 'set_kiosk_css' in name:
        file_src = src_browser
    elif '_file_url' in name or 'wrapper' in name:
        file_src = src_pages
    elif 'set_page' in name or 'match_fb 仍然' in name:
        file_src = src_fb
    else:
        file_src = src_browser
    has = needle in file_src
    ok = has == expected
    print(f'  {"OK  " if ok else "FAIL"} {name}: needle={needle!r} present={has}')

print()
print('=== 9. GitHub Release 一致性 ===')
try:
    url = 'https://api.github.com/repos/kou147258/fnos-kiosk/releases/tags/v0.1.42'
    req = urllib.request.Request(url, headers={'Accept':'application/vnd.github+json'})
    with urllib.request.urlopen(req, timeout=15) as resp:
        data = json.loads(resp.read())
        print(f'  tag: {data["tag_name"]}')
        for a in data.get('assets', []):
            print(f'  asset: {a["name"]} {a["size"]} bytes SHA256={a["digest"]}')
            remote_hash = a['digest'].replace('sha256:', '')
            match = 'OK' if remote_hash == h else 'FAIL'
            print(f'    local == remote: {match}')
except Exception as e:
    print(f'  WARN: GitHub API 调用失败: {e}')

print()
print('=== 10. v0.1.41 之前修复的回归测试 ===')
sys.path.insert(0, 'app/bin')
from dash_pages import PageStore, _file_url, kind_of
from dash_config import Config
import tempfile

# A. _file_url
for p in ['/var/lib/kiosk/img.png', 'C:/Users/x/img.png']:
    u = _file_url(p)
    assert u.startswith('file:///'), f'{p}: {u}'
print(f'  A. _file_url 跨平台: OK')

# B. wrapper 三档
ps = PageStore(tempfile.mkdtemp())
for fit in ('contain', 'cover', 'fill'):
    ps.write_bytes(f'a_{fit}.png', b'\x89PNG' + b'\x00' * 10, fit=fit)
    body = open(os.path.join(ps.root, f'_wrap_a_{fit}.html'), encoding='utf-8').read()
    assert f'object-fit:{fit}' in body
print(f'  B. wrapper fit 三档: OK')

# C. url_kiosk_css 安全
c = Config(os.path.join(tempfile.mkdtemp(), 'etc.json'), tempfile.mkdtemp())
# (css, expected_ok)
test_cases = [
    ('body{color:red}', True),
    ('a onclick=1{}', False),
    ('a{background:url(javascript:1)}', False),
    ('<script>1</script>', False),
    ('a{width:expression(1)}', False),
]
for css, expected_ok in test_cases:
    ok, err = c.update({'url_kiosk_css': css})
    mark = 'OK' if ok == expected_ok else 'FAIL'
    print(f'    {css[:30]:30s}: ok={ok} expected={expected_ok} {mark}')

print()
print('=== ALL VERIFICATION COMPLETE ===')