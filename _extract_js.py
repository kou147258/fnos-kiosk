#!/usr/bin/env python3
"""提取 dash_browser.py set_kiosk_css 中的 JS 注入并用 node --check 验证"""
import re, subprocess, tempfile, os

src = open('app/bin/dash_browser.py','rb').read().decode('utf-8')

# 找到 set_kiosk_css 整个函数
m = re.search(r'def set_kiosk_css\(self, css\):(.*?)def alive', src, re.DOTALL)
if not m:
    print('FAIL: set_kiosk_css function not found')
    raise SystemExit(1)

fn_body = m.group(1)

# 提取函数体内所有以 + 拼接的双引号字符串
# 匹配模式: "...\"" + "\n ...\""
# 简单做法：找从 " 到下一个 " 的所有内容
strs = re.findall(r'"((?:[^"\\]|\\.)*)"', fn_body)
print(f'找到 {len(strs)} 个字符串常量')

# 拼接所有看起来是 JS 代码的字符串（不是 css_json 那种）
js_parts = []
for s in strs:
    if any(t in s for t in ['(function(', 'documentElement', 'MutationObserver', 'addScriptToEvaluateOnNewDocument', '__kioskInject', '__kioskFit']):
        js_parts.append(s.replace('\\"', '"').replace('\\n', '\n').replace('\\', '\\'))

if not js_parts:
    print('FAIL: 没找到 JS 字符串片段')
    raise SystemExit(1)

# 组合 + 补全 function wrappers（js_parts 可能是拆分的 IIFE）
combined = '\n'.join(js_parts)
# 补上函数包装（如果被切了）
if not combined.lstrip().startswith('(function'):
    # 找 (function() { 开始
    i = combined.find('(function()')
    if i >= 0:
        combined = combined[i:]

# 写到文件并 node --check
tmpfile = os.path.join(tempfile.gettempdir(), '_kiosk_fit_check.js')
with open(tmpfile, 'w', encoding='utf-8') as f:
    f.write(combined)

print(f'JS 总长: {len(combined)} chars')
print(f'前 200 chars: {combined[:200]!r}')
print(f'后 240 chars: {combined[-240:]!r}')

r = subprocess.run(['node', '--check', tmpfile], capture_output=True, text=True, timeout=10)
print()
print('=== node --check 结果 ===')
if r.returncode == 0:
    print('PASS: JS 语法正确')
else:
    print('FAIL:', r.stderr.strip())
    lines = combined.split('\n')
    err = re.search(r':(\d+)', r.stderr)
    if err:
        ln = int(err.group(1))
        for i in range(max(0, ln-2), min(len(lines), ln+3)):
            print(f'  {i+1}: {lines[i]}')