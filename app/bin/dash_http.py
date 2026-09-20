#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""fnOS 浏览器屏 —— HTTP 层（API + 静态页 + framebuffer 重启/预览）。

访问模型沿用 fnos-dashboard：
  - 设置页与全部管理接口仅限本机 127.0.0.1
  - 局域网直连仅提供只读面板 + 状态接口
  - 配置更新仅接受白名单字段
"""

import json
import os
import signal
import subprocess
import sys
import time
from http.server import BaseHTTPRequestHandler

import dash_pages
from dash_config import APP_VERSION

MIME = {
    ".html": "text/html; charset=utf-8",
    ".css": "text/css; charset=utf-8",
    ".js": "application/javascript; charset=utf-8",
    ".json": "application/json; charset=utf-8",
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".svg": "image/svg+xml",
    ".ico": "image/x-icon",
    ".woff2": "font/woff2",
}


def fb_raw_read():
    """读取 /dev/fb0 当前帧，返回 (w, h, bgra, stride)。"""
    base = "/sys/class/graphics/fb0"
    vs = open(os.path.join(base, "virtual_size")).read().strip()
    w, h = (int(x) for x in vs.split(",")[:2])
    bpp = int(open(os.path.join(base, "bits_per_pixel")).read().strip())
    if bpp != 32:
        raise RuntimeError("仅支持 32bpp 帧缓冲，当前 %dbpp" % bpp)
    stride_file = os.path.join(base, "stride")
    stride = max(w * 4,
                 int(open(stride_file).read().strip())
                 if os.path.exists(stride_file) else w * 4)
    import mmap
    fd = os.open("/dev/fb0", os.O_RDONLY)
    try:
        mm = mmap.mmap(fd, stride * h, access=mmap.ACCESS_READ)
        raw = mm[:(h - 1) * stride + w * 4]
        mm.close()
    finally:
        os.close(fd)
    return w, h, raw, stride


def bgra_to_png(w, h, bgra, stride):
    try:
        from PIL import Image
        import io as _io
    except ImportError:
        Image = None
    if Image is not None:
        import io as _io
        packed = bytearray(w * h * 4)
        for y in range(h):
            packed[y * w * 4:(y + 1) * w * 4] = bgra[y * stride:y * stride + w * 4]
        img = Image.frombytes("RGBA", (w, h), bytes(packed), "raw", "BGRA")
        out = _io.BytesIO()
        img.convert("RGB").save(out, "PNG")
        return out.getvalue()
    import struct
    import zlib

    def chunk(typ, data):
        return (struct.pack(">I", len(data)) + typ + data
                + struct.pack(">I", zlib.crc32(typ + data) & 0xFFFFFFFF))

    ihdr = struct.pack(">IIBBBBB", w, h, 8, 2, 0, 0, 0)
    rows = bytearray()
    for y in range(h):
        row = bgra[y * stride: y * stride + w * 4]
        rgb = bytearray(w * 3)
        rgb[0::3] = row[2::4]
        rgb[1::3] = row[1::4]
        rgb[2::3] = row[0::4]
        rows += b"\x00" + rgb
    idat = zlib.compress(bytes(rows), 6)
    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", ihdr)
            + chunk(b"IDAT", idat) + chunk(b"IEND", b""))


def fb_restart_needed(prev, cur):
    """仅显示器进程级配置变化才重启渲染进程；其余（模组、主题、强调色等）均热加载。"""
    return any(prev.get(k) != cur.get(k)
               for k in ("fb_enabled", "fb_rotate", "screen_inches",
                         "browser_path", "browser_window", "browser_scale",
                         "browser_timeout", "hide_cursor"))


class Handler(BaseHTTPRequestHandler):
    server_version = "fnos-kiosk/" + APP_VERSION
    protocol_version = "HTTP/1.1"

    # 由 main() 注入
    web_root = "."
    config = None
    pages = None
    var_dir = "."
    etc_dir = "."
    http_port = 0

    def log_message(self, fmt, *args):
        pass

    def _is_trusted(self):
        return self.client_address[0] in ("127.0.0.1", "::1")

    def _send(self, code, body, ctype="application/json; charset=utf-8"):
        if isinstance(body, (dict, list)):
            body = json.dumps(body, ensure_ascii=False).encode("utf-8")
        elif isinstance(body, str):
            body = body.encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        try:
            self.wfile.write(body)
        except (BrokenPipeError, ConnectionResetError):
            pass

    def _send_json(self, code, obj):
        self._send(code, obj)

    def _deny_local_only(self):
        self._send_json(403, {"ok": False,
                              "error": "设置页与管理接口仅限本机访问"
                                       "（请通过飞牛桌面应用入口访问）"})

    def _read_body(self, limit=8 * 1024 * 1024):
        try:
            length = int(self.headers.get("Content-Length", 0))
        except ValueError:
            length = 0
        if length <= 0 or length > limit:
            return None
        return self.rfile.read(length)

    def _read_json(self, limit=65536):
        body = self._read_body(20 * 1024 * 1024 if limit is None else limit)
        if body is None:
            return None
        try:
            obj = json.loads(body.decode("utf-8"))
        except (ValueError, UnicodeDecodeError):
            return None
        return obj if isinstance(obj, dict) else None

    def _static_path(self, rel):
        root = os.path.realpath(self.web_root)
        full = os.path.realpath(os.path.join(root, rel.lstrip("/")))
        if full != root and not full.startswith(root + os.sep):
            return None
        if os.path.isdir(full):
            full = os.path.join(full, "index.html")
        if os.path.isfile(full):
            return full
        return None

    def _serve_static(self, rel):
        full = self._static_path(rel)
        if full is None:
            self._send_json(404, {"ok": False, "error": "Not Found"})
            return
        ext = os.path.splitext(full)[1].lower()
        ctype = MIME.get(ext, "application/octet-stream")
        try:
            with open(full, "rb") as f:
                body = f.read()
        except OSError:
            self._send_json(404, {"ok": False, "error": "Not Found"})
            return
        self._send(200, body, ctype=ctype)

    # ---- fb 渲染进程管理 ----
    def _fb_restart(self):
        pid_file = os.path.join(self.var_dir, "fb.pid")

        def _scan_renderers():
            found = []
            me = os.getpid()
            try:
                names = os.listdir("/proc")
            except OSError:
                return found
            for name in names:
                if not name.isdigit() or int(name) == me:
                    continue
                try:
                    with open("/proc/%s/cmdline" % name, "rb") as f:
                        cmd = f.read().replace(b"\x00", b" ").decode(
                            "utf-8", "replace")
                except OSError:
                    continue
                if "fb_render.py" in cmd:
                    found.append(int(name))
            return found

        def _log(msg):
            try:
                with open(os.path.join(self.var_dir, "fb.log"), "a",
                          encoding="utf-8") as f:
                    f.write("[backend %s] %s\n"
                            % (time.strftime("%m-%d %H:%M:%S"), msg))
            except OSError:
                pass

        old_pids = _scan_renderers()
        for pid in old_pids:
            try:
                os.kill(pid, signal.SIGTERM)
            except OSError:
                pass
        deadline = time.time() + 2
        while time.time() < deadline:
            try:
                os.waitpid(-1, os.WNOHANG)
            except (ChildProcessError, OSError):
                pass
            if not _scan_renderers():
                break
            time.sleep(0.1)
        for pid in _scan_renderers():
            try:
                os.kill(pid, signal.SIGKILL)
            except OSError:
                pass
        try:
            os.unlink(pid_file)
        except OSError:
            pass
        if old_pids:
            _log("restart: 已终止旧渲染进程 %s" % old_pids)

        cfg = self.config.get()
        if not cfg.get("fb_enabled") or not os.path.exists("/dev/fb0"):
            _log("restart: 未拉起（fb_enabled=%s, /dev/fb0=%s）"
                 % (cfg.get("fb_enabled"), os.path.exists("/dev/fb0")))
            return
        fb_bin = os.path.join(
            os.path.dirname(os.path.abspath(__file__)), "fb_render.py")
        if not os.path.isfile(fb_bin):
            _log("restart: 未拉起（缺少 %s）" % fb_bin)
            return
        port = self.http_port
        log_path = os.path.join(self.var_dir, "fb.log")
        try:
            log = open(log_path, "ab")
            # CDP 端口优先从环境变量 KIOSK_CDP_PORT 取，否则用 service_port + 1023
            # （service_port=8280 → CDP=10303；service_port=9500 → CDP=10523）。
            # 这是为了让 service_port 改了之后 CDP 端口自动跟着变。
            try:
                cdp_port = int(os.environ.get("KIOSK_CDP_PORT") or (port + 1023))
            except (TypeError, ValueError):
                cdp_port = port + 1023
            proc = subprocess.Popen(
                [sys.executable, fb_bin, "--fb", "/dev/fb0",
                 "--api", "http://127.0.0.1:%d" % port,
                 "--cdp-port", str(cdp_port)],
                stdout=log, stderr=log, stdin=subprocess.DEVNULL,
                start_new_session=True)
            log.close()
        except OSError as e:
            _log("restart: 拉起失败 %r" % e)
            return
        _log("restart: 已拉起渲染进程 pid=%d (%s)"
             % (proc.pid, sys.executable))
        with open(pid_file, "w") as f:
            f.write(str(proc.pid))

    def _profile_dir(self):
        """计算 Chromium profile 实际路径。"""
        from dash_config import Config  # 局部避免循环
        cfg = self.config.get() if self.config else {}
        custom = cfg.get("chromium_profile_dir") or ""
        if custom:
            return custom
        # 默认 var/chromium-profile
        return os.path.join(self.var_dir, "chromium-profile")

    def _auth_reset(self):
        """删除 Chromium profile 中的登录态数据，但保留偏好（Preferences / Bookmarks 等）。

        删除范围（白名单）：
          Default/Cookies, Default/Cookies-journal
          Default/Login Data*
          Default/Web Data*
          Default/Local Storage/, Default/IndexedDB/, Default/Session Storage/
          Default/Sessions/, Default/Extension Cookies/
          Default/Network/Cookies*

        保留：
          Default/Preferences, Default/Secure Preferences（窗口、主题、扩展等）
          Default/Bookmarks
          Default/Extensions
          profile 顶层：Local State、First Run、Last Version 等
        """
        profile = self._profile_dir()
        if not os.path.isdir(profile):
            return {"ok": True, "msg": "尚未创建 profile，无需重置"}
        # 关闭可能正在用 profile 的 Chromium（避免锁）—— 隔离异常防止崩溃
        try:
            self._fb_restart()
        except Exception:
            pass

        # 要删除的文件名（精确匹配，区分大小写）
        delete_files = {
            "Cookies", "Cookies-journal",
            "Login Data", "Login Data-journal",
            "Login Data For Account", "Login Data For Account-journal",
            "Web Data", "Web Data-journal",
            "Network Action Predictor", "Network Action Predictor-journal",
            "QuotaManager", "QuotaManager-journal",
            "Reporting and NEL", "Reporting and NEL-journal",
            "TopSites", "Top Sites", "Shortcuts", "TopSites-journal",
        }
        # 要删除的目录名
        delete_dirs = {
            "Local Storage", "Local Storage LevelDB",
            "IndexedDB", "Session Storage",
            "Sessions", "Extension Cookies", "Extension Rules",
            "Service Worker", "CacheStorage", "Storage",
            "GPUCache", "Code Cache", "Cache", "ShaderCache",
            "GrShaderCache", "FileTypePolicies", "System Profile",
            "Network", "blob_storage", "Databases",
        }
        removed = []
        try:
            default_dir = os.path.join(profile, "Default")
            if os.path.isdir(default_dir):
                for fn in os.listdir(default_dir):
                    full = os.path.join(default_dir, fn)
                    if fn in delete_files:
                        try:
                            os.unlink(full)
                            removed.append("Default/" + fn)
                        except OSError as e:
                            removed.append("Default/" + fn + " (失败: %s)" % e)
                    elif fn in delete_dirs and os.path.isdir(full):
                        try:
                            import shutil
                            shutil.rmtree(full, ignore_errors=True)
                            removed.append("Default/" + fn + "/")
                        except OSError as e:
                            removed.append("Default/" + fn + "/ (失败: %s)" % e)
            # 顶层
            for fn in os.listdir(profile):
                full = os.path.join(profile, fn)
                if fn in delete_dirs and os.path.isdir(full):
                    try:
                        import shutil
                        shutil.rmtree(full, ignore_errors=True)
                        removed.append(fn + "/")
                    except OSError as e:
                        removed.append(fn + "/ (失败: %s)" % e)
        except OSError as e:
            return {"ok": False, "error": "无法读取 profile 目录：%s" % e}
        # 触发渲染器自动重启（重建 Chromium）
        try:
            self._fb_restart()
        except Exception:
            pass
        return {"ok": True,
                "msg": "已清理登录态，渲染器已重启，请重新登录",
                "removed": removed}

    def _fb_info(self):
        info = {"exists": os.path.exists("/dev/fb0"), "w": 0, "h": 0,
                "bpp": 0, "pil": False, "renderer_running": False}
        # 端口信息无 fb0 也要返回（设置页排障用）
        info["http_port"] = self.http_port
        try:
            info["cdp_port"] = int(os.environ.get("KIOSK_CDP_PORT")
                                   or (self.http_port + 1023))
        except (TypeError, ValueError):
            info["cdp_port"] = self.http_port + 1023
        info["profile_dir"] = self._profile_dir()
        info["profile_exists"] = os.path.isdir(info["profile_dir"])
        if not info["exists"]:
            return info
        try:
            base = "/sys/class/graphics/fb0"
            vs = open(os.path.join(base, "virtual_size")).read().strip()
            info["w"], info["h"] = (int(x) for x in vs.split(",")[:2])
            info["bpp"] = int(
                open(os.path.join(base, "bits_per_pixel")).read().strip())
        except (OSError, ValueError, IndexError):
            pass
        try:
            import PIL  # noqa
            info["pil"] = True
        except ImportError:
            pass
        pid_file = os.path.join(self.var_dir, "fb.pid")
        try:
            with open(pid_file) as f:
                pid = int(f.read().strip())
            os.kill(pid, 0)
            info["renderer_running"] = True
            info["renderer_pid"] = pid
        except (OSError, ValueError):
            pass
        return info

    def _fb_diag(self):
        """一键诊断：fb0 状态 + 进程权限 + Chromium + 日志。"""
        import grp
        import subprocess
        info = {}
        # fb0 文件属性
        try:
            st = os.stat("/dev/fb0")
            info["fb0_exists"] = True
            info["fb0_mode_octal"] = oct(st.st_mode & 0o777)
            info["fb0_uid"] = st.st_uid
            info["fb0_gid"] = st.st_gid
        except OSError as e:
            info["fb0_exists"] = False
            info["fb0_error"] = str(e)
        try:
            st = os.stat("/sys/class/graphics/fb0/virtual_size")
            info["fb0_virtual_size"] = open(
                "/sys/class/graphics/fb0/virtual_size").read().strip()
            info["fb0_bpp"] = int(open(
                "/sys/class/graphics/fb0/bits_per_pixel").read().strip())
        except OSError:
            pass
        # 实际可读写？
        info["fb0_readable"] = os.access("/dev/fb0", os.R_OK)
        info["fb0_writable"] = os.access("/dev/fb0", os.W_OK)
        # 当前进程身份
        info["pgid"] = os.getgid()
        info["puid"] = os.getuid()
        # 是否在 video 组
        try:
            video_gid = grp.getgrnam("video").gr_gid
            info["video_gid"] = video_gid
            info["in_video_group"] = (os.getgid() == video_gid) or \
                ("video" in os.getgroups())
        except KeyError:
            info["video_gid"] = None
            info["in_video_group"] = False
        # fb_render 进程状态
        pid_file = os.path.join(self.var_dir, "fb.pid")
        info["fb_pid_file"] = pid_file
        try:
            with open(pid_file) as f:
                pid = int(f.read().strip())
            try:
                os.kill(pid, 0)
                info["fb_render_alive"] = True
                info["fb_render_pid"] = pid
            except OSError:
                info["fb_render_alive"] = False
                info["fb_render_pid"] = pid
        except (OSError, ValueError):
            info["fb_render_alive"] = False
            info["fb_render_pid"] = None
        # watchdog 状态
        wd_file = os.path.join(self.var_dir, "wd.pid")
        try:
            with open(wd_file) as f:
                pid = int(f.read().strip())
            try:
                os.kill(pid, 0)
                info["watchdog_alive"] = True
                info["watchdog_pid"] = pid
            except OSError:
                info["watchdog_alive"] = False
        except (OSError, ValueError):
            info["watchdog_alive"] = False
        # chromium 是否在 PATH
        for c in ("chromium", "chromium-browser", "google-chrome"):
            p = subprocess.run(["which", c], capture_output=True, text=True,
                               timeout=3)
            path = (p.stdout or "").strip()
            if path:
                info["chromium_path"] = path
                info["chromium_name"] = c
                break
        # PIL 可用
        try:
            import PIL  # noqa
            info["pil_available"] = True
        except ImportError:
            info["pil_available"] = False
        # profile 目录
        profile = self._profile_dir()
        info["profile_dir"] = profile
        info["profile_exists"] = os.path.isdir(profile)
        # fb.log 末尾 30 行
        log_path = os.path.join(self.var_dir, "fb.log")
        try:
            with open(log_path, "r", encoding="utf-8", errors="replace") as f:
                info["fb_log_tail"] = "".join(f.readlines()[-30:])
        except OSError:
            info["fb_log_tail"] = ""
        # 配置文件 fb_enabled
        cfg = self.config.get() if self.config else {}
        info["fb_enabled_in_config"] = bool(cfg.get("fb_enabled"))
        info["pages_count"] = len(cfg.get("pages") or [])
        return info

    def _fb_dump_png(self):
        try:
            w, h, bgra, stride = fb_raw_read()
        except Exception:
            return None
        try:
            return bgra_to_png(w, h, bgra, stride)
        except Exception:
            return None

    # ---- GET ----
    def do_GET(self):
        path = self.path.split("?", 1)[0].split("#", 1)[0]
        if path == "/api/status":
            cfg = self.config.get()
            self._send_json(200, {
                "ok": True,
                "version": APP_VERSION,
                "config": cfg,
                "pages": cfg.get("pages") or [],
            })
            return
        if path == "/api/config":
            self._send_json(200, {"ok": True, "config": self.config.get()})
            return
        if path == "/api/pages":
            self._send_json(200, {"ok": True,
                                  "pages": self.pages.list()})
            return
        if path == "/api/pages/raw":
            from urllib.parse import parse_qs
            q = parse_qs(self.path.split("?", 1)[1] if "?" in self.path else "")
            name = (q.get("name") or [""])[0]
            try:
                content = self.pages.read(name)
            except ValueError as e:
                self._send_json(400, {"ok": False, "error": str(e)})
                return
            if content is None:
                self._send_json(404, {"ok": False, "error": "文件不存在"})
                return
            self._send(200, {"ok": True, "name": name, "content": content},
                       ctype="application/json; charset=utf-8")
            return

        if path == "/api/pages/file":
            # 直接返回二进制内容（带正确 MIME），供 <img>/<video> 预览
            from urllib.parse import parse_qs
            q = parse_qs(self.path.split("?", 1)[1] if "?" in self.path else "")
            name = (q.get("name") or [""])[0]
            try:
                data = self.pages.read_bytes(name)
            except ValueError as e:
                self._send_json(400, {"ok": False, "error": str(e)})
                return
            if data is None:
                self._send_json(404, {"ok": False, "error": "文件不存在"})
                return
            self._send(200, data, ctype=dash_pages.mime_of(name))
            return

        if not self._is_trusted():
            if path == "/settings" or path.startswith("/settings/") or \
                    path.startswith("/api/fb/"):
                self._deny_local_only()
                return

        if path == "/settings":
            return self._serve_static("/settings.html")
        if path == "/api/fb/info":
            self._send_json(200, {"ok": True, "fb": self._fb_info()})
            return
        if path == "/api/fb/dump.png":
            png = self._fb_dump_png()
            if png is None:
                self._send_json(404, {"ok": False,
                                      "error": "帧缓冲不可用（未启用或无权限）"})
                return
            self._send(200, png, ctype="image/png")
            return
        if path == "/api/fb/log":
            # 返回 fb.log 末尾 100 行（排障用）
            log_path = os.path.join(self.var_dir, "fb.log")
            lines = []
            try:
                with open(log_path, "r", encoding="utf-8", errors="replace") as f:
                    lines = f.readlines()[-100:]
            except OSError:
                pass
            self._send_json(200, {"ok": True, "log": "".join(lines)})
            return
        if path == "/api/fb/diag":
            # 一键诊断：把环境 + 权限 + 进程状态打包返回
            self._send_json(200, {"ok": True, "diag": self._fb_diag()})
            return

        rel = path if path != "/" else "/index.html"
        self._serve_static(rel)

    # ---- POST ----
    def do_POST(self):
        path = self.path.split("?", 1)[0]
        if not self._is_trusted():
            if path == "/api/settings" or path == "/api/config" or \
                    path.startswith("/api/pages") or \
                    path.startswith("/api/auth"):
                self._deny_local_only()
                return
        if path == "/api/settings" or path == "/api/config":
            patch = self._read_json()
            if patch is None:
                self._send_json(400, {"ok": False, "error": "无效的请求体"})
                return
            prev = self.config.get()
            ok, err = self.config.update(patch)
            if ok:
                cur = self.config.get()
                if fb_restart_needed(prev, cur):
                    self._fb_restart()
                self._send_json(200, {"ok": True, "config": cur})
            else:
                self._send_json(400, {"ok": False, "error": err})
            return
        if path == "/api/pages/save":
            obj = self._read_json()
            if not obj or not obj.get("name"):
                self._send_json(400, {"ok": False, "error": "缺少 name"})
                return
            encoding = (obj.get("encoding") or "text").lower()
            try:
                if encoding == "base64":
                    # 二进制上传（图片 / 视频）
                    self.pages.write_bytes(str(obj["name"]),
                                           str(obj.get("content", "")))
                else:
                    self.pages.write(str(obj["name"]),
                                     str(obj.get("content", "")))
            except ValueError as e:
                self._send_json(400, {"ok": False, "error": str(e)})
                return
            self._send_json(200, {"ok": True})
            return
        if path == "/api/pages/delete":
            obj = self._read_json()
            if not obj or not obj.get("name"):
                self._send_json(400, {"ok": False, "error": "缺少 name"})
                return
            try:
                self.pages.delete(str(obj["name"]))
            except ValueError as e:
                self._send_json(400, {"ok": False, "error": str(e)})
                return
            self._send_json(200, {"ok": True})
            return
        if path == "/api/auth/reset":
            self._send_json(200, self._auth_reset())
            return
        if path == "/api/fb/restart":
            # 手动强制重建 fb_render 进程（用于拖拽新文件后立即显示 / 排障）
            self._fb_restart()
            self._send_json(200, {"ok": True,
                                  "msg": "已重启渲染进程（约 2-3 秒后生效）"})
            return
        self._send_json(405, {"ok": False, "error": "Method Not Allowed"})