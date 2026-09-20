#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""fnOS 浏览器屏 —— 显示器（framebuffer）渲染器。

架构（沿用 fnos-dashboard，但「画布后端」换成 BrowserCanvas）：
  1. 后台线程从 http://127.0.0.1:<port>/api/status 拉配置 + /api/pages 拉页面列表
  2. BrowserCanvas 调用 Chromium CDP：
        Page.navigate(url, wait="load")
        Page.captureScreenshot → base64 PNG
        → PIL 解码 → resize → 旋转 → BGRA bytes
  3. FB.blit(bgra) 直接写 /dev/fb0

单屏布局（与 fnos-dashboard 同 1280×800 设计基准 + ui_scale 缩放）：
  - 大背景 = 浏览器截屏（充满 fb）
  - 顶部 header：当前页面名 + 时钟 + 离线徽标
  - 页脚：分页点 + 倒计时

轮换策略（默认 cycle 模式）：
  - pages 中 mode == "single" 的页面独占全屏，循环忽略其余
  - pages 中 mode == "cycle" 的按 rotate_seconds 整除时间戳翻页
  - 每个页面若 refresh_seconds > 0，到点会 Page.reload()
"""

import argparse
import base64
import datetime
import fcntl
import io
import json
import mmap
import os
import struct
import sys
import threading
import time
import urllib.request

import dash_pages
from dash_browser import Browser, find_chromium


# 与 fnos-dashboard / settings.html 共享的 6 套主题
PALETTES = {
    "midnight": {"bg": (10, 19, 34), "text": (232, 238, 251), "dim": (147, 165, 196),
                 "accent": (59, 130, 246), "warn": (245, 158, 11), "danger": (248, 113, 113),
                 "down": (52, 211, 153), "up": (251, 191, 36)},
    "graphite": {"bg": (14, 16, 19), "text": (231, 234, 240), "dim": (154, 163, 178),
                 "accent": (45, 212, 191), "warn": (245, 158, 11), "danger": (251, 113, 133),
                 "down": (74, 222, 128), "up": (251, 191, 36)},
    "emerald":  {"bg": (4, 35, 26), "text": (228, 247, 238), "dim": (143, 196, 173),
                 "accent": (52, 211, 153), "warn": (251, 191, 36), "danger": (251, 113, 133),
                 "down": (94, 234, 212), "up": (252, 211, 77)},
    "solar":    {"bg": (28, 18, 4), "text": (253, 243, 224), "dim": (201, 168, 120),
                 "accent": (245, 158, 11), "warn": (251, 191, 36), "danger": (248, 113, 113),
                 "down": (74, 222, 128), "up": (96, 165, 250)},
    "sakura":   {"bg": (253, 241, 246), "text": (64, 42, 53), "dim": (163, 121, 140),
                 "accent": (236, 72, 153), "warn": (217, 119, 6), "danger": (225, 29, 72),
                 "down": (16, 185, 129), "up": (139, 92, 246)},
    "light":    {"bg": (241, 244, 249), "text": (30, 41, 59), "dim": (100, 116, 139),
                 "accent": (37, 99, 235), "warn": (217, 119, 6), "danger": (220, 38, 38),
                 "down": (5, 150, 105), "up": (217, 119, 6)},
}

FONT_LATIN_CANDIDATES = (
    "/usr/share/fonts/truetype/noto/NotoSansMono-Regular.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSansMono-Bold.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    "/System/Library/Fonts/Menlo.ttc",
    "/System/Library/Fonts/Helvetica.ttc",
)
FONT_CJK_CANDIDATES = (
    "/usr/share/fonts/truetype/droid/DroidSansFallbackFull.ttf",
    "/usr/share/fonts/truetype/wqy/wqy-microhei.ttc",
    "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
    "/System/Library/Fonts/PingFang.ttc",
    "/System/Library/Fonts/Supplemental/Arial Unicode.ttf",
)


# --------------------------------------------------------------------------
# 帧缓冲设备
# --------------------------------------------------------------------------
class FB:
    def __init__(self, path="/dev/fb0"):
        base = os.path.join("/sys/class/graphics",
                            os.path.basename(os.path.realpath(path)))
        vs = open(os.path.join(base, "virtual_size")).read().strip()
        self.w, self.h = (int(x) for x in vs.split(",")[:2])
        bpp = int(open(os.path.join(base, "bits_per_pixel")).read().strip())
        if bpp != 32:
            raise RuntimeError("仅支持 32bpp 帧缓冲，当前 %dbpp" % bpp)
        stride_file = os.path.join(base, "stride")
        self.stride = max(self.w * 4,
                          int(open(stride_file).read().strip())
                          if os.path.exists(stride_file) else self.w * 4)
        self.fd = os.open(path, os.O_RDWR)
        deadline = time.time() + 15
        while True:
            try:
                fcntl.flock(self.fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                break
            except OSError:
                if time.time() >= deadline:
                    os.close(self.fd)
                    raise RuntimeError("另一个渲染进程正在使用 " + path)
                print("[fb] 等待帧缓冲锁释放…", flush=True)
                time.sleep(0.5)
        self.mm = mmap.mmap(self.fd, self.stride * self.h)
        self._row = self.w * 4

    def blit(self, bgra):
        if self.stride == self._row:
            self.mm[0:self._row * self.h] = bgra[:self._row * self.h]
            return
        for y in range(self.h):
            off = y * self.stride
            self.mm[off:off + self._row] = \
                bgra[y * self._row:(y + 1) * self._row]

    def close(self):
        try:
            self.mm.close()
            os.close(self.fd)
        except OSError:
            pass


# --------------------------------------------------------------------------
# BrowserCanvas —— Chromium 截屏 → PIL → 缩放 → 输出 RGB 缓冲
# --------------------------------------------------------------------------
class BrowserCanvas:
    name = "browser"

    def __init__(self, w, h, browser, page_store):
        from PIL import Image  # noqa
        self._Image = Image
        self.w, self.h = w, h
        self.browser = browser
        self.page_store = page_store
        self.img = Image.new("RGB", (w, h), (0, 0, 0))
        self._page = None
        self._page_url = ""
        self._loaded_at = 0.0
        self._last_screenshot_ok = False
        self._error_msg = ""

    def set_page(self, page):
        self._page = page
        self._page_url = dash_pages.resolve_url(page, self.page_store)
        self._loaded_at = 0.0  # 触发下次 begin() 重新导航

    def _render_background(self, pil_img):
        """把浏览器截屏按 fb 尺寸自适应填到画布底层（保持比例）。"""
        bw, bh = pil_img.size
        if bw == self.w and bh == self.h:
            self.img.paste(pil_img, (0, 0))
            return
        # 等比缩放到 fb 全覆盖（cover 模式）
        sx = self.w / bw
        sy = self.h / bh
        s = max(sx, sy)
        nw, nh = max(1, int(round(bw * s))), max(1, int(round(bh * s)))
        resized = pil_img.resize((nw, nh), self._Image.LANCZOS)
        ox = (self.w - nw) // 2
        oy = (self.h - nh) // 2
        self.img.paste(resized, (ox, oy))

    def begin(self, bg=None):
        """把当前页面渲染成底层画面。失败保留上一帧。"""
        self.img.paste(bg if bg else (0, 0, 0), [0, 0, self.w, self.h])
        if self._page is None:
            return
        url = self._page_url
        if not url:
            self._error_msg = "空 URL"
            return
        now = time.time()
        # 触发导航：页面变更或刷新间隔到
        refresh = int(self._page.get("refresh_seconds") or 0)
        need_nav = (not self._loaded_at) or (refresh > 0 and
                                            now - self._loaded_at >= refresh)
        if need_nav:
            if not self.browser.alive():
                self._error_msg = "Chromium 未运行"
                return
            try:
                self.browser.navigate(url, wait="load",
                                      timeout=int(self._page.get("timeout") or 30))
                self._loaded_at = now
                self._error_msg = ""
            except Exception as e:
                self._error_msg = "导航失败：%s" % str(e)[:80]
                return
        # 截屏
        try:
            data_b64 = self.browser.screenshot()
            if not data_b64:
                self._error_msg = "截图数据为空"
                return
            png = base64.b64decode(data_b64)
            with io.BytesIO(png) as buf:
                shot = self._Image.open(buf).convert("RGB")
            # 应用 zoom（>1 放大模拟高分屏字体）
            zoom = float(self._page.get("zoom") or 1.0)
            if abs(zoom - 1.0) > 0.01:
                nw, nh = max(1, int(shot.width * zoom)), max(1, int(shot.height * zoom))
                shot = shot.resize((nw, nh), self._Image.LANCZOS)
            self._render_background(shot)
            self._last_screenshot_ok = True
        except Exception as e:
            self._error_msg = "截图失败：%s" % str(e)[:80]
            return

    def to_bgra(self, rotate=0):
        img = self.img
        if rotate:
            rot = getattr(self._Image, "Transpose", self._Image)
            angle = {"900": rot.ROTATE_90,
                     "180": rot.ROTATE_180,
                     "270": rot.ROTATE_270}.get(str(rotate))
            if angle is not None:
                img = img.transpose(angle)
        return img.convert("RGBA").tobytes("raw", "BGRA")

    @property
    def last_error(self):
        return self._error_msg


# --------------------------------------------------------------------------
# HUD 绘制（header / footer / error overlay）
# --------------------------------------------------------------------------
class HUD:
    """基于 PIL 的简易 HUD：顶部状态条 + 底部分页点 + 错误浮层。"""

    def __init__(self, canvas, scale=1.0, pal=None):
        from PIL import ImageDraw, ImageFont
        self.c = canvas
        self._ImageDraw = ImageDraw
        self._ImageFont = ImageFont
        self.s = scale
        self.pal = pal or PALETTES["midnight"]
        self._fonts = {}
        latin = next((p for p in FONT_LATIN_CANDIDATES if os.path.exists(p)), None)
        cjk = next((p for p in FONT_CJK_CANDIDATES if os.path.exists(p)), None)
        if not latin and not cjk:
            raise RuntimeError("未找到可用的系统字体")
        self._latin_path = latin or cjk
        self._cjk_path = cjk or latin

    def _font(self, size, cjk=False):
        size = max(8, int(size))
        key = (size, cjk)
        f = self._fonts.get(key)
        if f is None:
            f = self._ImageFont.truetype(self._cjk_path if cjk else self._latin_path,
                                         size)
            self._fonts[key] = f
        return f

    @staticmethod
    def _runs(s):
        runs = []
        cur, cur_a = "", None
        for ch in str(s):
            a = ord(ch) < 128
            if cur_a is None or a == cur_a:
                cur += ch
                cur_a = a
            else:
                runs.append((cur, cur_a))
                cur, cur_a = ch, a
        if cur:
            runs.append((cur, cur_a))
        return runs

    def text(self, x, y, s, size, color, anchor="la"):
        runs = self._runs(s)
        d = self.c
        widths = [d.textlength(t, font=self._font(size, not a))
                  for t, a in runs]
        total = sum(widths)
        if anchor[0] == "r":
            x -= total
        elif anchor[0] == "c":
            x -= total / 2
        va = anchor[1] if len(anchor) > 1 else "a"
        for (t, is_ascii), w in zip(runs, widths):
            d.text((x, y), t, font=self._font(size, not is_ascii),
                   fill=color, anchor="l" + va)
            x += w

    def text_w(self, s, size):
        return self.c.textlength(
            str(s), font=self._font(size, cjk=any(ord(ch) > 127 for ch in str(s))))

    def header(self, page_name, offline):
        s = self.s
        c = self.c
        W = c.width if hasattr(c, "width") else self.c.img.width
        # 半透明顶栏
        bar_h = int(60 * s)
        overlay = self._Image.new("RGBA", (W, bar_h),
                                  (*self.pal["bg"], 180))
        self.c.img.paste(overlay, (0, 0), overlay)
        # 页名（左）
        self.text(int(24 * s), int(18 * s), page_name, int(22 * s),
                  self.pal["text"])
        # 时钟（右）
        clock = datetime.datetime.now().strftime("%H:%M:%S")
        self.text(W - int(24 * s), int(18 * s), clock, int(28 * s),
                  self.pal["dim"], anchor="rt")
        if offline:
            self.text(W - int(24 * s), int(44 * s), "OFFLINE", int(18 * s),
                      self.pal["danger"], anchor="rt")

    def footer(self, n_pages, idx, rotate_sec, is_single=False):
        s = self.s
        c = self.c
        W = c.width if hasattr(c, "width") else self.c.img.width
        H = c.height if hasattr(c, "height") else self.c.img.height
        bar_h = int(36 * s)
        y0 = H - bar_h
        overlay = self._Image.new("RGBA", (W, bar_h),
                                  (*self.pal["bg"], 160))
        self.c.img.paste(overlay, (0, y0), overlay)
        if is_single:
            self.text(W / 2, y0 + int(10 * s), "SINGLE URL MODE",
                      int(16 * s), self.pal["dim"], anchor="ma")
        else:
            # 分页点
            total_w = n_pages * 16 * s
            x0 = W / 2 - total_w / 2
            for i in range(n_pages):
                cx = x0 + i * 16 * s + 4 * s
                cy = y0 + int(14 * s)
                r = int(4 * s)
                col = self.pal["accent"] if i == idx else self.pal["dim"]
                self.c.ellipse([cx - r, cy - r, cx + r, cy + r], fill=col)
            remain = max(0, int(rotate_sec - (time.time() % rotate_sec)))
            self.text(W - int(24 * s), y0 + int(10 * s),
                      "%ds" % remain, int(16 * s),
                      self.pal["dim"], anchor="rt")

    def error_overlay(self, msg):
        s = self.s
        c = self.c
        W = c.width if hasattr(c, "width") else self.c.img.width
        H = c.height if hasattr(c, "height") else self.c.img.height
        box_w = max(280, int(W * 0.6))
        box_h = int(80 * s)
        x0 = (W - box_w) // 2
        y0 = (H - box_h) // 2
        overlay = self._Image.new("RGBA", (box_w, box_h),
                                  (*self.pal["bg"], 220))
        self.c.img.paste(overlay, (x0, y0), overlay)
        self.c.rectangle([x0, y0, x0 + box_w, y0 + box_h],
                         outline=self.pal["danger"], width=2)
        self.text(x0 + int(16 * s), y0 + int(12 * s), "⚠ 错误",
                  int(20 * s), self.pal["danger"])
        self.text(x0 + int(16 * s), y0 + int(40 * s),
                  str(msg)[:60], int(16 * s), self.pal["text"])


# --------------------------------------------------------------------------
# 后台数据拉取
# --------------------------------------------------------------------------
def fetch_json(url, timeout=6):
    req = urllib.request.Request(url, headers={"User-Agent": "fnos-kiosk-fb/1.0"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8", "replace"))


class Fetcher(threading.Thread):
    def __init__(self, api, interval):
        super().__init__(daemon=True)
        self.api = api
        self.interval = max(1.0, interval)
        self.config = {}
        self.pages = []
        self.offline = True

    def run(self):
        while True:
            try:
                data = fetch_json(self.api + "/api/status", timeout=8)
                self.config = data.get("config") or {}
                self.pages = data.get("pages") or []
                self.offline = False
            except Exception:
                self.offline = True
            time.sleep(self.interval)


# --------------------------------------------------------------------------
# 主循环
# --------------------------------------------------------------------------
def main():
    ap = argparse.ArgumentParser(description="fnOS 浏览器屏 显示器渲染器")
    ap.add_argument("--fb", default="/dev/fb0")
    # 默认从环境变量读 TRIM_SERVICE_PORT（fnOS 注入），再退回 8200。
    # 上游 dash_http.py 始终传 --api 显式值，此默认值仅作直接调试兜底。
    ap.add_argument("--api", default="http://127.0.0.1:" +
                    os.environ.get("TRIM_SERVICE_PORT", "8200"))
    ap.add_argument("--interval", type=float, default=2.0)
    ap.add_argument("--pages-dir", default="")
    # Chromium CDP 远程调试端口默认 9223，可被 KIOSK_CDP_PORT 覆盖以防端口冲突。
    ap.add_argument("--cdp-port", type=int,
                    default=int(os.environ.get("KIOSK_CDP_PORT", "9223")))
    args = ap.parse_args()

    # ---- fb 设备 ----
    try:
        fb = FB(args.fb)
    except RuntimeError as e:
        print("[fb] %s" % e, flush=True)
        return
    W, H = fb.w, fb.h
    print("[fb] %dx%d stride=%d" % (W, H, fb.stride), flush=True)

    # ---- 后台拉数据 ----
    fetcher = Fetcher(args.api, args.interval)
    fetcher.start()
    # 等到第一份配置拉到手
    for _ in range(50):
        if fetcher.config:
            break
        time.sleep(0.1)

    cfg = fetcher.config or {}
    win_w = int(((cfg.get("browser_window") or [1920, 1080])[0]))
    win_h = int(((cfg.get("browser_window") or [1920, 1080])[1]))
    # 计算默认 user-data-dir：用户未配置时用 var/chromium-profile 持久化
    # （cookies / localStorage / IndexedDB / autofill / Service Worker 都留存）
    var_dir_for_profile = os.environ.get("TRIM_PKGVAR") or \
        os.path.join(os.getcwd(), "var")
    default_profile = cfg.get("chromium_profile_dir", "") or \
        os.path.join(var_dir_for_profile, "chromium-profile")
    try:
        os.makedirs(default_profile, exist_ok=True)
    except OSError:
        pass
    # PIL 缺失直接拒绝
    try:
        from PIL import Image  # noqa
    except ImportError:
        print("[fb] 缺少 python3-PIL，无法启动（apt install python3-pil）",
              flush=True)
        return

    # ---- 启动 Chromium ----
    log_path = os.path.join(os.path.dirname(args.fb) or ".", "fb_chromium.log")
    # var 目录一般是 /var/apps/<pkg>/var；fb.log 旁写
    var_log = os.environ.get("TRIM_PKGVAR")
    if var_log:
        log_path = os.path.join(var_log, "fb_chromium.log")
    browser = Browser(
        window=(win_w, win_h),
        port=args.cdp_port,
        chromium_path=cfg.get("browser_path", ""),
        scale=float(cfg.get("browser_scale", 1.0)),
        timeout=int(cfg.get("browser_timeout", 30)),
        hide_cursor=bool(cfg.get("hide_cursor", True)),
        # profile_dir：留空用 var/chromium-profile（持久登录态）
        user_data_dir=default_profile,
    )
    try:
        browser.start(log_path=log_path)
        browser.connect()
        print("[fb] Chromium ready (window=%dx%d)" % (win_w, win_h), flush=True)
    except Exception as e:
        print("[fb] Chromium 启动失败：%r" % e, flush=True)
        fb.close()
        return

    # ---- 本地页面存储（fb 渲染器也要读 var/pages/）----
    pages_root = args.pages_dir or os.path.join(
        os.environ.get("TRIM_PKGVAR", os.path.join(os.getcwd(), "var")), "pages")
    page_store = dash_pages.PageStore(pages_root)

    canvas = BrowserCanvas(W, H, browser, page_store)
    last_frame = None
    rotate = 0
    rotate_sec = 30
    nav_interval = max(1.0, args.interval)

    try:
        while True:
            now = time.time()
            cfg = fetcher.config or {}
            pages = dash_pages.list_visible_pages(cfg)
            default_mode = cfg.get("default_mode", "cycle")

            # 主题色板
            pal = PALETTES.get(cfg.get("theme", "midnight"), PALETTES["midnight"])
            accent = str(cfg.get("accent") or "")
            if accent.startswith("#") and len(accent) == 7:
                try:
                    r, g, b = int(accent[1:3], 16), int(accent[3:5], 16), int(accent[5:7], 16)
                    pal = dict(pal)
                    pal["accent"] = (r, g, b)
                except ValueError:
                    pass

            new_rotate = cfg.get("fb_rotate") if cfg.get("fb_rotate") in (0, 90, 180, 270) else 0
            if new_rotate != rotate:
                rotate = new_rotate
                # 浏览器窗口尺寸在 rotate 变化时无需重启（截屏在 PIL 端旋转）
                # 但窗口尺寸若变化需要重启 Chromium
                win = cfg.get("browser_window") or [1920, 1080]
                if (win[0], win[1]) != (browser.window[0], browser.window[1]):
                    print("[fb] 窗口尺寸变化，重启 Chromium (%dx%d → %dx%d)" %
                          (browser.window[0], browser.window[1], win[0], win[1]),
                          flush=True)
                    browser.close()
                    browser = Browser(
                        window=(int(win[0]), int(win[1])),
                        port=args.cdp_port,
                        chromium_path=cfg.get("browser_path", ""),
                        scale=float(cfg.get("browser_scale", 1.0)),
                        timeout=int(cfg.get("browser_timeout", 30)),
                        hide_cursor=bool(cfg.get("hide_cursor", True)),
                        user_data_dir=default_profile,
                    )
                    try:
                        browser.start(log_path=log_path)
                        browser.connect()
                        canvas = BrowserCanvas(W, H, browser, page_store)
                        canvas.set_page(pages[0])
                    except Exception as e:
                        print("[fb] Chromium 重建失败：%r" % e, flush=True)
                        break

            # 缩放：分辨率自适应（与 fnos-dashboard 同套）
            res_scale = min(W / 1280.0, H / 800.0)
            inches = float(cfg.get("screen_inches") or 0)
            if inches > 0:
                ppi = (W * W + H * H) ** 0.5 / inches
                ui_scale = max(0.75, min(2.2, ppi / 150.0)) * max(0.8, min(1.6, res_scale))
            else:
                ui_scale = max(0.6, res_scale)

            # 单 URL 模式：取 mode == "single" 的第一个；缺省按 default_mode
            singles = [p for p in pages if p.get("mode") == "single"]
            if default_mode == "single" and singles:
                page = singles[0]
                is_single = True
            elif default_mode == "single":
                page = pages[0] if pages else None
                is_single = True
            else:
                # cycle 模式：每 rotate_sec 翻一页
                rotate_sec = max(5, int(cfg.get("rotate_seconds", 30)))
                # 仅在 cycle 页面里循环（single 页面被排除）
                cycle_pages = [p for p in pages if p.get("mode") != "single"]
                if not cycle_pages:
                    cycle_pages = pages
                if not cycle_pages:
                    cycle_pages = pages
                idx = int(now / rotate_sec) % max(1, len(cycle_pages))
                page = cycle_pages[idx]
                is_single = False

            if page is None:
                time.sleep(1.0)
                continue

            # 如果 Chromium 死了，尝试重启（带 circuit breaker）
            if not browser.alive():
                if not getattr(main, "_restart_attempts", None):
                    main._restart_attempts = 0
                if main._restart_attempts < 5:
                    main._restart_attempts += 1
                    print("[fb] Chromium 不在，重启尝试 #%d" %
                          main._restart_attempts, flush=True)
                    try:
                        browser.start(log_path=log_path)
                        browser.connect()
                        canvas = BrowserCanvas(W, H, browser, page_store)
                    except Exception as e:
                        print("[fb] 重启失败：%r" % e, flush=True)
                        time.sleep(2)
                        continue
                else:
                    # 多次失败，画错误屏
                    canvas.img.paste(pal["bg"], [0, 0, W, H])
                    from PIL import ImageDraw
                    ImageDraw.Draw(canvas.img).text((20, 20),
                                                    "Chromium 持续启动失败，请检查 /var/apps/com.fnos.kiosk/var/fb_chromium.log",
                                                    fill=pal["danger"])
                    fb.blit(canvas.to_bgra(rotate))
                    time.sleep(5)
                    continue
            main._restart_attempts = 0

            # 切换页面时刷新 canvas 目标
            if getattr(canvas, "_page", None) is None or \
                    canvas._page.get("id") != page.get("id"):
                canvas.set_page(page)

            # 绘制
            draw_failed = False
            try:
                canvas.begin(pal["bg"])
                hud = HUD(canvas, scale=ui_scale, pal=pal)
                page_label = "%s/%s" % (
                    (dash_pages.list_visible_pages(cfg).index(page) + 1),
                    len(dash_pages.list_visible_pages(cfg))
                ) if not is_single and len(dash_pages.list_visible_pages(cfg)) > 1 \
                    else page.get("name", "")
                hud.header(page_label or page.get("name", ""),
                           fetcher.offline)
                if canvas.last_error:
                    hud.error_overlay(canvas.last_error)
                n_cycle = len(dash_pages.list_visible_pages(cfg))
                hud.footer(n_cycle, idx=0, rotate_sec=rotate_sec,
                           is_single=is_single)
            except Exception as e:
                draw_failed = True
                print("[fb] 绘制异常：%r" % e, flush=True)

            try:
                frame = canvas.to_bgra(rotate)
                if draw_failed or frame != last_frame:
                    fb.blit(frame)
                    last_frame = frame
            except Exception as e:
                print("[fb] 帧输出异常：%r" % e, flush=True)

            time.sleep(max(0.2, nav_interval - (time.time() - now)))
    finally:
        try:
            browser.close()
        except Exception:
            pass
        fb.close()


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        sys.exit(0)