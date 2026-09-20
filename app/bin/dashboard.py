#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""fnOS 浏览器屏 —— 后端服务入口（纯 Python 标准库 + 可选 Pillow）。

实现思路沿用 fnos-dashboard：HTTP 拉 JSON 快照 → 显示器渲染器消费。
但「数据源」不是 /proc 而是 headless Chromium（CDP 协议），
由 fb_render.py 自行驱动；本进程只负责配置/页面列表与 HTTP API。

模块划分：
  dash_config  —— 配置读写与白名单校验
  dash_pages   —— 页面（URL / HTML 文件）解析与本地 HTML 渲染
  dash_browser —— Chromium 生命周期管理（被 fb_render 调用）
  dash_http    —— HTTP API 与静态页
"""

import argparse
import os
import signal
import sys
import threading
from http.server import ThreadingHTTPServer

import dash_config
import dash_http
import dash_pages


def main():
    here = os.path.dirname(os.path.abspath(__file__))
    ap = argparse.ArgumentParser(description="fnOS 浏览器屏后端")
    ap.add_argument("--host", default="0.0.0.0")
    ap.add_argument("--port", type=int,
                    default=int(os.environ.get("TRIM_SERVICE_PORT", "8200")))
    ap.add_argument("--web", default=os.path.normpath(os.path.join(here, "..", "web")))
    ap.add_argument("--config",
                    default=os.path.join(
                        os.environ.get("TRIM_PKGETC",
                                       os.path.normpath(os.path.join(here, "..", "etc"))),
                        "config.json"))
    ap.add_argument("--var",
                    default=os.environ.get("TRIM_PKGVAR",
                                           os.path.normpath(os.path.join(here, "..", "var"))))
    args = ap.parse_args()

    var_dir = args.var
    try:
        os.makedirs(var_dir, exist_ok=True)
    except OSError:
        pass

    cfg = dash_config.Config(args.config, var_dir)
    pages = dash_pages.PageStore(os.path.join(var_dir, "pages"))

    dash_http.Handler.web_root = args.web
    dash_http.Handler.config = cfg
    dash_http.Handler.pages = pages
    dash_http.Handler.var_dir = var_dir
    dash_http.Handler.etc_dir = os.path.dirname(cfg.path)
    dash_http.Handler.http_port = args.port

    server = ThreadingHTTPServer((args.host, args.port), dash_http.Handler)
    server.daemon_threads = True

    def _shutdown(_signum, _frame):
        threading.Thread(target=server.shutdown, daemon=True).start()
    signal.signal(signal.SIGTERM, _shutdown)
    signal.signal(signal.SIGINT, _shutdown)

    print("[fnos-kiosk] v%s listening on %s:%d, web=%s, config=%s"
          % (dash_config.APP_VERSION, args.host, args.port, args.web, cfg.path),
          flush=True)
    try:
        server.serve_forever(poll_interval=0.5)
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    sys.exit(main())