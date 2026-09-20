#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""fnOS 浏览器屏 —— FPK 离线打包工具。

fnpack 是 fnOS 私有 CLI（PyPI 上没有），pip 装不上。
fnOS 应用中心接收的 .fpk 本质上就是项目的 zip 归档（包含 manifest/cmd/app/...），
外加 install_callback 等可执行钩子。

本脚本：
  1. 校验 manifest 必须存在
  2. 把项目根目录打成 zip
  3. 重命名为 .fpk
  4. 给出本地安装命令
"""
import os
import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
APP_NAME = "com.fnos.kiosk"
OUT_DIR = ROOT / "dist"
OUT_FPK = OUT_DIR / f"{APP_NAME}-0.1.0.fpk"


def should_skip(path: Path) -> bool:
    """跳过不需要打进 FPK 的本地文件。"""
    rel = path.relative_to(ROOT)
    parts = rel.parts
    if any(p.startswith(".") and p != "." for p in parts):
        return True  # .git, .vscode
    if "__pycache__" in parts:
        return True
    if rel == Path("dist") or rel.parent == Path("dist"):
        return True
    if rel.suffix == ".pyc":
        return True
    return False


def main():
    # 1. 必备文件校验
    must_have = ["manifest", "cmd/main", "app/bin/dashboard.py",
                  "app/web/index.html", "config/privilege"]
    missing = [m for m in must_have if not (ROOT / m).exists()]
    if missing:
        print("[FAIL] 缺少必备文件：%s" % missing)
        sys.exit(1)

    # 2. 创建 dist 目录
    OUT_DIR.mkdir(exist_ok=True)

    # 3. 创建 zip（ZIP_DEFLATED 压缩）
    files_added = 0
    print("[PACK] %s -> %s" % (ROOT, OUT_FPK))
    with zipfile.ZipFile(OUT_FPK, "w", compression=zipfile.ZIP_DEFLATED,
                         compresslevel=9) as zf:
        for path in sorted(ROOT.rglob("*")):
            if not path.is_file():
                continue
            if should_skip(path):
                continue
            arc = path.relative_to(ROOT).as_posix()
            zf.write(path, arcname=arc)
            files_added += 1
            print("  + %s" % arc)

    size_kb = OUT_FPK.stat().st_size / 1024
    print("\n[OK] %s (%.1f KB, %d 个文件)" %
          (OUT_FPK, size_kb, files_added))
    print("")
    print("[INSTALL] 在 fnOS 上安装：")
    print("  1. 把 %s 拷到 NAS" % OUT_FPK.name)
    print("  2. 浏览器进 fnOS -> 应用中心 -> 右上「手动安装」 -> 选 .fpk")
    print("  3. 走安装向导即可")


if __name__ == "__main__":
    main()