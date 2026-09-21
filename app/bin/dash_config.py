#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""fnOS 浏览器屏 —— 配置层（etc/config.json 读写与白名单校验）。

数据模型：
  - 默认模式：cycle（多页轮换）/ single（单 URL 独占全屏）
  - pages[]：每个元素是一个 {id, name, type, url|path, mode, refresh_seconds, zoom, enabled}
  - fb_*：显示器参数（与 fnos-dashboard 同语义）

所有用户输入必须过 _sanitize：URL 走白名单（默认仅 http/https），
host 走正则防 SSRF，id 限定 [a-z0-9_-]。
"""

import json
import os
import re
import threading

APP_VERSION = "0.1.36"  # 同步 manifest.version，与 fnpack 实际打包一致
THEMES = ("midnight", "graphite", "emerald", "solar", "sakura", "light")
_ID_RE = re.compile(r"[a-z0-9_-]{1,32}")
_URL_RE = re.compile(r"^https?://[^\s]{1,2048}$", re.IGNORECASE)
_HOST_RE = re.compile(r"^[a-z0-9.-]{3,100}$", re.IGNORECASE)
_PATH_RE = re.compile(r"^[A-Za-z0-9_./-]{1,256}$")
# 浏览器可能访问的目标 host 黑名单（防 SSRF）：仅 RFC1918 / loopback 默认被禁，
# 需要时通过 allow_private_hosts 放行
def _extract_host(url):
    """从 http(s) URL 抽出 host（去掉 scheme、路径、端口）。失败返回 ''。"""
    if not isinstance(url, str):
        return ""
    u = url.strip()
    for sch in ("http://", "https://", "HTTP://", "HTTPS://"):
        if u.startswith(sch):
            u = u[len(sch):]
            break
    else:
        return ""
    # 取到第一个 / : ? #
    for sep in ("/", ":", "?", "#"):
        if sep in u:
            u = u.split(sep, 1)[0]
    return u.lower()


def _is_private_host(host):
    """RFC1918 / loopback 判定（数值匹配，避免依赖 host 字符串前缀正则误判）。"""
    if not host:
        return False
    if host == "localhost" or host == "0.0.0.0" or host == "::" or host == "::1":
        return True
    # IPv6 [::1] / [::]
    if host.startswith("[") and host.endswith("]"):
        inner = host[1:-1].lower()
        return inner in ("::1", "::", "0:0:0:0:0:0:0:1", "0:0:0:0:0:0:0:0")
    # IPv4
    parts = host.split(".")
    if len(parts) == 4:
        try:
            nums = [int(p) for p in parts]
            if all(0 <= n <= 255 for n in nums):
                a, b = nums[0], nums[1]
                if a == 10:
                    return True
                if a == 127:
                    return True
                if a == 172 and 16 <= b <= 31:
                    return True
                if a == 192 and b == 168:
                    return True
                if a == 169 and b == 254:
                    return True
                if a == 0:
                    return True
                if a >= 224:  # multicast / reserved
                    return True
        except ValueError:
            pass
    return False

DEFAULT_PAGE = {
    "id": "",
    "name": "",
    "type": "url",            # url | html_file | media_file
    "url": "",
    "path": "",
    "mode": "cycle",           # cycle | single
    "refresh_seconds": 0,     # 0=不自动刷新；>0 按秒重新加载
    "zoom": 1.0,              # 0.5–2.0
    "enabled": True,
}

# v0.1.34 默认注入的「URL 全屏化」CSS —— 把浏览器默认的 html/body margin
# 清掉，强制铺满 1024×768 viewport。Chromium 视口本身已经是 1024×768（match_fb
# 或自定义尺寸），但 URL 自带的 body { margin: 8px }、<html> 没设 100% 高度、
# 子元素 fixed width 等都会让 URL 看起来「没填满」。!important 覆盖页面自身样式。
#
# 用户在 URL 设置 → 「URL 全屏 CSS」里可改/清空。空字符串 = 禁用注入。
# 注意：定义必须在 DEFAULT_CONFIG 之前，否则 DEFAULT_CONFIG 引用会 NameError。
DEFAULT_URL_KIOSK_CSS = (
    "html,body{margin:0!important;padding:0!important;"
    "width:100%!important;height:100%!important;"
    "background:#000!important;overflow:hidden!important}"
    "body>*{max-width:100vw!important;max-height:100vh!important;"
    "box-sizing:border-box!important}"
)


DEFAULT_CONFIG = {
    "theme": "midnight",
    "accent": "",
    "default_mode": "cycle",   # 缺省页面模式（单 URL 兜底用）
    "rotate_seconds": 30,
    "fb_enabled": False,
    "fb_rotate": 0,
    "display_fit": "stretch",  # 默认填满 fb（解决 16:9 内容在 4:3 fb 上的 letterbox + 让 zoom 立刻可见）
    "display_zoom": 1.0,       # URL 页面缩放（1.0=原始，>1 放大（页面 CSS 像素更少 → 内容看起来更大），<1 缩小）
    "screen_inches": 0,
    "browser_path": "",        # 自定义 chromium 路径（空则自动找）
    "browser_window": "match_fb",   # 浏览器视口尺寸；"match_fb" 自动等于 fb0 物理分辨率（推荐）；或 [w, h]
    "browser_scale": 1.0,      # 设备像素比（HiDPI 屏可调 1.5/2.0 让字体更清晰）
    "browser_timeout": 30,     # Page.navigate 超时秒
    "chromium_profile_dir": "", # 自定义 profile 路径（留空 = var/chromium-profile，自动持久化）
    "allow_private_hosts": False,    # 显式开启后才允许 192.168 / localhost
    "hide_cursor": True,
    "url_kiosk_css": DEFAULT_URL_KIOSK_CSS,  # 注入到每个 URL 页面的 CSS；空 = 不注入
    "pages": [],
}


def _writable_dir(path):
    try:
        os.makedirs(path, exist_ok=True)
        return os.access(path, os.W_OK)
    except OSError:
        return False


def _clip_str(v, n):
    return str(v or "")[:n]


def _clip_float(v, lo, hi, default):
    try:
        return min(hi, max(lo, float(v)))
    except (TypeError, ValueError):
        return default


def _clip_int(v, lo, hi, default):
    try:
        return min(hi, max(lo, int(v)))
    except (TypeError, ValueError):
        return default


def _bool(v, default=False):
    return bool(v) if isinstance(v, bool) else default


def _sanitize_page(raw, allow_private):
    p = dict(DEFAULT_PAGE)
    if not isinstance(raw, dict):
        return None
    pid = _clip_str(raw.get("id"), 32)
    if not _ID_RE.fullmatch(pid):
        return None
    p["id"] = pid
    p["name"] = _clip_str(raw.get("name"), 48) or pid
    ptype = raw.get("type")
    # v0.1.30: 移除「内置模板」功能 (用户反馈模板在不同 fb / display_zoom 下表现不稳，
    # 且 Chromium 直接打开 PNG 经常白屏)。旧配置里的 type=template 一律丢弃（返回 None
    # 让 _merge_pages 跳过），不再尝试转换成 url 保留——避免出现「已配置但无页面」状态。
    if ptype == "template":
        return None
    if ptype in ("url", "html_file", "media_file"):
        p["type"] = ptype
    else:
        p["type"] = "url"
    if p["type"] == "url":
        url = _clip_str(raw.get("url"), 2048)
        if not _URL_RE.match(url):
            return None
        if not allow_private and _is_private_host(_extract_host(url)):
            return None
        p["url"] = url
        p["path"] = ""
    else:
        path = _clip_str(raw.get("path"), 256)
        if not _PATH_RE.match(path):
            return None
        # html_file / media_file 类型 path 必须是相对路径（不含 ..）
        if ".." in path.split("/"):
            return None
        p["url"] = ""
        p["path"] = path
    p["mode"] = raw.get("mode") if raw.get("mode") in ("cycle", "single") else "cycle"
    p["refresh_seconds"] = _clip_int(raw.get("refresh_seconds"), 0, 86400, 0)
    p["zoom"] = _clip_float(raw.get("zoom"), 0.3, 3.0, 1.0)
    # v0.1.35: per-page 画面适配模式（contain/cover/stretch/none）。
    # "none"（默认）→ 走 cfg.display_fit；显式设置 → 覆盖全局（图片型 wrapper
    # 也会按 fit 重新生成）。
    p["fit"] = raw.get("fit") if raw.get("fit") in \
        ("contain", "cover", "stretch", "none", None, "") else "none"
    if not p["fit"]:
        p["fit"] = "none"
    p["enabled"] = _bool(raw.get("enabled"), True)
    return p


class Config:
    def __init__(self, etc_path, var_dir):
        self.var_dir = var_dir
        self.path = etc_path if _writable_dir(os.path.dirname(etc_path)) \
            else os.path.join(var_dir, "config.json")
        self._lock = threading.Lock()
        self._on_url_saved = (lambda u: None)  # 由 dash_http 注入
        self._data = self._load()

    def _load(self):
        candidates = [self.path]
        var_override = os.path.normpath(os.path.join(self.var_dir, "config.json"))
        if var_override != self.path and os.path.isfile(var_override):
            candidates.append(var_override)
        data = self._merge_files(candidates)
        # 一次性迁移：contain / cover → stretch。
        # contain 让 fb0 内永远 letterbox；cover 会裁切——两者都让「zoom 改了看不出效果」
        # 「画面没充满」反馈不断。每个 dashboard 启动都检查 + 落日志，确保用户在 fb.log
        # 里能看到「v0.1.25 migration ran: contain -> stretch」一行，方便排障。
        marker = os.path.join(self.var_dir, ".migrated_to_stretch")
        cur = data.get("display_fit")
        if cur in (None, "", "contain", "cover") \
                and not os.path.isfile(marker):
            data["display_fit"] = "stretch"
            try:
                with open(marker, "w", encoding="utf-8") as f:
                    f.write("v0.1.25 migration: display_fit %s -> stretch\n"
                            % (cur or "default"))
            except OSError:
                pass
            # 顺手落盘（用 self.path 以保证写到 etc_dir 或 var_dir）
            try:
                tmp = self.path + ".tmp"
                with open(tmp, "w", encoding="utf-8") as f:
                    json.dump(self._sanitize(data), f,
                              ensure_ascii=False, indent=2)
                os.replace(tmp, self.path)
            except OSError:
                pass
            # 把迁移活动落到 fb.log（dashboard 启动还没建 log 时降级到 initdb.log）
            for _lp in ("fb.log",):
                try:
                    import time as _t
                    with open(os.path.join(self.var_dir, _lp), "a",
                              encoding="utf-8") as _f:
                        _f.write("[config %s] migration: display_fit %s -> stretch\n"
                                 % (_t.strftime("%m-%d %H:%M:%S"),
                                    cur or "default"))
                except OSError:
                    pass
        return data

    def _merge_files(self, paths):
        data = json.loads(json.dumps(DEFAULT_CONFIG))
        for p in paths:
            try:
                with open(p, "r", encoding="utf-8") as f:
                    patch = json.load(f)
                if isinstance(patch, dict):
                    data.update(patch)
            except (OSError, ValueError):
                continue
        return self._sanitize(data)

    def _sanitize(self, data):
        out = dict(DEFAULT_CONFIG)
        out.update(data)
        # 主题 / 强调色
        if out.get("theme") not in THEMES:
            out["theme"] = DEFAULT_CONFIG["theme"]
        accent = out.get("accent") or ""
        if not isinstance(accent, str) or not re.fullmatch(r"#[0-9a-fA-F]{6}", accent):
            accent = ""
        out["accent"] = accent.lower()
        # 模式
        out["default_mode"] = out.get("default_mode") if out.get("default_mode") in ("cycle", "single") else "cycle"
        # 数值类
        out["rotate_seconds"] = _clip_int(out.get("rotate_seconds"), 5, 300, 30)
        out["fb_rotate"] = out.get("fb_rotate") if out.get("fb_rotate") in (0, 90, 180, 270) else 0
        out["screen_inches"] = _clip_float(out.get("screen_inches"), 0.0, 200.0, 0.0)
        out["browser_timeout"] = _clip_int(out.get("browser_timeout"), 5, 120, 30)
        out["browser_scale"] = _clip_float(out.get("browser_scale"), 0.5, 3.0, 1.0)
        out["display_zoom"] = _clip_float(out.get("display_zoom"), 0.5, 3.0, 1.0)
        # 视口
        win = out.get("browser_window") or "match_fb"
        if isinstance(win, str) and win.lower() in ("match_fb", "fb", "auto"):
            out["browser_window"] = "match_fb"
        else:
            if not (isinstance(win, list) and len(win) == 2):
                win = [1920, 1080]
            out["browser_window"] = [_clip_int(win[0], 320, 7680, 1920),
                                      _clip_int(win[1], 240, 4320, 320)]
        out["browser_path"] = _clip_str(out.get("browser_path"), 256)
        profile = _clip_str(out.get("chromium_profile_dir"), 256)
        # profile_dir 只接受绝对路径且不能含 ..（防路径穿越）
        if profile and (not profile.startswith("/") or ".." in profile.split("/")):
            profile = ""
        out["chromium_profile_dir"] = profile
        out["fb_enabled"] = bool(out.get("fb_enabled"))
        out["hide_cursor"] = bool(out.get("hide_cursor"))
        out["allow_private_hosts"] = bool(out.get("allow_private_hosts"))
        # v0.1.34: URL 全屏注入 CSS（裁剪到 4 KB 防止恶意 config 把脚本注入搞成 DOS）
        out["url_kiosk_css"] = _clip_str(out.get("url_kiosk_css"), 4096) or ""
        # 页面列表：去重 id + 白名单
        pages = out.get("pages") or []
        seen = set()
        clean = []
        for raw in pages if isinstance(pages, list) else []:
            p = _sanitize_page(raw, out["allow_private_hosts"])
            if p is None or p["id"] in seen:
                continue
            seen.add(p["id"])
            clean.append(p)
        out["pages"] = clean
        return out

    def get(self):
        with self._lock:
            return json.loads(json.dumps(self._data))

    def update(self, patch):
        """校验并合并补丁，原子写盘。返回 (ok, error)。"""
        clean = {}
        # 主题 / 强调色
        if "theme" in patch:
            if patch["theme"] not in THEMES:
                return False, "不支持的主题：%r" % (patch["theme"],)
            clean["theme"] = patch["theme"]
        if "accent" in patch:
            a = patch["accent"] or ""
            if not isinstance(a, str) or (a != "" and not re.fullmatch(r"#[0-9a-fA-F]{6}", a)):
                return False, "强调色格式无效"
            clean["accent"] = a.lower()
        if "default_mode" in patch:
            if patch["default_mode"] not in ("cycle", "single"):
                return False, "默认模式仅支持 cycle / single"
            clean["default_mode"] = patch["default_mode"]
        if "rotate_seconds" in patch:
            clean["rotate_seconds"] = _clip_int(patch["rotate_seconds"], 5, 300, 30)
        if "screen_inches" in patch:
            clean["screen_inches"] = _clip_float(patch["screen_inches"], 0.0, 200.0, 0.0)
        if "fb_rotate" in patch:
            try:
                rotate = int(patch["fb_rotate"])
            except (TypeError, ValueError):
                return False, "显示方向无效"
            if rotate not in (0, 90, 180, 270):
                return False, "显示方向仅支持 0/90/180/270"
            clean["fb_rotate"] = rotate
        if "display_fit" in patch:
            v = str(patch["display_fit"] or "").lower()
            if v not in ("contain", "cover", "stretch"):
                return False, "画面适配模式仅支持 contain/cover/stretch"
            clean["display_fit"] = v
        if "display_zoom" in patch:
            clean["display_zoom"] = _clip_float(patch["display_zoom"], 0.5, 3.0, 1.0)
        if "fb_enabled" in patch:
            clean["fb_enabled"] = bool(patch["fb_enabled"])
        if "hide_cursor" in patch:
            clean["hide_cursor"] = bool(patch["hide_cursor"])
        if "allow_private_hosts" in patch:
            clean["allow_private_hosts"] = bool(patch["allow_private_hosts"])
        if "browser_path" in patch:
            clean["browser_path"] = _clip_str(patch["browser_path"], 256)
        if "chromium_profile_dir" in patch:
            pd = _clip_str(patch["chromium_profile_dir"], 256)
            if pd and (not pd.startswith("/") or ".." in pd.split("/")):
                return False, "chromium_profile_dir 必须是绝对路径且不含 '..'"
            clean["chromium_profile_dir"] = pd
        if "browser_timeout" in patch:
            clean["browser_timeout"] = _clip_int(patch["browser_timeout"], 5, 120, 30)
        if "browser_scale" in patch:
            clean["browser_scale"] = _clip_float(patch["browser_scale"], 0.5, 3.0, 1.0)
        if "url_kiosk_css" in patch:
            css = _clip_str(patch["url_kiosk_css"], 4096)
            # 拒绝任何 <script> / on*= / javascript: / expression() 之类
            # （即便 set_kiosk_css 只是塞 <style>，防御一下）
            if css and re.search(r"<\s*script|on\w+\s*=|javascript\s*:|expression\s*\(",
                                  css, re.IGNORECASE):
                return False, "url_kiosk_css 含不安全内容（不允许 <script> / on*= / javascript:）"
            clean["url_kiosk_css"] = css
        if "browser_window" in patch:
            w = patch["browser_window"]
            if isinstance(w, str) and w.lower() in ("match_fb", "fb", "auto"):
                clean["browser_window"] = "match_fb"
            else:
                if not (isinstance(w, list) and len(w) == 2):
                    return False, "browser_window 必须是 [W, H] 数组或 'match_fb'"
                clean["browser_window"] = [_clip_int(w[0], 320, 7680, 1920),
                                           _clip_int(w[1], 240, 4320, 320)]
        if "pages" in patch:
            pages = patch["pages"]
            if not isinstance(pages, list):
                return False, "页面列表必须是数组"
            allow_private = bool(clean.get("allow_private_hosts",
                                          self._data.get("allow_private_hosts")))
            seen = set()
            clean_pages = []
            for raw in pages:
                p = _sanitize_page(raw, allow_private)
                if p is None or p["id"] in seen:
                    continue
                seen.add(p["id"])
                clean_pages.append(p)
            clean["pages"] = clean_pages

        with self._lock:
            data = dict(self._data)
            data.update(clean)
            data = self._sanitize(data)
            tmp = self.path + ".tmp"
            try:
                with open(tmp, "w", encoding="utf-8") as f:
                    json.dump(data, f, ensure_ascii=False, indent=2)
                os.replace(tmp, self.path)
            except OSError as e:
                return False, "配置写入失败：%s" % e
            self._data = data
        # 记录最近使用的 URL（settings 端可以读）
        try:
            seen = set()
            for p in (data.get("pages") or []):
                if p.get("type") == "url" and p.get("url"):
                    if p["url"] not in seen:
                        seen.add(p["url"])
                        self._on_url_saved(p["url"])
        except Exception:
            pass
        return True, ""