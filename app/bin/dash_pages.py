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
        """写二进制（图片 / 视频）。data 必须为 bytes 或 base64 str。"""
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

    def delete(self, name):
        full = self._full(name)
        if not os.path.exists(full):
            raise ValueError("文件不存在")
        os.unlink(full)

    def to_file_url(self, name):
        """把 var/pages/<filename> 转成 file:// URL 供 Chromium 加载。"""
        full = os.path.realpath(self._full(name))
        # 防路径穿越校验：必须仍在 self.root 下
        root_real = os.path.realpath(self.root)
        if not (full == root_real or full.startswith(root_real + os.sep)):
            raise ValueError("文件路径非法")
        # file URL 用 / 分隔
        url = "file://" + full.replace(os.sep, "/")
        return url


def list_visible_pages(cfg):
    """从全量配置里筛出启用的页面，供 fb_render 使用。"""
    pages = []
    for p in (cfg.get("pages") or []):
        if not p.get("enabled"):
            continue
        if p["type"] == "url":
            if not p.get("url"):
                continue
        elif p["type"] in ("html_file", "media_file"):
            if not p.get("path"):
                continue
        elif p["type"] == "template":
            if not p.get("template"):
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
    """把页面记录转换成 Chromium 真正加载的 URL（含 file:// 转写、模板拼接）。"""
    if page["type"] in ("html_file", "media_file"):
        try:
            return page_store.to_file_url(page["path"])
        except (ValueError, OSError):
            return "about:blank"
    if page["type"] == "template":
        # 模板放在 app/web/templates/<name>.html，由 dashboard HTTP 服务返回
        # Chromium 通过 127.0.0.1:<HTTP_PORT> 访问，避免 file:// 跨域限制
        name = page.get("template") or "clock"
        # 限制名字在白名单内
        if not re.fullmatch(r"[a-z0-9_-]{1,32}", name):
            return "about:blank"
        return "http://127.0.0.1:%d/templates/%s.html" % (http_port, name)
    return page.get("url") or "about:blank"