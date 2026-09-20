#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""fnOS 浏览器屏 —— 独立 CDP 客户端（设置页「远程控制」用）。

目的：让 dashboard 进程能直接通过 CDP 操作 kiosk 的 headless Chromium，
这样设置页里就能嵌入「实时截图 + 点击/键盘输入转发」功能，
不需要 chrome://inspect 也不需要 SSH 隧道。

与 dash_browser.py 的区别：
  - dash_browser.Browser 是 fb_render 用的——它**独占** Chromium
    做截图渲染，不能再分一个客户端给远程控制
  - 本模块是 dashboard 用的**独立** CDP 客户端——和 fb_render 共享
    Chromium 但只做轻量操作（screenshot / click / type / navigate）

线程模型：
  - connect() 后启动 reader 线程收事件
  - call() 同步等回应（带 timeout）
  - close() 关 ws
"""

import base64
import hashlib
import json
import os
import secrets
import socket
import struct
import threading
import time
from urllib.request import urlopen

# 复用 dash_browser 的 RFC 6455 实现（零依赖复用）
from dash_browser import WSClient, WS_GUID


class CDPProxy:
    """独立的 CDP 客户端，连接到 kiosk Chromium 的 page target。"""

    def __init__(self, port=10303):
        self.port = int(port)
        self.ws = None
        self._msg_id = 0
        self._pending = {}
        self._events = []
        self._lock = threading.Lock()
        self._reader_th = None
        self._ws_url = ""
        self._connected = False
        self._connect_lock = threading.Lock()

    # ---------- 连接管理 ----------
    def _connect_once(self, timeout=10):
        """单次连接尝试（不重试）。"""
        try:
            resp = urlopen("http://127.0.0.1:%d/json" % self.port,
                           timeout=timeout).read()
            targets = json.loads(resp.decode("utf-8", "replace"))
        except Exception as e:
            raise RuntimeError("连不上 Chromium（:json 失败）：%r" % e)
        if not isinstance(targets, list) or not targets:
            raise RuntimeError("CDP /json 返回空（Chromium 还没就绪）")
        # 挑 type=='page'
        page = None
        for t in targets:
            if t.get("type") == "page":
                page = t
                break
        if page is None:
            page = targets[0]
        ws_url = page.get("webSocketDebuggerUrl", "")
        if not ws_url:
            raise RuntimeError("page target 缺 webSocketDebuggerUrl")
        if not ws_url.startswith("ws://"):
            raise RuntimeError("不支持的 ws 协议：%s" % ws_url[:16])
        rest = ws_url[5:]
        host_port, _, path = rest.partition("/")
        host, _, port = host_port.partition(":")
        self.ws = WSClient.connect(host, int(port or 9222), "/" + path)
        self._ws_url = ws_url
        self._reader_th = threading.Thread(target=self._reader, daemon=True)
        self._reader_th.start()
        # 启用 Page / Input / Runtime 域
        self.call("Page.enable", timeout=5)
        self.call("Input.setIgnoreInputEvents", params={"w": True},
                  timeout=5)  # CDP 自动忽略系统级按键
        self._connected = True

    def connect(self, retries=3):
        """带重试的连接。"""
        with self._connect_lock:
            for i in range(retries):
                try:
                    self._connect_once()
                    return
                except Exception as e:
                    if i == retries - 1:
                        self._connected = False
                        raise
                    time.sleep(1)

    def close(self):
        self._connected = False
        if self.ws is not None:
            try:
                self.ws.close()
            except Exception:
                pass
            self.ws = None

    def _ensure_connected(self):
        """调用前确保已连接；断线自动重连。"""
        if not self._connected:
            self.connect()
        else:
            # ws 死了？检查 reader 状态
            if self.ws is None:
                self._connected = False
                self.connect()

    # ---------- 低层 RPC ----------
    def _reader(self):
        try:
            while self.ws is not None:
                msg = self.ws.recv_text()
                try:
                    obj = json.loads(msg)
                except ValueError:
                    continue
                if "id" in obj:
                    ev, result = self._pending.pop(obj["id"], (None, None))
                    if ev is not None:
                        if "error" in obj:
                            result.append(("err", obj["error"]))
                        else:
                            result.append(("ok", obj.get("result")))
                        ev.set()
                else:
                    with self._lock:
                        self._events.append(obj)
                        if len(self._events) > 64:
                            del self._events[:32]
        except Exception:
            self.ws = None
            self._connected = False

    def call(self, method, params=None, timeout=15):
        """同步 CDP 调用。"""
        self._ensure_connected()
        with self._lock:
            self._msg_id += 1
            mid = self._msg_id
            ev = threading.Event()
            result = []
            self._pending[mid] = (ev, result)
        payload = {"id": mid, "method": method}
        if params:
            payload["params"] = params
        try:
            self.ws.send_text(json.dumps(payload, ensure_ascii=False))
        except Exception:
            self._connected = False
            raise
        if not ev.wait(timeout=timeout):
            with self._lock:
                self._pending.pop(mid, None)
            raise RuntimeError("CDP 超时：%s" % method)
        kind, value = result[0]
        if kind == "err":
            raise RuntimeError("CDP 错误 %s: %s" % (method, value))
        return value

    # ---------- 高层动作 ----------
    def screenshot(self, fmt="png", quality=None):
        """返回 base64 PNG / JPEG 字符串。"""
        params = {"format": fmt}
        if quality is not None:
            params["quality"] = quality
        r = self.call("Page.captureScreenshot", params, timeout=15)
        return r.get("data", "")

    def navigate(self, url, wait="load", timeout=30):
        """Page.navigate + 等 Page.loadEventFired。"""
        with self._lock:
            self._events = []
        self.call("Page.navigate", {"url": url}, timeout=10)
        # 等 load
        deadline = time.time() + timeout
        while time.time() < deadline:
            evs = self._drain_events("Page.loadEventFired")
            if evs:
                return
            time.sleep(0.1)
        raise RuntimeError("导航超时：%s" % url)

    def _drain_events(self, method):
        out, keep = [], []
        with self._lock:
            evs = self._events
            self._events = []
        for e in evs:
            if e.get("method") == method:
                out.append(e)
            else:
                keep.append(e)
        with self._lock:
            self._events.extend(keep)
        return out

    def click(self, x, y, button="left", click_count=1):
        """在 Chromium 视口坐标 (x, y) 处点击。"""
        for ev_type in ("mousePressed", "mouseReleased"):
            self.call("Input.dispatchMouseEvent", {
                "type": ev_type,
                "x": float(x), "y": float(y),
                "button": button,
                "clickCount": click_count,
            }, timeout=5)

    def mouse_move(self, x, y):
        self.call("Input.dispatchMouseEvent", {
            "type": "mouseMoved",
            "x": float(x), "y": float(y),
        }, timeout=5)

    def scroll(self, x, y, delta_x=0, delta_y=0):
        """滚轮事件。"""
        self.call("Input.dispatchMouseEvent", {
            "type": "mouseWheel",
            "x": float(x), "y": float(y),
            "deltaX": float(delta_x), "deltaY": float(delta_y),
        }, timeout=5)

    def type_text(self, text):
        """逐字符输入（用 char 事件处理 IME 输入）。"""
        if not text:
            return
        # 整体作为 insertText（最快也最准）
        self.call("Input.insertText", {"text": text}, timeout=5)

    def key_press(self, key, code="", modifiers=0):
        """按特殊键（Enter / Tab / Esc / Backspace / 方向键等）。
        key:  按键名（'Enter' / 'Tab' / 'Escape' / 'Backspace' / 'ArrowLeft' 等）
        code: 物理键码（'Enter' / 'Tab' 等，可选）
        modifiers: 1=Alt 2=Ctrl 4=Meta 8=Shift，可组合
        """
        params = {
            "type": "keyDown",
            "key": key,
            "code": code or key,
            "modifiers": int(modifiers),
            "windowsVirtualKeyCode": _KEY_TO_VK.get(key, 0),
        }
        self.call("Input.dispatchKeyEvent", params, timeout=5)
        params["type"] = "keyUp"
        self.call("Input.dispatchKeyEvent", params, timeout=5)

    def eval_js(self, expression, return_by_value=True):
        """执行 JS 表达式并返回值。"""
        r = self.call("Runtime.evaluate", {
            "expression": expression,
            "returnByValue": bool(return_by_value),
            "awaitPromise": True,
        }, timeout=10)
        if "exceptionDetails" in r:
            raise RuntimeError("JS 异常：" + str(
                r["exceptionDetails"].get("text", "?")))
        return r.get("result", {}).get("value")

    def get_url(self):
        """返回当前 page URL。"""
        try:
            return self.eval_js("location.href", return_by_value=True)
        except Exception:
            return ""

    def get_title(self):
        try:
            return self.eval_js("document.title", return_by_value=True)
        except Exception:
            return ""


# 常用特殊键的 Windows Virtual Key Code
_KEY_TO_VK = {
    "Enter": 13,
    "Tab": 9,
    "Escape": 27,
    "Backspace": 8,
    "Delete": 46,
    "ArrowLeft": 37,
    "ArrowUp": 38,
    "ArrowRight": 39,
    "ArrowDown": 40,
    "Home": 36,
    "End": 35,
    "PageUp": 33,
    "PageDown": 34,
    "Space": 32,
    "F1": 112, "F2": 113, "F3": 114, "F4": 115,
    "F5": 116, "F6": 117, "F7": 118, "F8": 119,
    "F9": 120, "F10": 121, "F11": 122, "F12": 123,
}


def _self_check():
    """开发自检：检查 ws 接 chromium + 一张截图。"""
    p = CDPProxy(port=10303)
    p.connect()
    print("URL:", p.get_url())
    print("title:", p.get_title())
    b64 = p.screenshot()
    print("screenshot bytes (base64):", len(b64))
    p.close()


if __name__ == "__main__":
    _self_check()