#!/bin/bash
# fnOS 浏览器屏 —�?构建与打包脚�?# 用法�?/build.sh
#       （fnpack 优先；不�?PATH 时用 tools/pack_fpk.py 兜底打包�?set -e
cd "$(dirname "$0")"

echo "[1/3] 生成应用图标..."
python3 tools/make_icons.py

echo "[2/3] 设置脚本执行权限..."
chmod +x build.sh cmd/* app/bin/*.py app/ui/index.cgi tools/*.py 2>/dev/null || true

if command -v fnpack >/dev/null 2>&1; then
    echo "[3/3] 使用 fnpack 打包..."
    fnpack build
    echo "完成：生�?com.fnos.kiosk.fpk 安装包�?
elif command -v python3 >/dev/null 2>&1; then
    echo "[3/3] fnpack 不在 PATH，使�?tools/pack_fpk.py 兜底（仅 ZIP 格式，fnOS 可能拒绝�?.."
    echo "      建议下载 fnpack: https://static2.fnnas.com/fnpack/fnpack-1.2.1-<os>-<arch>"
    python3 tools/pack_fpk.py
else
    echo "[3/3] fnpack �?python3 都不可用，请安装其一后重试："
    echo "      fnpack:    https://developer.fnnas.com/docs/cli/fnpack"
    echo "      python3:   apt install -y python3"
fi

echo ""
echo "本地预览（无需 fnOS）：python3 app/bin/dashboard.py --port 8280 --web app/web"
echo "设置页：http://127.0.0.1:8280/settings（仅限本机）"
