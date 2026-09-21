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
# 候选 CJK 字体（按优先级）。实际路径在不同发行版差异极大，
# 下面的 _discover_cjk_font() 会先扫一遍 /usr/share/fonts/ 找更准的。
FONT_CJK_CANDIDATES = (
    "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
    "/usr/share/fonts/truetype/noto-cjk/NotoSansCJK-Regular.ttc",
    "/usr/share/fonts/truetype/noto/NotoSansCJK-Regular.ttc",
    "/usr/share/fonts/truetype/wqy/wqy-microhei.ttc",
    "/usr/share/fonts/truetype/wqy/wqy-zenhei.ttc",
    "/usr/share/fonts/truetype/arphic/uming.ttc",
    "/usr/share/fonts/opentype/noto/NotoSerifCJK-Regular.ttc",
    "/usr/share/fonts/truetype/droid/DroidSansFallbackFull.ttf",
    "/System/Library/Fonts/PingFang.ttc",
    "/System/Library/Fonts/Supplemental/Arial Unicode.ttf",
)


def _discover_cjk_font():
    """扫整个 /usr/share/fonts/ 找真·Latin+CJK 字体。

    .ttc 是字体集合，PIL 默认只加载第一个（常常是 CJK Symbols 子集，
    没有 ASCII）。优先找 .otf/.ttf 单字体（含 Latin）；
    .ttc 则优先选择文件名包含 Sans（无衬线，通常含 ASCII）且
    不带 Symbols/Emoji 的。
    """
    roots = ("/usr/share/fonts", "/usr/local/share/fonts",
             "/Library/Fonts", "/System/Library/Fonts")
    exts = (".ttf", ".otf")
    found = []
    for root in roots:
        if not os.path.isdir(root):
            continue
        for dirpath, _, filenames in os.walk(root):
            for fn in filenames:
                low = fn.lower()
                if not any(low.endswith(e) for e in exts):
                    continue
                # 跳过明确的非 CJK 字体（除非没找到别的）
                skip_keywords = ("mono", "italic", "bold", "light",
                                 "thin", "black", "condensed")
                if any(k in low for k in skip_keywords):
                    continue
                # 优先 cjk / noto / sans / hei / 微米黑 / 黑体
                if any(k in low for k in ("cjk", "noto", "sans",
                                          "hei", "uming", "ukai")):
                    found.insert(0, os.path.join(dirpath, fn))
                else:
                    found.append(os.path.join(dirpath, fn))
    # .ttc 次之（可能是 CJK Symbols-only 的集合）
    for root in roots:
        if not os.path.isdir(root):
            continue
        for dirpath, _, filenames in os.walk(root):
            for fn in filenames:
                low = fn.lower()
                if low.endswith(".ttc") and any(k in low for k in (
                        "cjk", "noto", "wqy", "uming", "pingfang")):
                    found.append(os.path.join(dirpath, fn))
    return found[0] if found else ""


def _pick_cjk_font_path():
    """先扫盘 + fc-list，再退回硬编码候选。
    优先选「同时含 Latin 和 CJK」的字体（如 wqy-microhei），
    否则选纯 CJK 字体（启动屏 / 错误屏会和 DejaVu Sans 配合用）。"""
    discovered = _discover_cjk_font()
    if discovered:
        return discovered
    # fc-list（Debian/Ubuntu fontconfig 默认提供）
    try:
        import subprocess
        r = subprocess.run(
            ["fc-list", ":lang=zh", "file"],
            capture_output=True, text=True, timeout=3)
        for line in (r.stdout or "").splitlines():
            line = line.strip().rstrip(":")
            if line and line.lower().endswith((".ttf", ".otf", ".ttc")):
                return line
    except (OSError, subprocess.TimeoutExpired):
        pass
    # 硬编码候选兜底
    for p in FONT_CJK_CANDIDATES + FONT_LATIN_CANDIDATES:
        if os.path.exists(p):
            return p
    return ""


def _has_cjk_font():
    """检查系统是否有任何 CJK 字体（用于 URL 页面中文显示）。
    返回 (installed, font_path_or_hint) —— 没装时给用户提示信息。"""
    # 1. 扫盘 + fc-list
    if _pick_cjk_font_path():
        return True, ""
    # 2. 检查 fc-list 是否非空（即便没找到中文 family，至少 fc-list 工作）
    try:
        import subprocess
        r = subprocess.run(
            ["fc-list", ":lang=zh", "file"],
            capture_output=True, text=True, timeout=3)
        if r.stdout and r.stdout.strip():
            # 有 CJK 但 _pick 没选上 —— 也算装了
            return True, ""
    except (OSError, subprocess.TimeoutExpired):
        pass
    # 3. 完全没有中文支持
    return False, "apt install fonts-noto-cjk  # Debian/Ubuntu 上安装 Noto CJK 字体（约 50MB，7万+ 汉字 + Latin）"


def _pick_latin_font_path():
    """Latin 字体（必须含 ASCII 拉丁字符）。"""
    # 先看是否已有 DejaVu / Noto Sans Mono 等
    for p in FONT_LATIN_CANDIDATES:
        if os.path.exists(p):
            return p
    # fc-list 找一个 :lang=en 的
    try:
        import subprocess
        r = subprocess.run(
            ["fc-list", ":lang=en", "file"],
            capture_output=True, text=True, timeout=3)
        for line in (r.stdout or "").splitlines():
            line = line.strip().rstrip(":")
            if line and line.lower().endswith((".ttf", ".otf", ".ttc")):
                return line
    except (OSError, subprocess.TimeoutExpired):
        pass
    return ""


def _is_cjk(ch):
    """判断是否 CJK 字符（含中文、日文、韩文、汉字标点）。"""
    o = ord(ch)
    if 0x2E80 <= o <= 0x9FFF:    # CJK 基础 + 扩展 A
        return True
    if 0xAC00 <= o <= 0xD7AF:    # 韩文
        return True
    if 0x3000 <= o <= 0x303F:    # CJK 标点
        return True
    if 0xFF00 <= o <= 0xFFEF:    # 全角字符
        return True
    if 0x3400 <= o <= 0x4DBF:    # CJK 扩展 B
        return True
    return False


def _draw_text_mixed(d, xy, text, latin_font, cjk_font, fill, anchor="la"):
    """PIL 不支持字体回退，所以逐字符按 CJK / Latin 分段渲染。

    anchor 同 PIL：第一个字符 'l'/'r'/'c'，第二个字符 'a'/'m'/'b'/'t'/'b'。
    """
    if not text:
        return
    # 1. 测总宽
    def measure(s):
        f = cjk_font if any(_is_cjk(c) for c in s) else latin_font
        return f.getlength(s)

    total_w = 0.0
    cur_run = ""
    cur_kind = None
    for ch in text:
        k = "cjk" if _is_cjk(ch) else "latin"
        if k != cur_kind and cur_run:
            total_w += measure(cur_run)
            cur_run = ""
            cur_kind = k
        cur_run += ch
        if cur_kind is None:
            cur_kind = k
    if cur_run:
        total_w += measure(cur_run)

    x, y = xy
    if anchor[0] == "r":
        x -= total_w
    elif anchor[0] == "c":
        x -= total_w / 2
    va = anchor[1] if len(anchor) > 1 else "a"

    # 2. 实际渲染
    cur_run = ""
    cur_kind = None
    for ch in text:
        k = "cjk" if _is_cjk(ch) else "latin"
        if k != cur_kind and cur_run:
            f = cjk_font if cur_kind == "cjk" else latin_font
            d.text((x, y), cur_run, fill=fill, font=f, anchor="l" + va)
            x += f.getlength(cur_run)
            cur_run = ""
        cur_run += ch
        cur_kind = k
    if cur_run:
        f = cjk_font if cur_kind == "cjk" else latin_font
        d.text((x, y), cur_run, fill=fill, font=f, anchor="l" + va)


def _measure_text_mixed(text, latin_font, cjk_font):
    """_draw_text_mixed 的纯测量版（用于其他需要总宽度的场合）。"""
    total = 0.0
    cur_run = ""
    cur_kind = None
    for ch in text:
        k = "cjk" if _is_cjk(ch) else "latin"
        if k != cur_kind and cur_run:
            f = cjk_font if cur_kind == "cjk" else latin_font
            total += f.getlength(cur_run)
            cur_run = ""
        cur_run += ch
        cur_kind = k
    if cur_run:
        f = cjk_font if cur_kind == "cjk" else latin_font
        total += f.getlength(cur_run)
    return total


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

    def __init__(self, w, h, browser, page_store, http_port=8280):
        from PIL import Image  # noqa
        self._Image = Image
        self.w, self.h = w, h
        self.browser = browser
        self.page_store = page_store
        self.http_port = http_port
        self.img = Image.new("RGB", (w, h), (0, 0, 0))
        self._page = None
        self._page_url = ""
        self._loaded_at = 0.0
        self._last_screenshot_ok = False
        self._kiosk_css_pending = ""            # 来自 cfg["url_kiosk_css"]，set_page 写入
        self._kiosk_css_applied = (None, None)  # (url_key, css) —— 跟踪已注入的 CSS，避免每帧重发
        self._error_msg = ""
        self._fit_mode = "stretch"  # cover/contain/stretch，主循环刷新；config 默认 stretch

    def set_page(self, page, kiosk_css=""):
        # v0.1.39: set_page 改为幂等——主循环每帧调用，URL/path 没变就不重导航。
        # 之前只在 page.id 变化时调用，导致用户改 zoom/fit 不会立刻生效。
        self._kiosk_css_pending = kiosk_css or ""
        if not page:
            self._page = None
            self._page_url = ""
            self._loaded_at = 0.0
            return
        new_url = dash_pages.resolve_url(page, self.page_store,
                                        http_port=self.http_port)
        old_url = self._page_url
        self._page = page
        self._page_url = new_url
        # v0.1.35: per-page fit 覆盖全局 display_fit。page.fit 是
        # "none"/"stretch"/"contain"/"cover" 之一，"none" 时回退到 _fit_mode。
        page_fit = (page.get("fit") or "none").lower() if isinstance(
            page.get("fit"), str) else "none"
        if page_fit in ("stretch", "contain", "cover"):
            self._fit_mode = page_fit
        # 只在 URL/path 实际变化时触发重新导航；其他字段（zoom/fit 等）改了不影响。
        if new_url != old_url:
            self._loaded_at = 0.0

    def _render_background(self, pil_img, zoom_applied=1.0):
        """把浏览器截屏按 fb 尺寸填充画布底层。

        fit 模式（cfg.get('display_fit', 'stretch')）：
          - 'stretch' (默认): 强制拉伸到 fb 尺寸填满屏幕（推荐，16:9 内容在 4:3 fb 上轻微变形）
          - 'cover':         等比缩放 + 裁切，铺满 fb（适合背景图）
          - 'contain':       等比缩放 + 居中，整页可见，多余区域填黑边

        v0.1.38: zoom_applied > 1 时 shot 已在 begin() 里被 crop 到 fb 尺寸；
                 zoom_applied < 1 时 shot 已经比 fb 小，必须居中粘贴（不能 stretch，
                 否则拉伸就抵消了 zoom）。
        """
        bw, bh = pil_img.size
        fit_mode = (self._fit_mode or "stretch").lower() if hasattr(
            self, "_fit_mode") else "stretch"
        # 缩小版（zoom<1）：shot 已比 fb 小，强制居中黑边（不拉伸）
        if zoom_applied < 1.0 - 0.01 and (bw < self.w or bh < self.h):
            self.img.paste((0, 0, 0), [0, 0, self.w, self.h])
            ox = (self.w - bw) // 2
            oy = (self.h - bh) // 2
            self.img.paste(pil_img, (ox, oy))
            return
        if fit_mode == "stretch":
            # 强制拉伸
            if (bw, bh) != (self.w, self.h):
                pil_img = pil_img.resize((self.w, self.h),
                                          self._Image.LANCZOS)
            self.img.paste(pil_img, (0, 0))
            return
        if bw == self.w and bh == self.h:
            self.img.paste(pil_img, (0, 0))
            return
        sx = self.w / bw
        sy = self.h / bh
        if fit_mode == "cover":
            s = max(sx, sy)
        else:
            # contain（默认）
            s = min(sx, sy)
        nw, nh = max(1, int(round(bw * s))), max(1, int(round(bh * s)))
        resized = pil_img.resize((nw, nh), self._Image.LANCZOS)
        ox = (self.w - nw) // 2
        oy = (self.h - nh) // 2
        self.img.paste(resized, (ox, oy))

    def begin(self, bg=None):
        """把当前页面渲染成底层画面。失败保留上一帧。"""
        from PIL import ImageDraw
        self.img.paste(bg if bg else (0, 0, 0), [0, 0, self.w, self.h])
        # 给 HUD 调用做准备：HUD 早期代码（self.c.textlength / self.c.text / self.c.rectangle
        # / self.c.ellipse）——这些都是 ImageDraw 方法。BrowserCanvas 实例本身没有这些，
        # 但 HUD 在 HUD.__init__ 里把 BrowserCanvas 实例存到 self.c。所以把 ImageDraw
        # 的方法挂到 BrowserCanvas 上，让 HUD 的旧代码能继续跑。
        # 注意：必须在 self.img.paste 之后执行（ImageDraw.Draw 需要 img 是当前的）。
        d = ImageDraw.Draw(self.img)
        self.textlength = d.textlength
        self.text = d.text
        self.rectangle = d.rectangle
        self.ellipse = d.ellipse
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
                # v0.1.34: URL 类型页面导航前先注入 url_kiosk_css（让 body/html
                # 强制铺满 viewport，去除 URL 自带 margin / fixed-width 子元素）。
                # 本地 HTML / 媒体文件（wrapper.html 是 kiosk 自己生成的）不注入，
                # 否则会破坏 kiosk 自有布局。
                page_type = self._page.get("type") or "url"
                want_css = self._kiosk_css_pending if page_type == "url" else ""
                if (page_type, want_css) != self._kiosk_css_applied:
                    try:
                        self.browser.set_kiosk_css(want_css)
                    except Exception:
                        pass
                    self._kiosk_css_applied = (page_type, want_css)
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
            # v0.1.38: per-page zoom 真正生效。之前的实现是先 PIL resize shot 到 N 倍，
            # 然后 _render_background 又把它 resize 回 fb 尺寸（zoom 完全被覆盖）。
            # 正确语义：zoom>1 → 内容"放大"（看到的内容更少但每样东西更大）；
            #           zoom<1 → 内容"缩小"（看到的内容更多但每样东西更小）；
            #           zoom==1 → 原尺寸。
            zoom = float(self._page.get("zoom") or 1.0)
            if zoom > 1.0 + 0.01:
                # scale up to logical zoom 倍，再取中心 fb 区域
                big = shot.resize((max(1, int(shot.width * zoom)),
                                   max(1, int(shot.height * zoom))),
                                  self._Image.LANCZOS)
                ox = max(0, (big.width - self.w) // 2)
                oy = max(0, (big.height - self.h) // 2)
                shot = big.crop((ox, oy, ox + self.w, oy + self.h))
            elif zoom < 1.0 - 0.01:
                # 缩小版 < fb 尺寸：居中 + 黑边
                shot = shot.resize((max(1, int(shot.width * zoom)),
                                    max(1, int(shot.height * zoom))),
                                   self._Image.LANCZOS)
            # zoom==1.0 时 shot 是 shot.w × shot.h，正常交给 _render_background
            self._render_background(shot, zoom_applied=zoom)
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
        from PIL import Image, ImageDraw, ImageFont
        self.c = canvas
        self._Image = Image
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
    # 默认从环境变量读 TRIM_SERVICE_PORT（fnOS 注入），再退回 8280。
    # 上游 dash_http.py 始终传 --api 显式值，此默认值仅作直接调试兜底。
    ap.add_argument("--api", default="http://127.0.0.1:" +
                    os.environ.get("TRIM_SERVICE_PORT", "8280"))
    ap.add_argument("--interval", type=float, default=2.0)
    ap.add_argument("--pages-dir", default="")
    # Chromium CDP 端口（fb_render 自己内部用，绑定 127.0.0.1 仅本机）。
    # 优先级：--cdp-port > KIOSK_CDP_PORT > http_port+1023（从 --api 解析）
    # 重要：v0.1.20 之前这里默认 9223，与 dashboard 的 9303 不一致 → 截图失败
    # "连不上 Chromium（:json 失败）：Connection refused" 的根因。
    # 注：v0.1.25 删了设置页「远程控制」tab + cdp_proxy 模块；外部 chrome://inspect
    # 仍可用，端口提示在设置页底部。
    ap.add_argument("--cdp-port", type=int, default=0)
    args = ap.parse_args()
    if args.cdp_port <= 0:
        env_v = os.environ.get("KIOSK_CDP_PORT", "")
        if env_v.strip():
            args.cdp_port = int(env_v)
        else:
            try:
                from urllib.parse import urlparse
                u = urlparse(args.api or "")
                args.cdp_port = (u.port or 8280) + 1023
            except Exception:
                args.cdp_port = 9303

    # ---- fb 设备 ----
    fb_attempts = 0
    while True:
        try:
            fb = FB(args.fb)
            break
        except RuntimeError as e:
            fb_attempts += 1
            delay = min(30, 5 * fb_attempts)
            print("[fb] fb0 初始化失败（#%d，%ds 后重试）：%s"
                  % (fb_attempts, delay, e), flush=True)
            time.sleep(delay)
    W, H = fb.w, fb.h
    print("[fb] v%s fb_render starting" % __import__("dash_config").APP_VERSION,
          flush=True)
    print("[fb] %dx%d stride=%d" % (W, H, fb.stride), flush=True)

    # ---- 立刻写一帧"启动中"屏到 fb0（不依赖 Chromium）----
    # 这一步至关重要：它向用户证明 fb0 写权限拿到了（哪怕 Chromium 还没起来）。
    # 同时记录关键诊断信息到 fb.log，调试用。
    try:
        from PIL import Image, ImageDraw, ImageFont
        _diag_img = Image.new("RGB", (W, H), (10, 19, 34))
        _diag_draw = ImageDraw.Draw(_diag_img)
        # 智能选字体：Latin + CJK 配合（避免「CJK 字体不含 ASCII」问题）
        _latin_path = _pick_latin_font_path()
        _cjk_path = _pick_cjk_font_path()
        print("[fb] 字体: latin=%s cjk=%s" % (_latin_path, _cjk_path),
              flush=True)
        # v0.1.46: CJK 字体检测 —— 没装 CJK 时 URL 页面中文会显示为 □
        _cjk_ok, _cjk_hint = _has_cjk_font()
        if not _cjk_ok:
            print("[fb] ⚠ CJK 字体未安装！URL 页面中文会显示为 □。修复：%s"
                  % _cjk_hint, flush=True)
            # 启动屏加一行告警（让用户上 fb0 第一眼就看到）
            _warn = "⚠ CJK 字体未安装，中文 URL 页将显示 □"
            _draw_text_mixed(_diag_draw, (W // 2, H // 3 + 3 * (H // 7)),
                             _warn, _latin_sm, _cjk_sm,
                             fill=(255, 180, 80), anchor="mm")
            _hint_y = H // 3 + 4 * (H // 7)
            if not _latin_sm and not _cjk_sm:
                _hint_y = H // 3 + 4 * (H // 7)  # fallback
            _draw_text_mixed(_diag_draw, (W // 2, _hint_y),
                             _cjk_hint, _latin_sm, _cjk_sm,
                             fill=(180, 200, 230), anchor="mm")
        _big = max(32, W // 22)
        _sm = max(18, W // 40)
        _latin_big = ImageFont.truetype(_latin_path, _big) if _latin_path else None
        _latin_sm = ImageFont.truetype(_latin_path, _sm) if _latin_path else None
        _cjk_big = ImageFont.truetype(_cjk_path, _big) if _cjk_path else _latin_big
        _cjk_sm = ImageFont.truetype(_cjk_path, _sm) if _cjk_path else _latin_sm
        _lines = [
            ("fnos-kiosk 启动中", (232, 238, 251)),
            ("正在启动 Chromium（CDP 远程调试）……", (147, 165, 196)),
            ("fb0 = %dx%d @ 32bpp" % (W, H), (147, 165, 196)),
        ]
        for i, (txt, col) in enumerate(_lines):
            _draw_text_mixed(_diag_draw, (W // 2, H // 3 + i * (H // 7)),
                             txt, _latin_big, _cjk_big, fill=col, anchor="mm")
        # 右下角写个时间戳（纯 ASCII，用 Latin 字体）
        _ts = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        _diag_draw.text((W - 16, H - 16), _ts, fill=(60, 80, 110),
                        font=_latin_sm, anchor="rb")
        fb.blit(_diag_img.convert("RGBA").tobytes("raw", "BGRA"))
        print("[fb] 启动中屏已写入 fb0（Chromium 还没起来，正在初始化）", flush=True)
    except Exception as e:
        print("[fb] 写启动屏失败（%r）——fb0 可能不可写" % e, flush=True)

    # ---- 后台拉数据 ----
    fetcher = Fetcher(args.api, args.interval)
    fetcher.start()
    # 等到第一份配置拉到手
    for _ in range(50):
        if fetcher.config:
            break
        time.sleep(0.1)

    cfg = fetcher.config or {}
    # v0.1.46: URL 页面（任意含 type=url 的页面）强制用 match_dashboard。
    # —— 这是关键修复：之前用户的旧 config 里写的是 match_fb_wide，被 _sanitize
    #    误清洗成 [1920,1080] 列表默认值 → Chromium viewport = 1920×1080
    #    → 16:9 dashboard 在 fb 里只占 1024×576 + 下方 192px 黑边。
    # 现在只要有任意 URL 页就强制 match_dashboard（无视配置），保证填满 fb。
    # 非 URL 页（html_file / media_file）才走用户的 browser_window 设置（默认 match_fb，
    # 让 wrapper HTML 用 object-fit 在 4:3 viewport 里正常居中显示）。
    pages_for_viewport = cfg.get("pages") or []
    has_url_page = any(p.get("type") == "url" for p in pages_for_viewport if isinstance(p, dict))
    if has_url_page:
        bw_cfg = "match_dashboard"
    else:
        bw_cfg = cfg.get("browser_window") or "match_fb"
    print("[fb] 视口决策: has_url=%s bw=%s" % (has_url_page, bw_cfg), flush=True)
    if isinstance(bw_cfg, str):
        bw_lower = bw_cfg.lower()
        if bw_lower in ("match_fb", "fb", "auto"):
            win_w, win_h = W, H
        elif bw_lower in ("match_fb_wide", "wide", "1.25x"):
            # 保持 fb 长宽比 ×1.25（线性放大，每边都 1.25 倍）
            # 1024×768 fb → 1280×960 viewport → dashboard 填满 → PIL scale → fb
            win_w, win_h = int(W * 1.25), int(H * 1.25)
        elif bw_lower in ("match_dashboard", "16:9", "wide16"):
            # v0.1.45: 强制 16:9 viewport（dashboard 自然长宽比）→ PIL scale 到 fb → 整页无黑边
            # 算法：viewport 短边 = fb 短边 × 1.0（即 viewport 的 height = fb height for 横向 fb），
            #        长边按 16:9 算出 → PIL 横向 squish 把 viewport 长边缩到 fb 长边
            # 1024×768 fb → viewport 1366×768（×0.75 horiz, ×1.0 vert，dashboard 完整填 fb，水平 squish ~25%）
            # 1920×1080 fb → viewport 1920×1080（16:9 正好匹配，无 squish）
            # 1280×720 fb → viewport 1280×720（16:9 匹配）
            if W >= H:
                win_h = H
                win_w = int(win_h * 16 / 9)
            else:
                win_w = W
                win_h = int(win_w * 16 / 9)
        else:
            win_w, win_h = W, H  # 未知字符串 → fallback match_fb
    else:
        win_w = int((bw_cfg or [1920, 1080])[0])
        win_h = int((bw_cfg or [1920, 1080])[1])
    # display_zoom 应用：zoom>1 → window 缩小 → 页面 CSS 像素更少 → fb 截图看起来放大
    # zoom<1 → window 放大 → 页面 CSS 像素更多 → fb 截图看起来缩小（看见更多内容）
    zoom = float(cfg.get("display_zoom", 1.0) or 1.0)
    if zoom <= 0:
        zoom = 1.0
    win_w = max(320, int(win_w / zoom))
    win_h = max(240, int(win_h / zoom))
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

    # ---- 启动 Chromium（带重试，不退出）----
    log_path = os.path.join(os.path.dirname(args.fb) or ".", "fb_chromium.log")
    # var 目录一般是 /var/apps/<pkg>/var；fb.log 旁写
    var_log = os.environ.get("TRIM_PKGVAR")
    if var_log:
        log_path = os.path.join(var_log, "fb_chromium.log")

    def _spawn_browser(cfg_):
        return Browser(
            window=(win_w, win_h),
            port=args.cdp_port,
            chromium_path=cfg_.get("browser_path", ""),
            scale=float(cfg_.get("browser_scale", 1.0)),
            timeout=int(cfg_.get("browser_timeout", 30)),
            hide_cursor=bool(cfg_.get("hide_cursor", True)),
            user_data_dir=default_profile,
        )

    # Chromium 启动重试：backoff 5s → 10s → 15s 上限（用户装好 chromium 后
    # 最多等 15s 就能看到画面，不需要等 30s）
    _retry_delays = [5, 10, 15]

    def _write_error_screen(title, detail):
        try:
            from PIL import Image, ImageDraw, ImageFont
            img = Image.new("RGB", (W, H), (40, 10, 10))
            d = ImageDraw.Draw(img)
            # 智能选字体：Latin + CJK 配合（核心修复：CJK 字体不含 ASCII 会渲染成 □）
            _latin_path = _pick_latin_font_path()
            _cjk_path = _pick_cjk_font_path()
            _big = max(28, W // 24)
            _sm = max(18, W // 38)
            f_l_big = ImageFont.truetype(_latin_path, _big) if _latin_path else None
            f_l_sm = ImageFont.truetype(_latin_path, _sm) if _latin_path else None
            f_c_big = ImageFont.truetype(_cjk_path, _big) if _cjk_path else f_l_big
            f_c_sm = ImageFont.truetype(_cjk_path, _sm) if _cjk_path else f_l_sm
            d.rectangle([(0, 0), (W, H)], outline=(248, 113, 113), width=4)
            _draw_text_mixed(d, (W // 2, H // 4), title,
                             f_l_big, f_c_big,
                             fill=(248, 113, 113), anchor="mm")
            # 错误详情（CJK-aware 换行 + mixed-font 渲染）
            wrapped = _wrap_text_cjk_mixed(
                detail, int(W * 0.85), f_l_sm, f_c_sm)
            y0 = int(H * 0.38)
            for i, line in enumerate(wrapped[:6]):
                _draw_text_mixed(d, (W // 2, y0 + i * (H // 14)), line,
                                 f_l_sm, f_c_sm,
                                 fill=(232, 238, 251), anchor="mm")
            # 直接给出修复命令
            fix1 = "在 NAS 上 SSH 执行："
            fix2 = "sudo apt install -y chromium python3-pil"
            fix3 = "安装完成后 fb_render 会自动检测（无需手动重启）"
            _draw_text_mixed(d, (W // 2, int(H * 0.78)), fix1,
                             f_l_sm, f_c_sm,
                             fill=(245, 158, 11), anchor="mm")
            _draw_text_mixed(d, (W // 2, int(H * 0.83)), fix2,
                             f_l_sm, f_c_sm,
                             fill=(252, 211, 77), anchor="mm")
            _draw_text_mixed(d, (W // 2, int(H * 0.92)), fix3,
                             f_l_sm, f_c_sm,
                             fill=(147, 165, 196), anchor="mm")
            fb.blit(img.convert("RGBA").tobytes("raw", "BGRA"))
        except Exception as ee:
            print("[fb] 写错误屏失败：%r" % ee, flush=True)

    def _wrap_text_cjk_mixed(s, max_px, latin_font, cjk_font):
        """CJK-aware 文本换行：按实际 getlength 测量（避免 Latin/CJK 估算不准）。"""
        if not s:
            return [s]
        out, cur = [], ""
        cur_w = 0.0
        for ch in s:
            f = cjk_font if _is_cjk(ch) else latin_font
            ch_w = f.getlength(ch) if f else (20 if _is_cjk(ch) else 10)
            if cur_w + ch_w > max_px and cur:
                out.append(cur)
                cur, cur_w = ch, ch_w
            else:
                cur += ch
                cur_w += ch_w
        if cur:
            out.append(cur)
        return out

    browser = _spawn_browser(cfg)
    while True:
        try:
            browser.start(log_path=log_path)
            browser.connect()
            print("[fb] Chromium ready (window=%dx%d)" % (win_w, win_h),
                  flush=True)
            break
        except Exception as e:
            delay = _retry_delays[min(main._spawn_attempts, len(_retry_delays) - 1)] \
                if hasattr(main, "_spawn_attempts") else 5
            main._spawn_attempts = getattr(main, "_spawn_attempts", 0) + 1
            err_msg = "Chromium 启动失败（#%d）" % main._spawn_attempts
            err_detail = str(e)[:200]
            print("[fb] %s，将在 %ds 后重试：%r"
                  % (err_msg, delay, e), flush=True)
            # 如果是「未找到 chromium」类错误，把详细诊断打到 fb.log
            if "未找到 chromium" in err_detail:
                try:
                    from dash_browser import find_chromium
                    _, finfo = find_chromium()
                    for e2 in finfo["errors"]:
                        print("[fb]   查找: %s" % e2, flush=True)
                except Exception:
                    pass
            _write_error_screen(err_msg, err_detail)
            try:
                browser.close()
            except Exception:
                pass
            time.sleep(delay)
            browser = _spawn_browser(cfg)
    main._spawn_attempts = 0

    # ---- 本地页面存储（fb 渲染器也要读 var/pages/）----
    pages_root = args.pages_dir or os.path.join(
        os.environ.get("TRIM_PKGVAR", os.path.join(os.getcwd(), "var")), "pages")
    page_store = dash_pages.PageStore(pages_root)
    # 从 args.api URL 解析 dashboard HTTP 端口（模板 URL 需要 127.0.0.1:<port>）
    _http_port = 8280
    try:
        from urllib.parse import urlparse
        u = urlparse(args.api or "")
        if u.port:
            _http_port = u.port
    except Exception:
        pass

    canvas = BrowserCanvas(W, H, browser, page_store, http_port=_http_port)
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
            # v0.1.48: 必须在 cfg 拿到后就立即算 _has_url_now —— 后续 line 1036 和 line 1049
            # 都会引用它。如果在用之前才赋值，Python 会把整个函数体的 _has_url_now 当作
            # 局部变量，导致 line 1036 触发 UnboundLocalError（v0.1.47 修复时埋下的 bug）。
            _pages_now = cfg.get("pages") or []
            _has_url_now = any(p.get("type") == "url" for p in _pages_now if isinstance(p, dict))
            # v0.1.35: 主循环只在「当前页面没有 per-page fit」时才覆盖 canvas._fit_mode，
            # 否则会覆盖 set_page() 里设置的 per-page fit（导致 fit 切换失效）。
            # 当前页面 = canvas._page（page 对象）或 pages 列表里 cycle 模式选中的页面。
            current_page = getattr(canvas, "_page", None)
            page_fit = (current_page.get("fit") or "none").lower() \
                if current_page and isinstance(current_page.get("fit"), str) \
                else "none"
            if _has_url_now:
                # v0.1.51: URL 页面**总是**强制 cover（无视 page_fit 覆盖和 display_fit 配置）——
                # 之前的 page_fit 优先逻辑会让用户保存的 per-page fit 覆盖我们的 cover，
                # 导致黑带还在。URL 页面只有一个合理的 fit 模式（cover = 铺满 fb 裁切左右），
                # 这里直接强制。
                canvas._fit_mode = "cover"
            elif page_fit == "none":
                # display_fit 热加载（不需要重启 Chromium）
                # 非 URL 页才走用户的 display_fit 设置（默认 stretch）
                canvas._fit_mode = (cfg.get("display_fit") or "stretch").lower()
                if canvas._fit_mode not in ("contain", "cover", "stretch"):
                    canvas._fit_mode = "stretch"
            # v0.1.35: url_kiosk_css 热加载。每帧把 cfg 上的最新值推给 canvas，
            # begin() 内会和 _kiosk_css_applied 比较并决定是否重新 set_kiosk_css。
            # 这样设置页改了 url_kiosk_css 立即生效，无需切页。
            canvas._kiosk_css_pending = cfg.get("url_kiosk_css", "") or ""
            # 计算目标窗口尺寸（受 browser_window + display_zoom 共同影响）
            # v0.1.46: 与冷启动一致 —— 只要有 URL 页就强制 match_dashboard
            # v0.1.48: _has_url_now 已在 cfg 读取后立即算好（见 line ~1023），这里直接复用。
            if _has_url_now:
                win = "match_dashboard"
            else:
                win = cfg.get("browser_window") or "match_fb"
            if isinstance(win, str):
                win_lower = win.lower()
                if win_lower in ("match_fb", "fb", "auto"):
                    new_w, new_h = W, H
                elif win_lower in ("match_fb_wide", "wide", "1.25x"):
                    new_w, new_h = int(W * 1.25), int(H * 1.25)
                elif win_lower in ("match_dashboard", "16:9", "wide16"):
                    if W >= H:
                        new_h = H
                        new_w = int(new_h * 16 / 9)
                    else:
                        new_w = W
                        new_h = int(new_w * 16 / 9)
                else:
                    new_w, new_h = W, H
            else:
                new_w = int(win[0])
                new_h = int(win[1])
            zoom_now = float(cfg.get("display_zoom", 1.0) or 1.0)
            if zoom_now <= 0:
                zoom_now = 1.0
            new_w = max(320, int(new_w / zoom_now))
            new_h = max(240, int(new_h / zoom_now))
            # 窗口尺寸或旋转变了，都需要重建 Browser（rotate 用 PIL 旋转贴图；
            # 尺寸用 Chromium 重新启动确保截图大小正确）
            cur_w, cur_h = browser.window[0], browser.window[1]
            need_restart = (new_w, new_h) != (cur_w, cur_h)
            if new_rotate != rotate:
                rotate = new_rotate
                need_restart = True
            if need_restart:
                if (new_w, new_h) != (cur_w, cur_h):
                    print("[fb] 窗口尺寸变化，重启 Chromium (%dx%d → %dx%d)" %
                          (cur_w, cur_h, new_w, new_h),
                          flush=True)
                    browser.close()
                    browser = Browser(
                        window=(new_w, new_h),
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
                        canvas = BrowserCanvas(W, H, browser, page_store,
                                              http_port=_http_port)
                        canvas.set_page(pages[0],
                                        kiosk_css=cfg.get("url_kiosk_css", ""))
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

            # 如果 Chromium 死了，尝试重启（一直重试，配合外层 watchdog）
            if not browser.alive():
                main._restart_attempts = getattr(main, "_restart_attempts", 0)
                main._restart_attempts += 1
                delay = min(30, 2 * main._restart_attempts)
                print("[fb] Chromium 不在，重启尝试 #%d（%ds 后）"
                      % (main._restart_attempts, delay), flush=True)
                try:
                    # 重建 Browser 实例（start_new_session 后的旧 Chromium 已死透）
                    browser = Browser(
                        window=(win_w, win_h),
                        port=args.cdp_port,
                        chromium_path=cfg.get("browser_path", ""),
                        scale=float(cfg.get("browser_scale", 1.0)),
                        timeout=int(cfg.get("browser_timeout", 30)),
                        hide_cursor=bool(cfg.get("hide_cursor", True)),
                        user_data_dir=default_profile,
                    )
                    browser.start(log_path=log_path)
                    browser.connect()
                    canvas = BrowserCanvas(W, H, browser, page_store,
                                          http_port=_http_port)
                    canvas.set_page(pages[0] if pages else None,
                                    kiosk_css=cfg.get("url_kiosk_css", ""))
                    main._restart_attempts = 0
                except Exception as e:
                    print("[fb] 重启失败：%r" % e, flush=True)
                    # 画错误屏给用户看到（fb0 上能看到排查线索）
                    try:
                        canvas.img.paste(pal["bg"], [0, 0, W, H])
                        from PIL import ImageDraw
                        ImageDraw.Draw(canvas.img).text(
                            (20, 20),
                            "Chromium 启动失败（#%d）：%s\n请检查 /var/apps/com.fnos.kiosk/var/fb_chromium.log"
                            % (main._restart_attempts, str(e)[:60]),
                            fill=pal["danger"])
                        fb.blit(canvas.to_bgra(rotate))
                    except Exception:
                        pass
                    time.sleep(delay)
                    continue

            # v0.1.39: 每帧都 set_page（幂等，URL 没变就不重导航）。之前只在 page.id 变化
# 时调用，导致 zoom/fit/url_kiosk_css 改了不生效——必须重启应用才看到效果。
            canvas.set_page(page, kiosk_css=cfg.get("url_kiosk_css", ""))

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
                # cycle 模式用真实 idx，single 模式 idx=0（HUD footer 内部对
                # is_single=True 会改成「SINGLE URL MODE」字样，不需要 idx）
                foot_idx = idx if not is_single else 0
                hud.footer(n_cycle, idx=foot_idx, rotate_sec=rotate_sec,
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