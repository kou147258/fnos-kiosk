# fnos-kiosk · 浏览器屏

把任意 **Web 页面**直接显示到 fnOS NAS 副屏（HDMI / VGA 直连的 `/dev/fb0`）。
基于 **headless Chromium + CDP**（纯 Python 标准库 WebSocket，**零第三方依赖**），
沿用 [fnos-dashboard](https://github.com/kou147258/fnos-dashboard) 的 FPK 沙箱架构
（沙箱用户、udev 收紧 fb0、仅本机管理面、CGI 反代、单进程 fb 渲染器）。

> 📦 **当前版本：[v0.1.61](https://github.com/kou147258/fnos-kiosk/releases/tag/v0.1.61)** · 单一 release、单一版本号

---

## ✨ fnos-kiosk 做什么

**核心问题**：你 NAS 上挂了副屏（HDMI 接的小显示器 / VGA 老的触摸屏），
你想让这块屏永远显示某个 web 页面（HA 看板、Grafana、自建面板、公司内网监控页）。
系统浏览器打开后会被其他窗口盖掉、Chromium 全屏启动会占资源、桌面环境会闪屏。

**fnos-kiosk 解法**：把任意 URL 当成「静态画面」通过 headless Chromium 渲染 + CDP 截图 + PIL 绘制到 `/dev/fb0`。后台静默、不抢桌面、登录态持久化、远程 web 设置、自动恢复崩溃。

---

## ✅ 已实现功能（v0.1.61）

| | |
|---|---|
| **三类内容源** | 远程 URL · 本地 HTML · 本地图片（PNG/JPG/GIF/WebP/SVG/BMP/ICO）· 本地视频（MP4/WebM/Ogg/Mov） |
| **页面缩放** | URL 内容 `transform: scale`（slider 50%~300%）—— 只缩内容，URL viewport 自身永不变 |
| **URL viewport 钳制** | 默认 1280×720（dashboard 设计尺寸），CDP `Emulation.setDeviceMetricsOverride` 强制 inner viewport，不被 headless auto-detect 偷走 |
| **DPR 钳制** | chromium `--force-device-scale-factor=1.0`（避免某些 headless 把 1280 auto-detect 成 1024） |
| **display_fit 模式** | URL 强制 stretch 填满 fb 4:3；媒体 / 本地 HTML 由用户配置决定 |
| **多页轮换** | URL 列表按时间自动翻页（同 fnos-dashboard 机制） |
| **显示方向** | 0° / 90° / 180° / 270° 旋转，PPI 自适应缩放 |
| **拖拽上传** | 把图片/视频/HTML 拖到设置页 → 上传到 NAS + 立即显示到副屏 |
| **登录态持久化** | Chromium profile 保留 cookies / localStorage，重启免登录 |
| **管理面安全** | 设置页与全部管理接口仅限 127.0.0.1；URL 白名单防 SSRF |
| **FPK 沙箱** | `run-as=package` + `join-groups:["video"]`；udev 收紧 fb0 权限 |
| **CJK 中文** | PIL + 系统字体自动回退；缺 PIL 时英文仍可用 |
| **自愈 watchdog** | 渲染进程崩溃 / Chromium 启动失败自动重试；fb0 不可读也持续重试 |
| **诊断 API** | `/api/fb/diag` 一键诊断 fb0 权限 / 进程 / Chromium / PIL / profile |

---

## 📦 安装

### 1. NAS 上装 Chromium（一次性）

```bash
sudo apt install -y chromium python3-pil
# 部分发行版包名是 chromium-browser
# sudo apt install -y chromium-browser python3-pil
```

Chromium 是唯一的外部重量级依赖；**Python 代码零第三方包**，stdlib 即可。

### 2. 安装 FPK

1. 从 [Releases](https://github.com/kou147258/fnos-kiosk/releases) 下载最新 `com.fnos.kiosk.fpk`
2. fnOS 桌面 → **应用中心** → **手动安装** → 选择 `.fpk`
3. 安装向导选择默认模式（URL 列表轮换 / 单 URL 全屏）、轮换时间、显示方向
4. 桌面出现「**浏览器屏**」入口；点击进入设置页

### 3. 配置 URL + 重启渲染进程

设置页 → 「页面」→ `+ 新增页面` → 类型「远程 URL」→ 填 URL → 保存。
设置页保存后 fb_render 会自动检测配置变化并在 2-3 秒内重启 Chromium 让新配置生效。

---

## 🎯 推荐用法（v0.1.61 默认配置的最佳场景）

**场景：NAS 副屏显示某个 dashboard（HA / Grafana / 自建监控页）**

| 设置项 | 推荐值 | 说明 |
|---|---|---|
| 类型 | 远程 URL | 填 dashboard 完整 URL |
| 模式 | `single` | 这个页面永远独占全屏 |
| 缩放 | **100%（1.0）** | 不要调比例，让 dashboard 自然大小 |
| 适配 | 任意 | v0.1.61 已强制 URL 页面用 stretch 填满 fb，配置不影响 |
| 高级 → url_viewport_size | 默认 `[1280, 720]` | dashboard 设计尺寸，CDP 强制生效 |
| 高级 → url_kiosk_css | 默认空 | dashboard 自己排版（除非想强制拉伸/全屏） |

如果 dashboard 在副屏上**只看到 4 张卡**（2×2 而不是 6 卡），最常见原因就是 **chromium auto-detect 把它当 1.25× DPR 缩成 1024 宽**。v0.1.61 已加 `Emulation.setDeviceMetricsOverride 1280x720 dpr=1.0` 把这条链路钉死，fb.log 里能看到这一行 banner：

```
[fb] v0.1.61 fb_render starting
[fb] 1024x768 stride=4096
[fb] 字体: latin=... cjk=/usr/share/fonts/truetype/droid/DroidSansFallbackFull.ttf
[fb] 启动中屏已写入 fb0（Chromium 还没起来，正在初始化）
[fb] 视口决策: has_url=True bw=match_dashboard
[fb] Emulation.setDeviceMetricsOverride 1280x720 dpr=1.0
[fb] Chromium ready (window=1280x720)
```

如果你看到 `Chromium ready (window=1280x720)` + `Emulation.setDeviceMetricsOverride 1280x720 dpr=1.0`，inner viewport 就是 1280 物理像素、1.0 DPR，dashboard 进 3 列布局时 6 张卡完整。

---

## 📐 架构

```
                   ┌────────────────┐
                   │   Chromium     │  ←── CDP WebSocket (stdlib) ──┐
                   │  headless=new  │                               │
                   │  --force-      │                               │
                   │  device-scale- │                               │
                   │  factor=1.0    │                               │
                   │  +Emulation    │                               │
                   │  setDevice     │                               │
                   │  MetricsOverri │                               │
                   └────────────────┘                               │
                                                                   ▼
  ┌──────────────┐         ┌────────────────┐         ┌──────────────────┐
  │  浏览器面板   │ ──HTTP─▶│  dash_http.py  │  cfg/   │    fb_render     │───→ /dev/fb0
  │  (只读)      │         │   (127.0.0.1)  │────────▶│  BrowserCanvas   │     (NAS 副屏)
  └──────────────┘         └───────┬────────┘         │  PIL stretch +   │
                                   │                  │  blit            │
                                   ▼                  └──────────────────┘
                          ┌────────────────┐
                          │  设置页 (CGI)  │  ←── 仅 127.0.0.1
                          │  reverse proxy │
                          └────────────────┘
```

模块说明：

- **`dash_http.py`** — HTTP 服务（设置页 + 配置 / 页面管理 + 诊断）
- **`dash_browser.py`** — Chromium 生命周期 + stdlib WebSocket + CDP 协议；`Browser.set_viewport(w, h, dpr=1.0)` 通过 `Emulation.setDeviceMetricsOverride` 强制 inner viewport
- **`dash_pages.py`** — 三类内容源统一抽象（`resolve_url`）
- **`fb_render.py`** — fb 渲染进程；URL 页 `display_fit` 强制 stretch；`BrowserCanvas` 取截图 → PIL stretch 拉伸 → 输出 RGBA → `FB.blit()`
- **`dash_config.py`** — 配置白名单（`_sanitize`），所有外部输入过这里；URL 页配置 `_sanitize` 接受 `match_dashboard` / `match_fb` / `match_fb_wide` / `url_desktop` 字符串 + `[W, H]` 数组 + `url_viewport_size` 列表
- **`index.cgi`** — fnOS 桌面入口反代（→ HTTP API）

---

## 🔌 默认端口

应用启动后占用 **两个 127.0.0.1 绑定** 端口：

| 端口 | 默认 | 作用 |
|---|---|---|
| **HTTP API** | `8280` | 后端服务（前端面板 / 设置页 / CGI 反代目标） |
| **CDP 远程调试** | `9303`（HTTP 端口 + 1023） | Chromium DevTools Protocol；fb 渲染器通过它导截屏 |

都绑 127.0.0.1，不对外暴露。fnOS 安装时 `checkport=true` 实测空闲，撞车会拒绝安装。

---

## 📡 API（仅节选）

| 端点 | 方法 | 访问 | 说明 |
|---|---|---|---|
| `/api/status` | GET | 局域网 | 配置 + 页面列表 |
| `/api/config` | GET / POST | POST 仅 127.0.0.1 | 读取 / 保存配置（白名单 + 原子写盘） |
| `/api/pages` | GET / POST / DELETE | POST/DELETE 仅 127.0.0.1 | 本地 HTML / 媒体文件列表 CRUD |
| `/api/upload` | POST | 局域网 | 上传媒体 / HTML（白名单后缀） |
| `/api/auth/reset` | POST | 127.0.0.1 | 清登录态（保留 Preferences） |
| `/api/fb/info` | GET | 127.0.0.1 | fb0 状态 + 渲染进程 PID |
| `/api/fb/dump.png` | GET | 127.0.0.1 | 帧缓冲实时预览 PNG |
| `/api/fb/diag` | GET | 127.0.0.1 | 一键诊断（fb0 权限 / 进程 / Chromium / PIL / profile）|
| `/api/fb/restart` | POST | 127.0.0.1 | 手动重建 fb_render 进程 |
| `/api/fb/log` | GET | 127.0.0.1 | fb.log 末尾 100 行 |

---

## 🛠 开发

### 本地预览（不需要 fnOS / Chromium）

```bash
git clone https://github.com/kou147258/fnos-kiosk.git
cd fnos-kiosk
python3 app/bin/dash_http.py --port 8280 --web app/web
# 浏览器打开
open http://127.0.0.1:8280/
```

> 本地预览时没有 `/dev/fb0` 也没有 Chromium，fb_render 不启动；HTTP API 和设置页全可用。

### 打包 FPK

```bash
K:\ESP\fnpack.exe build .   # 需要 [fnpack](https://developer.fnnas.com/docs/cli/fnpack)
```

无 fnpack 环境可用手写打包兜底：
```bash
python3 tools/pack_fpk.py
```

---

## ⚙️ 高级配置

`etc/config.json` 关键字段：

```json
{
  "theme": "midnight",
  "default_mode": "single",
  "rotate_seconds": 30,
  "fb_enabled": true,
  "fb_rotate": 0,
  "browser_window": "match_dashboard",
  "browser_scale": 1.0,
  "url_viewport_size": [1280, 720],
  "url_kiosk_css": "",
  "pages": [
    {
      "id": "main",
      "name": "Home Assistant",
      "type": "url",
      "url": "http://192.168.9.10:8123/lovelace/main",
      "mode": "single",
      "refresh_seconds": 300,
      "zoom": 1.0,
      "enabled": true
    }
  ]
}
```

URL 页面 `display_fit` 写死为 `stretch`（覆盖用户配置）—— fb4:3 + URL 16:9 永远拉满，没有黑条也没有横压。
非 URL 页面（媒体 / 本地 HTML）走用户的 `display_fit`（默认 stretch）。

---

## ⚠️ 已知边界

- Chromium 进程会持续占用约 200 ~ 400 MB 内存（与目标页面复杂度相关），建议 NAS 内存 ≥ 2 GB
- WebGL、视频硬解等高负载页面在 headless 下可能掉帧
- 单 Chromium 实例：所有页面共享同一标签页
- fb 渲染器轮询截图 / blit 间隔默认 1 s（可在 `fb_render.py` 调整 `nav_interval`）
- headless Chromium 不支持触屏事件；fb0 触屏点击不会被转发到浏览器（已知 TODO）

---

## 🧱 目录结构

```
fnos-kiosk/
├── app/
│   ├── bin/                  # Python 后端（zero deps）
│   │   ├── dash_http.py
│   │   ├── dash_config.py
│   │   ├── dash_pages.py
│   │   ├── dash_browser.py
│   │   ├── fb_render.py
│   └── web/                  # 前端面板与设置页
│       ├── index.html
│       ├── settings.html
│       └── assets/
├── cmd/                      # FPK 生命周期脚本
├── config/                   # privilege + resource
├── wizard/                   # install + config 向导
├── tools/
│   ├── make_icons.py
│   └── pack_fpk.py
├── manifest                  # 当前版本 v0.1.61
├── CONTRIBUTING.md
└── README.md
```

---

## 📜 版本

**当前唯一发布版本：v0.1.61**（2026-09-21）。

v0.1.61 主要修改：
1. **强制 chromium `--force-device-scale-factor=1.0`** —— 不再被 headless auto-detect 偷走 inner viewport
2. **新增 `Browser.set_viewport(w, h, dpr=1.0)`** —— 通过 CDP `Emulation.setDeviceMetricsOverride` 显式钳制 inner viewport，作为 CLI flag 的双保险
3. **URL 页面 `display_fit` 从 `cover` 改 `stretch`** —— fb 4:3 永远填满，dashboard 卡片视觉比例 80:107 ≈ 0.75，跟桌面 reference 比例最接近
4. **`_sanitize` 接受 `match_dashboard` / `match_fb_wide` 字面量 + `url_viewport_size` 列表** —— 用户在设置页点「16:9 viewport」「自适应显示器」按钮能正常保存
5. **`__kioskApplyZoom` 删 CSS `zoom` 属性** —— `transform: scale` 是唯一缩放源，避免 layout reflow 把 dashboard 从 3 列回流到 2 列

历史 release notes 已清除——本仓库从 v0.1.61 起只维护一个版本，所有用户全部从 v0.1.61 起开始用。

---

## 🤝 参与开发

见 [CONTRIBUTING.md](CONTRIBUTING.md)。

---

## 📜 许可证

MIT —— 详见 [LICENSE](LICENSE)。

---

## 🔗 链接

- 项目主页：<https://github.com/kou147258/fnos-kiosk>
- 架构参考：[fnos-dashboard](https://github.com/kou147258/fnos-dashboard)
- fnOS 应用开发文档：<https://developer.fnnas.com/>
- fnpack 工具：<https://developer.fnnas.com/docs/cli/fnpack>
