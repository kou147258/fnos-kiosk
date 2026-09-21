#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""fnOS 浏览器屏 —— 页面源。

支持的页面类型：
  - url      ：远程 URL。fb_render 通过 Chromium CDP 导航 + Page.captureScreenshot 取帧
  - html_file：本地 HTML 文件，存放在 var/pages/ 下，通过 file:// URL 提供
  - media_file：本地媒体文件（图片 / 视频 / SVG），与 html_file 同样路径解析方式；
                 通过 Chromium 直接渲染（图片） 或 <video autoplay> 播放（视频）

PageStore 提供：
  - 本地 HTML / 媒体 文件的 CRUD（安装 / 列出 / 删除 / 读取）
  - URL 解析与 file:// 路径转 URL
  - 类型识别（按扩展名返回 kind: html | image | video | other）
"""

import base64
import datetime
import mimetypes
import os
import re
import shutil
import threading

# 允许的文件扩展名白名单（防恶意扩展名绕过 MIME 推断）
ALLOWED_EXTS = frozenset({
    # Web
    "html", "htm", "svg",
    # 图片
    "jpg", "jpeg", "png", "gif", "webp", "bmp", "ico",
    # 视频
    "mp4", "webm", "ogg", "mov",
})
# 单文件大小上限（16MB：图片和短视频都够）
MAX_FILE_BYTES = 16 * 1024 * 1024

_FILENAME_RE = re.compile(r"[A-Za-z0-9_.-]{1,64}")


def safe_filename(name):
    """检查文件名安全 + 后缀在白名单内。返回清理后的文件名或 ''。"""
    name = (name or "").strip()
    if not name:
        return ""
    if not _FILENAME_RE.fullmatch(name):
        return ""
    # 拆分 basename + ext
    base, ext = os.path.splitext(name)
    ext = ext.lstrip(".").lower()
    if not ext or ext not in ALLOWED_EXTS:
        return ""
    if not base:
        return ""
    return name


def kind_of(name):
    """按扩展名返回文件类别：html | image | video | other。"""
    base, ext = os.path.splitext(name or "")
    ext = ext.lstrip(".").lower()
    if ext in ("html", "htm", "svg"):
        return "html"
    if ext in ("jpg", "jpeg", "png", "gif", "webp", "bmp", "ico"):
        return "image"
    if ext in ("mp4", "webm", "ogg", "mov"):
        return "video"
    return "other"


def mime_of(name):
    """按文件名猜 MIME；缺省 application/octet-stream。"""
    m, _ = mimetypes.guess_type(name or "")
    return m or "application/octet-stream"


class PageStore:
    """var/pages/ 下的本地文件管理。"""

    def __init__(self, root):
        self.root = root
        self._lock = threading.Lock()
        try:
            os.makedirs(self.root, exist_ok=True)
        except OSError:
            pass

    def _full(self, name):
        if not safe_filename(name):
            raise ValueError(
                "非法文件名（限 [A-Za-z0-9_.-]{1,64}，扩展名必须为："
                + ", ".join(sorted(ALLOWED_EXTS)) + "）")
        return os.path.join(self.root, name)

    def list(self):
        out = []
        try:
            for fn in sorted(os.listdir(self.root)):
                if not safe_filename(fn):
                    continue  # 跳过非白名单文件（如被用户手动塞进的 .sh）
                full = os.path.join(self.root, fn)
                if not os.path.isfile(full):
                    continue
                st = os.stat(full)
                out.append({
                    "name": fn,
                    "size": st.st_size,
                    "mtime": st.st_mtime,
                    "kind": kind_of(fn),
                    "mime": mime_of(fn),
                })
        except OSError:
            pass
        return out

    def read(self, name):
        """读文本文件（HTML/SVG 等）。二进制文件请用 read_bytes。"""
        full = self._full(name)
        try:
            with open(full, "r", encoding="utf-8") as f:
                return f.read()
        except OSError:
            return None

    def read_bytes(self, name):
        """读二进制文件。返回 bytes 或 None。"""
        full = self._full(name)
        try:
            with open(full, "rb") as f:
                return f.read()
        except OSError:
            return None

    def write(self, name, content):
        """写文本内容（向后兼容）。二进制请用 write_bytes。"""
        full = self._full(name)
        if not isinstance(content, str):
            raise ValueError("内容必须是字符串")
        encoded = content.encode("utf-8")
        if len(encoded) > MAX_FILE_BYTES:
            raise ValueError("文件过大（上限 %d MB）"
                             % (MAX_FILE_BYTES // (1024 * 1024)))
        tmp = full + ".tmp"
        with open(tmp, "wb") as f:
            f.write(encoded)
        os.replace(tmp, full)

    def write_bytes(self, name, data):
        """写二进制（图片 / 视频）。data 必须为 bytes 或 base64 str。

        v0.1.33：媒体文件（image/video）会同时生成 `_wrap_<basename>.html`
        包裹层，用 CSS object-fit:contain 让 Chromium 把图片/视频填满 viewport
        —— 直接打开 PNG/JPG 时 Chromium 默认按原始像素居中、周围留黑边，
        那不是 letterbox，是浏览器的图像 viewer 行为。
        """
        full = self._full(name)
        if isinstance(data, str):
            # base64 解码
            try:
                data = base64.b64decode(data, validate=True)
            except (ValueError, TypeError) as e:
                raise ValueError("base64 解码失败：%s" % e)
        if not isinstance(data, (bytes, bytearray)):
            raise ValueError("二进制内容必须是 bytes")
        if len(data) > MAX_FILE_BYTES:
            raise ValueError("文件过大（上限 %d MB）"
                             % (MAX_FILE_BYTES // (1024 * 1024)))
        tmp = full + ".tmp"
        with open(tmp, "wb") as f:
            f.write(bytes(data))
        os.replace(tmp, full)
        # 媒体文件 → 同时生成 wrapper HTML（让图片/视频填满 viewport）
        if kind_of(name) in ("image", "video"):
            self._write_wrapper(name, kind_of(name))

    def _write_wrapper(self, name, kind):
        """给媒体文件生成 _wrap_<basename>.html，CSS 让 img/video 填满 viewport。

        HTML 结构最小：100vw × 100vh 容器，img/video 用 object-fit:contain
        保比例（不裁切），background:#000 让非图像区显黑。
        """
        if not safe_filename(name):
            return
        base, _ = os.path.splitext(name)
        wrap_name = "_wrap_" + base + ".html"
        wrap_full = self._full(wrap_name)
        # 用 absolute file:// 引用源文件
        src_full = os.path.realpath(self._full(name))
        src_url = "file://" + src_full.replace(os.sep, "/")
        if kind == "image":
            tag = '<img src="%s" alt="">' % src_url
        else:
            # video 需 muted 才能 autoplay（headless Chromium 限制）
            tag = ('<video src="%s" autoplay loop muted playsinline></video>'
                   % src_url)
        # 文件名做 title（HTML escape）
        import html as _html
        title = _html.escape(name)
        body = (
            '<!DOCTYPE html>\n'
            '<html><head><meta charset="UTF-8">\n'
            '<title>%s</title>\n'
            '<style>\n'
            'html,body{margin:0;padding:0;width:100vw;height:100vh;'
            'overflow:hidden;background:#000}\n'
            'img,video{width:100vw;height:100vh;'
            'object-fit:contain;display:block}\n'
            '</style></head>\n'
            '<body>%s</body></html>\n'
        ) % (title, tag)
        tmp = wrap_full + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            f.write(body)
        os.replace(tmp, wrap_full)

    def delete(self, name):
        """删除文件 + 同名 wrapper（如果有）。"""
        full = self._full(name)
        if not os.path.exists(full):
            raise ValueError("文件不存在")
        os.unlink(full)
        # 同步删掉 _wrap_*.html
        base, _ = os.path.splitext(name)
        wrap_name = "_wrap_" + base + ".html"
        wrap_full = self._full(wrap_name)
        try:
            if os.path.isfile(wrap_full):
                os.unlink(wrap_full)
        except OSError:
            pass

    def to_file_url(self, name):
        """把 var/pages/<filename> 转成 file:// URL 供 Chromium 加载。

        对媒体文件（image/video）返回 wrapper HTML 的 URL——wrapper 里有
        CSS 让 img/video object-fit:contain 填满 viewport，避免 Chromium
        默认 viewer 的「按原始像素居中 + 周围黑边」。
        """
        full = os.path.realpath(self._full(name))
        # 防路径穿越校验：必须仍在 self.root 下
        root_real = os.path.realpath(self.root)
        if not (full == root_real or full.startswith(root_real + os.sep)):
            raise ValueError("文件路径非法")
        # 媒体文件 → wrapper URL（如果存在）
        if kind_of(name) in ("image", "video"):
            base, _ = os.path.splitext(name)
            wrap_name = "_wrap_" + base + ".html"
            wrap_full = os.path.realpath(self._full(wrap_name))
            if os.path.isfile(wrap_full):
                return "file://" + wrap_full.replace(os.sep, "/")
        # 普通 HTML / SVG / 其他 → 直接 file://
        url = "file://" + full.replace(os.sep, "/")
        return url


def list_visible_pages(cfg):
    """从全量配置里筛出启用的页面，供 fb_render 使用。"""
    pages = []
    for p in (cfg.get("pages") or []):
        if not p.get("enabled"):
            continue
        # v0.1.30: 移除内置模板支持（已废弃）。type=template 不会到这里（_sanitize_page
        # 已经丢弃），但保留防御性判断以防外部直接构造的 page。
        if p.get("type") == "template":
            continue
        if p["type"] == "url":
            if not p.get("url"):
                continue
        elif p["type"] in ("html_file", "media_file"):
            if not p.get("path"):
                continue
        else:
            continue
        pages.append(p)
    if not pages:
        # 单 URL 模式 + 没有任何 URL 时的兜底：渲染一条「请配置 URL」提示
        pages = [{
            "id": "_empty",
            "name": "未配置页面",
            "type": "url",
            "url": "about:blank",
            "mode": cfg.get("default_mode", "cycle"),
            "refresh_seconds": 0,
            "zoom": 1.0,
            "enabled": True,
        }]
    return pages


def find_single_page(pages):
    """单 URL 模式下：返回 mode='single' 的第一个页面；否则按列表第一个。"""
    for p in pages:
        if p.get("mode") == "single":
            return p
    return pages[0] if pages else None


def resolve_url(page, page_store, http_port=0):
    """把页面记录转换成 Chromium 真正加载的 URL（含 file:// 转写）。"""
    # v0.1.30: 移除 template 类型支持——已无内置模板。
    if page.get("type") == "template":
        return "about:blank"
    if page["type"] in ("html_file", "media_file"):
        try:
            return page_store.to_file_url(page["path"])
        except (ValueError, OSError):
            return "about:blank"
    return page.get("url") or "about:blank"