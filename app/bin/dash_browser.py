#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""fnOS 浏览器屏 —— headless Chromium 驱动（纯标准库 WebSocket + CDP）。

不依赖 websocket-client / websocketpp 等第三方库：直接按 RFC 6455 手写
WebSocket 帧的拆装（client→server 必须 mask，server→client 不 mask）。
这样和 fnos-dashboard 的 zero-dep 哲学保持一致。

使用流程：
    b = Browser(window=(W, H), port=9222)
    b.start()                  # spawn chromium --headless=new --remote-debugging-port=9222 ...
    b.connect()                # GET /json/version → 拿到 webSocketDebuggerUrl
    b.navigate(url, wait="load")
    png_b64 = b.screenshot()   # Page.captureScreenshot → base64 PNG
    b.close()

注意：本模块只关心 Chromium 子进程 + 一条 WebSocket；fb_render 自己负责
截图解码 / 缩放 / 写 fb0。
"""

import base64
import hashlib
import json
import os
import secrets
import shutil
import socket
import struct
import subprocess
import sys
import threading
import time
from urllib.request import urlopen


# ---- WebSocket frame 编解码（RFC 6455）----
WS_GUID = b"258EAFA5-E914-47DA-95CA-C5AB0DC85B11"
WS_OP_CONT = 0x0
WS_OP_TEXT = 0x1
WS_OP_BIN = 0x2
WS_OP_CLOSE = 0x8
WS_OP_PING = 0x9
WS_OP_PONG = 0xA


def _ws_send_mask():
    # 4 字节 mask key
    return secrets.token_bytes(4)


def _ws_frame(payload, opcode=WS_OP_BIN):
    """客户端 frame（必须 masked）。"""
    if isinstance(payload, str):
        payload = payload.encode("utf-8")
    mask = _ws_send_mask()
    masked = bytes(b ^ mask[i % 4] for i, b in enumerate(payload))
    header = bytearray()
    header.append(0x80 | (opcode & 0x0F))  # FIN=1
    ln = len(payload)
    if ln < 126:
        header.append(0x80 | ln)            # MASK=1
    elif ln < (1 << 16):
        header.append(0x80 | 126)
        header.extend(struct.pack(">H", ln))
    else:
        header.append(0x80 | 127)
        header.extend(struct.pack(">Q", ln))
    header.extend(mask)
    header.extend(masked)
    return bytes(header)


def _ws_parse_header(buf):
    """从累计 buffer 里尝试解析一个 server→client frame header，返回 (header_len, payload_len, opcode)。"""
    if len(buf) < 2:
        return None
    b1, b2 = buf[0], buf[1]
    opcode = b1 & 0x0F
    masked = b2 & 0x80
    ln = b2 & 0x7F
    if ln < 126:
        header_len = 2
        payload_len = ln
    elif ln == 126:
        if len(buf) < 4:
            return None
        payload_len = struct.unpack(">H", buf[2:4])[0]
        header_len = 4
    else:
        if len(buf) < 10:
            return None
        payload_len = struct.unpack(">Q", buf[2:10])[0]
        header_len = 10
    if masked:
        if len(buf) < header_len + 4:
            return None
        header_len += 4
    return header_len, payload_len, opcode


class WSError(Exception):
    pass


class WSClient:
    """最小 WebSocket 客户端（仅做 RFC 6455 必需的子集）。"""

    def __init__(self, sock):
        self.s = sock
        self.s.settimeout(30)
        self._buf = bytearray()
        self._lock = threading.Lock()

    @classmethod
    def connect(cls, host, port, path):
        """完成 HTTP Upgrade 握手，返回 WSClient。"""
        sock = socket.create_connection((host, port), timeout=10)
        key_bytes = base64.b64encode(secrets.token_bytes(16))
        key_str = key_bytes.decode("ascii")
        req = (
            "GET %s HTTP/1.1\r\n"
            "Host: %s:%d\r\n"
            "Upgrade: websocket\r\n"
            "Connection: Upgrade\r\n"
            "Sec-WebSocket-Key: %s\r\n"
            "Sec-WebSocket-Version: 13\r\n"
            "\r\n"
        ) % (path, host, port, key_str)
        sock.sendall(req.encode("ascii"))
        # 读响应头
        sock.settimeout(10)
        data = b""
        while b"\r\n\r\n" not in data:
            chunk = sock.recv(4096)
            if not chunk:
                raise WSError("WebSocket 握手失败（连接关闭）")
            data += chunk
            if len(data) > 65536:
                raise WSError("WebSocket 握手响应过大")
        head, rest = data.split(b"\r\n\r\n", 1)
        status_line = head.split(b"\r\n", 1)[0].decode("ascii", "replace")
        if "101" not in status_line:
            raise WSError("WebSocket 握手失败：%s" % status_line)
        # 校验 Sec-WebSocket-Accept
        accept = None
        for line in head.split(b"\r\n")[1:]:
            k, _, v = line.partition(b":")
            if k.strip().lower() == b"sec-websocket-accept":
                accept = v.strip()
                break
        # 关键修复：key 已是 bytes，直接相加；str + bytes 会报 TypeError
        expect = hashlib.sha1(key_bytes + WS_GUID).digest()
        if accept != base64.b64encode(expect):
            raise WSError("Sec-WebSocket-Accept 不匹配")
        cli = cls(sock)
        if rest:
            cli._buf.extend(rest)
        return cli

    def send_text(self, text):
        with self._lock:
            self.s.sendall(_ws_frame(text, WS_OP_TEXT))

    def _recv_exact(self, n):
        while len(self._buf) < n:
            chunk = self.s.recv(65536)
            if not chunk:
                raise WSError("WebSocket 连接关闭")
            self._buf.extend(chunk)
        out = bytes(self._buf[:n])
        del self._buf[:n]
        return out

    def _recv_frame(self):
        # 读 header
        while True:
            hdr = _ws_parse_header(bytes(self._buf))
            if hdr is not None:
                break
            chunk = self.s.recv(4096)
            if not chunk:
                raise WSError("WebSocket 连接关闭（header）")
            self._buf.extend(chunk)
        header_len, payload_len, opcode = hdr
        # header 可能还在 buffer 边缘：累计到足够
        while len(self._buf) < header_len + payload_len:
            chunk = self.s.recv(65536)
            if not chunk:
                raise WSError("WebSocket 连接关闭（payload）")
            self._buf.extend(chunk)
        payload = bytes(self._buf[header_len:header_len + payload_len])
        del self._buf[:header_len + payload_len]
        # 控制帧：pong/close 直接忽略（足够简单；我们不开 keepalive）
        if opcode == WS_OP_CLOSE:
            raise WSError("WebSocket 服务端关闭")
        if opcode in (WS_OP_PING, WS_OP_PONG):
            return self._recv_frame()
        return payload

    def recv_text(self):
        return self._recv_frame().decode("utf-8", "replace")

    def close(self):
        try:
            self.s.sendall(_ws_frame(b"", WS_OP_CLOSE))
        except OSError:
            pass
        try:
            self.s.close()
        except OSError:
            pass


def find_chromium(custom_path=""):
    """按 custom_path → 常见安装路径 → PATH 顺序查找 Chromium。
    返回值：（exe_path, info_dict）；找不到时 exe_path 为空，info_dict 含诊断信息。"""
    info = {"checked": [], "found": "", "errors": []}
    candidates = []
    if custom_path:
        candidates.append(custom_path)
    candidates += [
        "/usr/bin/chromium",
        "/usr/bin/chromium-browser",
        "/usr/bin/google-chrome",
        "/snap/bin/chromium",
        "/usr/bin/chromium-snapper",
    ]
    which = shutil.which("chromium") or shutil.which("chromium-browser")
    if which:
        candidates.append(which)
    info["checked"] = candidates
    for c in candidates:
        if not os.path.exists(c):
            info["errors"].append("%s: 不存在" % c)
            continue
        if not os.path.isfile(c):
            info["errors"].append("%s: 不是文件" % c)
            continue
        if not os.access(c, os.X_OK):
            info["errors"].append("%s: 当前进程无执行权限" % c)
            continue
        info["found"] = c
        return c, info
    return "", info


def find_chromium_simple(custom_path=""):
    """只返回路径字符串的便捷包装（向后兼容）。"""
    path, _ = find_chromium(custom_path)
    return path


class Browser:
    """headless Chromium 生命周期管理 + 一条 CDP WebSocket。"""

    def __init__(self, window=(1920, 1080), port=9222,
                 chromium_path="", scale=1.0, timeout=30, hide_cursor=True,
                 user_data_dir=""):
        self.window = tuple(int(x) for x in window)
        self.port = int(port)
        self.chromium_path = chromium_path
        self.scale = float(scale)
        self.timeout = float(timeout)
        self.hide_cursor = bool(hide_cursor)
        # 持久 profile：cookies/localStorage/IndexedDB/Service Worker 都留存在这里。
        # 留空则用 /tmp 临时目录，每次重启登录态丢失（不推荐）。
        self.user_data_dir = user_data_dir or ""
        self.proc = None
        self.ws = None
        self._msg_id = 0
        self._pending = {}            # id -> threading.Event, result
        self._events = []             # 累积 CDP 事件（Page.loadEventFired 等）
        self._lock = threading.Lock()
        self._reader_th = None
        self._stderr_tail = []        # 简易诊断
        self._ws_url = ""

    # ---- 启动 ----
    def start(self, log_path=None):
        exe, finfo = find_chromium(self.chromium_path)
        if not exe:
            raise RuntimeError(
                "未找到 chromium/chromium-browser；"
                "检查路径：" + ", ".join(finfo["checked"]) + "；"
                "错误：" + " | ".join(finfo["errors"][:5]) +
                "。请 sudo apt install -y chromium 或在设置中指定 browser_path")
        args = [
            exe,
            "--headless=new",
            "--no-sandbox",
            "--disable-gpu",
            "--disable-dev-shm-usage",
            "--hide-scrollbars",
            "--disable-features=Translate,BackForwardCache",
            "--mute-audio",
            "--autoplay-policy=no-user-gesture-required",  # 让视频/音频无需用户手势自动播放
            "--disable-extensions",
            "--no-first-run",
            "--no-default-browser-check",
            "--disable-background-networking",
            "--disable-component-update",
            "--disable-default-apps",
            "--metrics-recording-only",
        ]
        if self.hide_cursor:
            args.append("--hide-cursor")
        if self.scale != 1.0:
            args.append("--force-device-scale-factor=%.3f" % self.scale)
        if self.user_data_dir:
            args.append("--user-data-dir=%s" % self.user_data_dir)
            # 让密码管理器、autofill 等都持久化（即便没显式调用）
            args.append("--enable-features=PasswordManagerEnableFaviconService")
        args += [
            "--window-size=%d,%d" % self.window,
            "--remote-debugging-port=%d" % self.port,
            "--remote-debugging-address=127.0.0.1",
            "about:blank",
        ]
        log_path_actual = log_path
        if log_path:
            try:
                log = open(log_path, "ab")
            except OSError:
                # fb_chromium.log 打不开时退化到 fb.log
                try:
                    alt = os.path.join(os.path.dirname(log_path) or ".",
                                       "fb.log")
                    log = open(alt, "ab")
                    log_path_actual = alt
                except OSError:
                    log = subprocess.DEVNULL
        else:
            log = subprocess.DEVNULL
        try:
            self.proc = subprocess.Popen(
                args, stdin=subprocess.DEVNULL,
                stdout=log, stderr=log,
                start_new_session=True)
        finally:
            if log is not subprocess.DEVNULL:
                try:
                    log.close()
                except OSError:
                    pass
        # 等待 /json/version 可访问
        deadline = time.time() + 20
        while time.time() < deadline:
            try:
                urlopen("http://127.0.0.1:%d/json/version" % self.port, timeout=2).read()
                return
            except Exception:
                if self.proc.poll() is not None:
                    raise RuntimeError("Chromium 启动失败（exit=%s）" % self.proc.returncode)
                time.sleep(0.3)
        self.close()
        raise RuntimeError("Chromium 启动超时（20s 内 /json/version 不可达）")

    # ---- WebSocket ----
    def connect(self, retries=5):
        """连接到 *page target* 的 WebSocket（不是 browser endpoint）。

        /json/version 返回的是 browser-level endpoint（无 Page.* 域）；
        /json 返回 target 列表，要挑 type=='page' 的来连，
        Page.enable / Page.navigate 等方法才可用。
        """
        last = None
        for _ in range(retries):
            try:
                resp = urlopen("http://127.0.0.1:%d/json" % self.port,
                               timeout=5).read()
                targets = json.loads(resp.decode("utf-8", "replace"))
                if not isinstance(targets, list) or not targets:
                    raise RuntimeError("CDP /json 返回空列表")
                # 优先选 type=='page' 的；about:blank 那条最稳
                page_target = None
                for t in targets:
                    if t.get("type") == "page":
                        page_target = t
                        break
                if page_target is None:
                    page_target = targets[0]
                self._ws_url = page_target.get("webSocketDebuggerUrl", "")
                if not self._ws_url:
                    raise RuntimeError("CDP page target 缺少 webSocketDebuggerUrl")
                if self._ws_url.startswith("ws://"):
                    rest = self._ws_url[5:]
                elif self._ws_url.startswith("ws+unix://"):
                    raise RuntimeError("暂不支持 unix socket transport")
                else:
                    raise RuntimeError("未知的 WebSocket URL 协议: %s"
                                       % self._ws_url[:16])
                host_port, _, path = rest.partition("/")
                host, _, port = host_port.partition(":")
                self.ws = WSClient.connect(host, int(port or 9222),
                                           "/" + path)
                self._reader_th = threading.Thread(target=self._reader,
                                                   daemon=True)
                self._reader_th.start()
                # 启用 Page 域（page target 上 Page.* 才存在）
                self.call("Page.enable", timeout=5)
                return
            except Exception as e:
                last = e
                time.sleep(0.5)
        raise RuntimeError("连接 Chromium CDP 失败：%r" % last)

    def close(self):
        if self.ws is not None:
            try:
                self.ws.close()
            except Exception:
                pass
            self.ws = None
        if self.proc is not None:
            try:
                if self.proc.poll() is None:
                    self.proc.terminate()
                    try:
                        self.proc.wait(timeout=3)
                    except subprocess.TimeoutExpired:
                        self.proc.kill()
            except Exception:
                pass
            self.proc = None

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
                    # 事件
                    with self._lock:
                        self._events.append(obj)
                        if len(self._events) > 256:
                            del self._events[:128]
        except Exception:
            self.ws = None

    def call(self, method, params=None, timeout=30):
        with self._lock:
            self._msg_id += 1
            mid = self._msg_id
            ev = threading.Event()
            result = []
            self._pending[mid] = (ev, result)
        payload = {"id": mid, "method": method}
        if params:
            payload["params"] = params
        self.ws.send_text(json.dumps(payload, ensure_ascii=False))
        if not ev.wait(timeout=timeout):
            with self._lock:
                self._pending.pop(mid, None)
            raise RuntimeError("CDP 调用超时：%s" % method)
        kind, value = result[0]
        if kind == "err":
            raise RuntimeError("CDP 调用失败 %s: %s" % (method, value))
        return value

    def drain_events(self, method=None, timeout=0.3):
        """取走符合 method 的事件；其他放回队尾（粗略实现但够用）。"""
        out, keep = [], []
        with self._lock:
            evs = self._events
            self._events = []
        for e in evs:
            if method is None or e.get("method") == method:
                out.append(e)
            else:
                keep.append(e)
        with self._lock:
            self._events.extend(keep)
        return out

    def wait_event(self, method, timeout=20):
        """阻塞等到指定 method 的事件出现。"""
        deadline = time.time() + timeout
        while time.time() < deadline:
            evs = self.drain_events(method=method)
            if evs:
                return evs[0]
            time.sleep(0.05)
        raise RuntimeError("等待 CDP 事件超时：%s" % method)

    # ---- 高层动作 ----
    def navigate(self, url, wait="load", timeout=None):
        """Page.navigate + 等待 Page.loadEventFired（或 domContentEventFired）。"""
        timeout = timeout or self.timeout
        # 先丢掉积压事件（避免读到上一次的 load）
        with self._lock:
            self._events = []
        try:
            self.call("Page.navigate", {"url": url}, timeout=10)
        except RuntimeError as e:
            # 某些 about:blank 导航会立刻报 "Cannot navigate to a URL"
            # 这是已知行为，吞掉即可
            msg = str(e)
            if "Cannot navigate" in msg or "-32000" in msg:
                pass
            else:
                raise
        if wait == "dom":
            self.wait_event("Page.domContentEventFired", timeout=timeout)
        else:
            self.wait_event("Page.loadEventFired", timeout=timeout)

    def screenshot(self, format="png"):
        """返回 base64 字符串。"""
        r = self.call("Page.captureScreenshot",
                      {"format": format, "captureBeyondViewport": False},
                      timeout=15)
        return r.get("data", "")

    def reload(self, timeout=None):
        timeout = timeout or self.timeout
        with self._lock:
            self._events = []
        self.call("Page.reload", {"ignoreCache": True}, timeout=10)
        self.wait_event("Page.loadEventFired", timeout=timeout)

    def alive(self):
        if self.proc is None or self.proc.poll() is not None:
            return False
        return self.ws is not None

    def status(self):
        """给设置页看的实时状态。"""
        if self.proc is None:
            return {"running": False, "exit_code": None, "ws_url": self._ws_url}
        rc = self.proc.poll()
        return {
            "running": rc is None,
            "exit_code": rc,
            "pid": self.proc.pid,
            "ws_url": self._ws_url,
            "window": list(self.window),
        }