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

APP_VERSION = "0.1.59"  # 同步 manifest.version，与 fnpack 实际打包一致
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

# v0.1.43 默认注入的「URL 全屏化」CSS —— 把浏览器默认的 html/body margin
# 清掉，强制铺满 viewport + 中文字体 fallback 链 + 强制 dashboard 容器宽高 100%。
# Chromium 视口本身是 match_fb_wide（1280×960 for 1024×768 fb）→ 等比缩到 fb。
#
# 用户在 URL 设置 → 「URL 全屏 CSS」里可改/清空。空字符串 = 禁用注入。
# 注意：定义必须在 DEFAULT_CONFIG 之前，否则 DEFAULT_CONFIG 引用会 NameError。
DEFAULT_URL_KIOSK_CSS = (
    # 基础：清 margin / 100% 宽高 / 强制 overflow:hidden + box-sizing
    "html,body{margin:0!important;padding:0!important;"
    "width:100%!important;height:100%!important;"
    "background:#000!important;overflow:hidden!important;"
    "box-sizing:border-box!important}"
    # v0.1.54: 恢复 body > * 强制 100vw × 100vh（之前 v0.1.51 改成 height:auto
    # 是为了配合 auto-fit 测真实高度；现在 v0.1.54 取消了 auto-fit 改用用户手动 zoom，
    # body > * 应该强制填满 viewport，dashboard 内容自然铺满 1365×768 视口）。
    # 用户调 zoom 时，dashboard 内容 transform: scale 居中缩放（超出部分靠
    # body overflow:hidden 裁切），viewport 大小不变。
    "body>*{width:100vw!important;height:100vh!important;"
    "margin:0!important;padding:0!important;"
    "max-width:none!important;max-height:none!important;"
    "box-sizing:border-box!important}"
    # body 第二层（孙元素）也强制铺满（防止 dashboard 第一层是 .outer 第二层是 .inner）
    "body>*>*{width:100%!important;height:100%!important;"
    "max-width:none!important;max-height:none!important;"
    "box-sizing:border-box!important}"
    # 中文字体 fallback —— Debian NAS 默认不含中文字体，
    # 这里给一个长 fallback 链，匹配 apt install 的常见中文字体名。
    "html,body,body *{"
    "font-family:"
    "'Noto Sans CJK SC','Noto Sans CJK TC','Source Han Sans SC','Source Han Sans CN',"
    "'WenQuanYi Zen Hei','WenQuanYi Micro Hei',"
    "'PingFang SC','Hiragino Sans GB','Microsoft YaHei','Microsoft JhengHei',"
    "'SimHei','SimSun',sans-serif"
    "!important}"
    # 强制常见 dashboard 容器宽高 100% + 字体继承
    "#app,#root,.app,.container,.wrapper,.main,.content,.layout,.dashboard,.page,section,main,article{"
    "width:100%!important;height:100%!important;max-width:none!important;"
    "font-family:inherit!important;"
    "display:flex!important;flex-direction:column!important}"
    # 强制 SVG 文字 / canvas 自适应
    "svg,canvas{max-width:100%!important;height:auto!important}"
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
    "browser_window": "match_dashboard",  # v0.1.46 默认改为 match_dashboard（16:9 viewport，让 URL 页填满 fb0）
                                            # 可选："match_dashboard" / "match_fb_wide" / "match_fb" / [w, h]
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
        # v0.1.46: 一次性迁移 browser_window。
        # 旧 _sanitize 把"match_fb_wide" 字符串误判清洗成 [1920, 1080] 列表默认值，
        # 导致 Chromium viewport 变成 1920x1080，dashboard 16:9 设计在 fb 上只剩
        # 1024x576 + 下方 192px 黑边。检测到 list 值且为默认 [1920, 1080] 时迁移
        # 到 match_dashboard（16:9 viewport，无黑边填满 fb）。
        bw_marker = os.path.join(self.var_dir, ".migrated_to_match_dashboard")
        bw = data.get("browser_window")
        if not os.path.isfile(bw_marker):
            if isinstance(bw, list) and len(bw) == 2 and \
                    bw[0] == 1920 and bw[1] == 1080:
                data["browser_window"] = "match_dashboard"
                try:
                    with open(bw_marker, "w", encoding="utf-8") as f:
                        f.write("v0.1.46 migration: browser_window [1920,1080] -> match_dashboard\n")
                except OSError:
                    pass
                # 顺手落盘
                try:
                    tmp = self.path + ".tmp"
                    with open(tmp, "w", encoding="utf-8") as f:
                        json.dump(self._sanitize(data), f,
                                  ensure_ascii=False, indent=2)
                    os.replace(tmp, self.path)
                except OSError:
                    pass
                # 落 fb.log
                for _lp in ("fb.log",):
                    try:
                        import time as _t
                        with open(os.path.join(self.var_dir, _lp), "a",
                                  encoding="utf-8") as _f:
                            _f.write("[config %s] migration: browser_window [1920,1080] -> match_dashboard (URL 页面填满 fb0 无黑边)\n"
                                     % _t.strftime("%m-%d %H:%M:%S"))
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
        # v0.1.46: 接受 4 种预设 + [w, h] 列表：
        #   match_dashboard（v0.1.45+ 默认，dashboard 自然 16:9，填满 fb 无黑边）
        #   match_fb_wide（v0.1.42-44 默认，fb 长宽比 ×1.25，dashboard 设计成 100vh 时无黑边）
        #   match_fb（早期默认，fb 物理分辨率，截图即填满）
        #   16:9 / wide16（match_dashboard 别名）
        #   wide / 1.25x（match_fb_wide 别名）
        win = out.get("browser_window") or "match_dashboard"
        if isinstance(win, str):
            wl = win.lower()
            if wl in ("match_dashboard", "16:9", "wide16"):
                out["browser_window"] = "match_dashboard"
            elif wl in ("match_fb_wide", "wide", "1.25x"):
                out["browser_window"] = "match_fb_wide"
            elif wl in ("match_fb", "fb", "auto"):
                out["browser_window"] = "match_fb"
            else:
                # 未知字符串（很可能是 v0.1.42 之前的旧值，比如 "wide" 等） → 走默认
                out["browser_window"] = "match_dashboard"
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
            # v0.1.58: 之前 validator 只接受 "match_fb" 字面量 + [W, H] 数组，
            # 但 UI 上「16:9 viewport」「自适应显示器 ×1.25」按钮会写入
            # "match_dashboard" / "match_fb_wide"，还有 v0.1.57 新加的
            # "url_desktop"——这三种字面量全被一刀切当非法值拒掉。
            # 现在把所有合法 viewport 字符串都接受，并归一化到标准字面量。
            if isinstance(w, str):
                wl = w.lower()
                if wl in ("match_fb", "fb", "auto"):
                    clean["browser_window"] = "match_fb"
                elif wl in ("match_dashboard", "16:9", "wide16", "url_desktop"):
                    # 16:9 设计尺寸（1366×768 在 v0.1.56，1920×1080 在 v0.1.57
                    # 因为 URL 页面强制走 url_desktop；非 URL 用户配置仍是
                    # match_dashboard 由 fb_render 按 fb 推算 16:9）
                    clean["browser_window"] = "match_dashboard"
                elif wl in ("match_fb_wide", "wide", "1.25x"):
                    # fb 长宽比 ×1.25（dashboard 自适应）
                    clean["browser_window"] = "match_fb_wide"
                else:
                    return False, ("browser_window 取值非法：'%s'。"
                                   "允许 'match_fb' / 'match_dashboard' / "
                                   "'match_fb_wide' / [W, H] 数组") % w
            elif isinstance(w, list) and len(w) == 2:
                clean["browser_window"] = [_clip_int(w[0], 320, 7680, 1920),
                                           _clip_int(w[1], 240, 4320, 320)]
            else:
                return False, "browser_window 必须是字符串 ('match_fb' / 'match_dashboard' / 'match_fb_wide') 或 [W, H] 数组"
        if "url_viewport_size" in patch:
            # v0.1.59: URL 页面专属渲染基准尺寸（[W, H]）。让用户可以选 1280×720
            # （精确匹配桌面 reference）/ 1366×768 / 1440×900 / 1920×1080 / 自定义，
            # 解决不同 dashboard CSS 4 列断点不同的问题。
            u = patch["url_viewport_size"]
            if isinstance(u, list) and len(u) == 2:
                clean["url_viewport_size"] = [_clip_int(u[0], 320, 7680, 1280),
                                              _clip_int(u[1], 240, 4320, 720)]
            else:
                return False, "url_viewport_size 必须是 [W, H] 数组"
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