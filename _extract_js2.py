#!/usr/bin/env python3
"""精确提取 dash_browser.py set_kiosk_css 中的 JS 字符串"""
import re, subprocess, os

src = open('app/bin/dash_browser.py','rb').read().decode('utf-8')

# 找 js_src = (...) 整段赋值
m = re.search(r'js_src = \((.*?)\)\s*\n\s*try:', src, re.DOTALL)
if not m:
    print('FAIL: js_src not found')
    raise SystemExit(1)

# 提取所有双引号字符串 + 变量插入（css_json）
js_raw = m.group(1)

# 找出所有 "..." 段并拼接（处理 css_json 变量插入）
out = []
i = 0
while i < len(js_raw):
    if js_raw[i] == '"':
        # 找匹配的 "
        j = i + 1
        while j < len(js_raw):
            if js_raw[j] == '\\':
                j += 2
                continue
            if js_raw[j] == '"':
                break
            j += 1
        out.append(js_raw[i+1:j].replace('\\n', '\n').replace('\\"', '"').replace('\\\\', '\\'))
        i = j + 1
    elif js_raw[i:i+8] == 'css_json':
        # 占位符 "..." + css_json + "..."
        # 简化：插入占位 JSON
        out.append('"<CSS>"')
        i += 8
        # 跳过 + 号和空格
        while i < len(js_raw) and js_raw[i] in ' +\t\n':
            i += 1
    else:
        i += 1

js_combined = ''.join(out)
# Wrap in function for proper IIFE parsing
js_full = '(function(){' + js_combined + '})()'

with open('/tmp/_kiosk_fit_check.js', 'w', encoding='utf-8') as f:
    f.write(js_full)

print(f'JS 总长: {len(js_full)} chars')
print(f'前 400:')
print(js_full[:400])
print()
print(f'后 400:')
print(js_full[-400:])

r = subprocess.run(['node', '--check', '/tmp/_kiosk_fit_check.js'],
                  capture_output=True, text=True, timeout=10)
print()
print('=== node --check ===')
if r.returncode == 0:
    print('PASS: JS 语法正确')
else:
    print('FAIL:', r.stderr.strip())
    lines = js_full.split('\n')
    err = re.search(r':(\d+)', r.stderr)
    if err:
        ln = int(err.group(1))
        for i in range(max(0, ln-2), min(len(lines), ln+3)):
            print(f'  {i+1}: {lines[i]}')