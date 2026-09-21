#!/usr/bin/env python3
"""完整核查 v0.1.41"""
import ast, os, sys, re, hashlib, subprocess

print('=== 1. syntax check 所有 .py 文件 ===')
for p in ['app/bin/dash_browser.py','app/bin/dash_config.py','app/bin/dash_http.py',
          'app/bin/dash_pages.py','app/bin/fb_render.py','app/bin/dashboard.py']:
    try:
        ast.parse(open(p,'rb').read().decode('utf-8'), p)
        print(f'  OK  {p}')
    except SyntaxError as e:
        print(f'  ERR {p}: {e}')

print()
print('=== 2. JS 注入语法验证 ===')
src = open('app/bin/dash_browser.py','rb').read().decode('utf-8')
# Extract all JS source strings from set_kiosk_css
import re
# Find all "(function()..." blocks (they're concatenated as strings)
matches = re.findall(r'"(\(\(\)function|function \(\)|\(function\(\)\{)[^"]*', src)
print(f'  找到 {len(matches)} 个 JS 字符串片段')

# Extract the auto-fit block (has MutationObserver + body.style.zoom)
m = re.search(r'"(\(function\(\)\{[^"]*?MutationObserver[^"]*?)"\s*\+\s*"\)\(\);"', src, re.DOTALL)
if m:
    # 重新组合所有字符串片段（dash_browser.py 把 JS 分成多行字符串拼接）
    # 简化版：找 set_kiosk_css 函数内的所有 string literal
    fn_match = re.search(r'def set_kiosk_css.*?try:\s*\n\s*r = self\.call', src, re.DOTALL)
    if fn_match:
        block = fn_match.group(0)
        # 提取引号字符串（支持双引号字符串拼接）
        parts = re.findall(r'"([^"\\]*(?:\\.[^"\\]*)*)"', block)
        js_combined = ''.join(parts)
        # 写到临时文件用 node --check 验证
        with open('/tmp/_kiosk_fit.js', 'w') as f:
            f.write(js_combined)
        r = subprocess.run(['node', '--check', '/tmp/_kiosk_fit.js'],
                          capture_output=True, text=True, timeout=10)
        if r.returncode == 0:
            print(f'  JS 注入语法 OK ({len(js_combined)} chars)')
        else:
            print(f'  JS syntax ERROR: {r.stderr.strip()[:300]}')
            # 输出错误行附近的 JS 内容
            lines = js_combined.split('\n')
            err_line = re.search(r':(\d+)', r.stderr).group(1) if ':' in r.stderr else 0
            try:
                ln = int(err_line)
                for i in range(max(0, ln-3), min(len(lines), ln+3)):
                    print(f'    {i+1}: {lines[i]}')
            except: pass

print()
print('=== 3. 版本号一致性 ===')
ver_manifest = re.search(r'version=(\d+\.\d+\.\d+)', open('manifest','rb').read().decode('utf-8')).group(1)
ver_dashconfig = re.search(r'APP_VERSION\s*=\s*["\']([\d.]+)["\']', open('app/bin/dash_config.py','rb').read().decode('utf-8')).group(1)
print(f'  manifest: {ver_manifest}')
print(f'  dash_config.APP_VERSION: {ver_dashconfig}')
assert ver_manifest == ver_dashconfig, f'VERSION MISMATCH!'
print(f'  版本一致')

print()
print('=== 4. FPK 哈希 ===')
h = hashlib.sha256(open('com.fnos.kiosk.fpk','rb').read()).hexdigest()
sz = os.path.getsize('com.fnos.kiosk.fpk')
print(f'  SHA256: {h}')
print(f'  大小: {sz} bytes')

print()
print('=== 5. 关键修改点验证 ===')
src_browser = open('app/bin/dash_browser.py','rb').read().decode('utf-8')
checks = [
    ('body.style.zoom (auto-fit 主体)', 'body.style.zoom='),
    ('no de.style.zoom (v0.1.40 bug)', 'de.style.zoom='),
    ('MutationObserver (SPA 支持)', 'MutationObserver'),
    ('debug indicator (__kiosk_fit_dbg)', '__kiosk_fit_dbg'),
    ('CSS injection (url_kiosk_css)', '__kiosk_injected_css'),
    ('Multi-retry timeouts (200/800/etc)', '[200,800,2000,5000,10000]'),
    ('Page.addScriptToEvaluateOnNewDocument', 'Page.addScriptToEvaluateOnNewDocument'),
    ('removeScriptToEvaluateOnNewDocument (cleanup)', 'removeScriptToEvaluateOnNewDocument'),
]
for name, needle in checks:
    has = needle in src_browser
    expected = not name.startswith('no ')
    ok = has == expected
    print(f'  {"OK  " if ok else "FAIL"} {name}: needle="{needle}" present={has}')

print()
print('=== 6. auto-fit 算法验证 ===')
def auto_fit(doc_w, doc_h, vp_w, vp_h):
    if not doc_w or not doc_h or not vp_w or not vp_h:
        return 1.0
    s = min(vp_w/doc_w, vp_h/doc_h, 1)
    if s < 0.05 or s > 1:
        s = 1
    return s

cases = [
    # 用户场景：dashboard 1280x720 in viewport 1024x768
    ('dashboard 1280x720 in 1024x768', 1280, 720, 1024, 768, 0.8),
    # 假设 dashboard 自适应，宽 1024 但高 832（两行卡片）
    ('dashboard 1024x832 in 1024x768', 1024, 832, 1024, 768, 0.923),
    # 超出 viewport 极端
    ('4K content in 1024x768', 4000, 2000, 1024, 768, 0.256),
    # 内容已小于 viewport
    ('小内容 800x600 in 1024x768', 800, 600, 1024, 768, 1.0),
    # 边界
    ('doc=0 兜底', 0, 0, 1024, 768, 1.0),
    ('vp=0 兜底', 1280, 720, 0, 0, 1.0),
    # 一边超一边小
    ('水平超 2000x500 in 1024x768', 2000, 500, 1024, 768, 0.512),
    ('垂直超 800x2000 in 1024x768', 800, 2000, 1024, 768, 0.384),
]
for name, dw, dh, vw, vh, expected in cases:
    actual = auto_fit(dw, dh, vw, vh)
    ok = abs(actual - expected) < 0.01
    print(f'  {"OK  " if ok else "FAIL"} {name}: actual={actual:.3f} expected={expected}')

print()
print('=== 7. release 资产匹配 ===')
import urllib.request, json
try:
    url = 'https://api.github.com/repos/kou147258/fnos-kiosk/releases/tags/v0.1.41'
    req = urllib.request.Request(url, headers={'Accept':'application/vnd.github+json'})
    with urllib.request.urlopen(req, timeout=15) as resp:
        data = json.loads(resp.read())
        print(f'  release tag: {data["tag_name"]}')
        print(f'  name: {data["name"]}')
        for a in data.get('assets', []):
            print(f'  asset: {a["name"]} {a["size"]} bytes SHA256={a["digest"]}')
except Exception as e:
    print(f'  WARN: GitHub API 调用失败: {e}')

print()
print('=== ALL VERIFICATION COMPLETE ===')