# fnos-kiosk · 浏览器屏

把任意 **Web 页面**直接显示到 fnOS NAS 副屏（HDMI / VGA 直连的 `/dev/fb0`）。
基于 **headless Chromium + CDP**（纯 Python 标准库 WebSocket，零第三方依赖），
沿用 [fnos-dashboard](https://github.com/neon9809/fnos-dashboard) 的 FPK 沙箱架构
（沙箱用户、udev 收紧 fb0、仅本机管理面、CGI 反代、单进程 fb 渲染器）。

> 📦 最新发布：[github.com/kou147258/fnos-kiosk/releases](https://github.com/kou147258/fnos-kiosk/releases)

---

## ✨ 核心能力

| 能力 | 说明 |
|---|---|
| **任意内容** | 远程 URL / 本地 HTML / 本地图片（PNG/JPG/GIF/WebP/SVG/BMP/ICO） / 本地视频（MP4/WebM/Ogg/Mov） |
| **本地上传** | 浏览器拖文件 → 上传 → 副屏显示，无需 SSH / 手动复制 |
| **多页轮换** | URL 列表按时间自动翻页（同 fnos-dashboard 机制） |
| **显示方向** | 0° / 90° / 180° / 270° 旋转，PPI 自适应缩放 |
| **登录态持久化** | Chromium profile 保留 cookies / localStorage，重启免登录 |
| **管理面安全** | 设置页与全部管理接口仅限 127.0.0.1；URL 白名单防 SSRF |
| **FPK 沙箱** | `run-as=package` + `join-groups:["video"]`；udev 收紧 fb0 权限 |
| **CJK 中文** | PIL + 系统字体自动回退；缺 PIL 时英文仍可用 |

---

## 📦 安装与使用

### 1. 安装前的依赖（NAS 上执行一次）

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
4. 桌面会出现「**浏览器屏**」入口；点击进入设置页

### 3. 显示内容 — 三种内容源

#### 方式 ① 远程 URL

设置页 → 「页面」→ `+ 新增页面` → 类型「远程 URL」→ 填 URL。
Chromium 完整渲染（JS / WebGL / 现代 CSS 全支持）。

#### 方式 ② 本地图片 / 视频

设置页 → 「高级」→ 文件选择 → 选 PNG / JPG / GIF / WebP / SVG / BMP / ICO / MP4 / WebM / Ogg / Mov → 上传。
「页面」→ `+ 新增页面` → 类型「媒体文件」→ 文件名下拉选刚上传的文件。
Chromium 直接渲染图片 / 自动播放视频 → fb0 输出到屏幕。

> 视频以截图频率（约 1 秒）刷新——能播，但帧率受截图周期限制，
> 适合循环播放的短片、宣传片。

#### 方式 ③ 本地 HTML（含交互、图表、时钟）

设置页 → 「高级」→ 文件选择 → 选 `.html` 文件 → 上传。
「页面」→ `+ 新增页面` → 类型「本地 HTML」→ 选择文件。

### 4. 模式选择

- **URL 列表轮换**：所有 `mode=cycle` 的页面按 `rotate_seconds` 自动翻页（默认 30 秒 / 页）
- **单 URL 全屏**：把某个页面设为 `mode=single`，它永远独占全屏，其他忽略（适合主看板）
- 同一份配置里可以混排：单 URL 页面独占 + 其他页面轮换

URL 默认禁止内网主机（防 SSRF）。如需访问 192.168 等内网服务，
在「高级」→ 勾选「允许内网主机」。

### 4.5 拖拽上传（即时显示）

把任意 **图片 / 视频 / HTML 文件**直接拖到设置页任意位置 → 自动上传到 NAS + 注册为单 URL 全屏页面 → 立即显示到副屏。

> 多文件一起拖：按文件名排序，最后一个为 `mode=single` 独占全屏，其余为 `mode=cycle` 加入轮换。

支持的扩展名：PNG / JPG / GIF / WebP / SVG / BMP / ICO / MP4 / WebM / Ogg / Mov / HTML。单文件 ≤ 16 MB。

### 5. 登录态持久化

默认情况下，Chromium 的 profile 存在 `var/chromium-profile/`。这意味着：

- **登录态自动持久化** —— cookies / localStorage / 已存密码 / Service Worker 都在
- 重启 FPK / Chromium / NAS **自动恢复登录**，不需要每次输账号密码
- 适合「登录一次，长期展示」场景（HA、Grafana、自建面板等）

#### 首次登录（headless 不能直接交互）

设置页 → 「浏览器」→ 「如何首次登录？」里有详细三种方式。推荐 **方式 A**：

```bash
# 1. SSH 隧道：把 NAS 的 CDP 端口转到 PC
ssh -L 9223:127.0.0.1:9223 user@<NAS-IP>

# 2. PC 浏览器打开 chrome://inspect/#devices
#    → Configure → 添加 localhost:9223

# 3. 看到 kiosk 的 headless Chromium 后点「inspect」
#    → 打开 DevTools → 在 Elements 面板里手动登录

# 4. 登录完关 DevTools 窗口 → kiosk 自动接管（用已保存的 cookies）
```

后续重启无需重登录。

#### 重置登录态（账号换了 / 清缓存）

设置页 → 「浏览器」→ 「清空登录态」→ 确认。
渲染器自动重启 Chromium，下次导航会重新提示登录。

> 重置会删除 auth cookies / IndexedDB / Service Worker / 缓存等，但**保留**浏览器偏好
>（`Preferences` / `Bookmarks` / `Secure Preferences` / `Local State`），
> 避免每次重置都把深色模式 / 字体设置一并丢掉。

---

## 🔌 默认端口

应用启动后占用 **两个 127.0.0.1 绑定** 端口：

| 端口 | 默认 | 作用 | 改法 |
|---|---|---|---|
| **HTTP API** | `8280` | 后端服务（前端面板 / 设置页 / CGI 反代目标） | 编辑 `manifest` 的 `service_port=`，重打包 |
| **CDP 远程调试** | `10303`（HTTP 端口 + 1023） | Chromium DevTools Protocol；fb 渲染器通过它导截屏 | 环境变量 `KIOSK_CDP_PORT=<其他端口>` 后重启 FPK |

### 为什么是 8280？

- fnOS 系统核心口：80 / 443 / 5666 / 5667 / 22 —— **不撞 8280**
- fnos-dashboard 默认 8199 —— 错开 +1
- 部分 NAS 自带 MiniDLNA 占用 8200 —— **0.1.1 起避开**
- 其他 FPK 应用各自声明 `service_port`，fnOS 安装时 `checkport=true` 实测空闲，撞车会拒绝安装
- HTTP API 与 CDP 都绑 127.0.0.1（`--remote-debugging-address=127.0.0.1`），不对外暴露

> **📜 历史 fix（端口坑）**
>
> | 版本 | 改动 |
> |---|---|
> | v0.1.0 | 默认 8200，与部分 NAS 的 MiniDLNA 撞车 —— 用户点桌面图标跳到 MiniDLNA 状态页 |
> | v0.1.1 | manifest 默认端口 8200 → 8280 |
> | v0.1.2 | 修复 CGI 反代（`index.cgi`）仍硬编码 8200 —— 改为读 `TRIM_SERVICE_PORT` → 回落 8280 |
> | v0.1.3 | 把 argparse 默认值、文档示例、CLI 帮助文本里所有 8200 全部统一到 8280（彻底无残留） |

### 想换 HTTP 端口

```bash
# 编辑 manifest
sed -i 's/service_port=8280/service_port=9500/' manifest
# 重新打包
./build.sh
```

`fb_render.py` 默认通过 `TRIM_SERVICE_PORT` 环境变量读取 fnOS 注入的端口号，运行时不再硬编码。

### 想换 CDP 端口（罕见）

在 `cmd/main` 的 `start_fb()` 之前一行加：

```bash
export KIOSK_CDP_PORT=10523  # 默认 = service_port + 1023
```

设置页「显示器输出」下方会实时显示当前两个端口。

---

### 🛡 渲染进程自愈（v0.1.5 起）

**问题**：早期版本里如果 Chromium 启动失败（比如刚启动时 profile 还没就绪、
`chromium` 还没装、CDP 端口被占），`fb_render.py` 会直接 `return` 退出，显示器就一直黑屏。

**现在的行为**：

| 失败场景 | 旧版 | v0.1.5+ |
|---|---|---|
| Chromium 启动失败 | 进程退出 → 黑屏 | `fb_render` 内部指数退避重试（5s → 10s → 20s → 30s），不死循环 |
| `fb_render.py` 崩溃 | 不重启 | `cmd/main` 部署的 watchdog 进程每 5s 检测一次，死了自动拉起 |
| `/dev/fb0` 暂时不可读 | 进程退出 | `fb_render` 内部重试，fb0 出现后立即接管 |
| 任何进程死亡 | fnOS 不知道 | watchdog 把日志写到 `var/wd.log`，设置页可查看 |

排障入口（设置页 → 显示 tab）：

- **🔄 手动重启渲染进程** —— 一键 `POST /api/fb/restart`
- **📋 查看 fb.log** —— 末尾 100 行，排障 Chromium 启动错误

---

## 📐 架构

```
                   ┌────────────────┐
                   │   Chromium     │  ←── CDP WebSocket (stdlib) ──┐
                   │  headless=new  │                               │
                   └────────────────┘                               │
                                                                   ▼
  ┌──────────────┐         ┌────────────────┐         ┌──────────────────┐
  │  浏览器面板   │ ──HTTP─▶│  dashboard.py  │  cfg/   │    fb_render     │───→ /dev/fb0
  │  (只读)      │         │   (127.0.0.1)  │────────▶│  BrowserCanvas   │     (NAS 副屏)
  └──────────────┘         └───────┬────────┘         │  PIL 缩放 + blit │
                                   │                  └──────────────────┘
                                   ▼
                          ┌────────────────┐
                          │  设置页 (CGI)  │  ←── 仅 127.0.0.1
                          │  reverse proxy │
                          └────────────────┘
```

模块说明：

- **`dashboard.py`** — HTTP 服务 + 配置 / 页面管理（接页面拉取、本地文件 CRUD、SSRF 校验）
- **`dash_browser.py`** — Chromium 生命周期 + stdlib WebSocket + CDP 协议
- **`dash_pages.py`** — 三类内容源统一抽象（`resolve_url`）
- **`fb_render.py`** — fb 渲染进程；`BrowserCanvas` 取截图 → PIL 缩放 → 输出 BGRA → `FB.blit()`
- **`index.cgi`** — fnOS 桌面入口反代（→ HTTP API）

---

## 📡 API

| 端点 | 方法 | 访问 | 说明 |
|---|---|---|---|
| `/` `/assets/*` | GET | 局域网 | 只读面板 |
| `/api/status` | GET | 局域网 | 配置 + 页面列表 |
| `/api/config` | GET | 局域网 | 读取配置 |
| `/api/pages` | GET | 局域网 | 本地 HTML / 媒体文件列表 |
| `/api/upload` | POST | 局域网 | 上传媒体 / HTML（白名单后缀） |
| `/api/pages/file` | GET | 局域网 | 读取本地文件（按 MIME） |
| `/settings` | GET | **127.0.0.1** | 设置页 |
| `/api/settings` | POST | **127.0.0.1** | 保存配置（白名单 + 原子写盘 + 必要时重启渲染器） |
| `/api/pages/save` `/api/pages/delete` | POST | **127.0.0.1** | 本地文件 CRUD |
| `/api/auth/reset` | POST | **127.0.0.1** | 清登录态（保留 Preferences） |
| `/api/fb/info` | GET | **127.0.0.1** | fb0 状态 + 渲染进程 PID |
| `/api/fb/dump.png` | GET | **127.0.0.1** | 帧缓冲实时预览 PNG |
| `/api/fb/restart` | POST | **127.0.0.1** | 手动重建 fb_render（v0.1.5+） |
| `/api/fb/log` | GET | **127.0.0.1** | fb.log 末尾 100 行（v0.1.5+） |

---

## 🛠 构建

### 本地预览（不需要 fnOS / Chromium）

```bash
# 直接跑 dashboard.py（绕过 FPK），PC 浏览器开 http://127.0.0.1:8280/
python3 app/bin/dashboard.py --port 8280 --web app/web
```

> 本地预览时没有 `/dev/fb0`（也没有 Chromium），渲染器会进 fallback 模式，
> 但完整 HTTP API 与设置页都可用 —— 适合开发与功能调试。

### 打包 FPK

```bash
./build.sh
```

`build.sh` 默认调用 `fnpack build`（无参数；fnpack 以当前目录为 FPK 根），
需先安装 [fnpack](https://developer.fnnas.com/docs/cli/fnpack)。

无 fnpack 环境可用手写打包兜底：

```bash
python3 tools/pack_fpk.py
```

> 手写打包器参考 fnOS 官方 [fnpack-1.2.1](https://static2.fnnas.com/fnpack/fnpack-1.2.1-windows-amd64)
> 输出的 gzip 头部（`1F 8B 08 00`）格式。Windows 自带 ZIP 输出的 `50 4B 03 04` 头不被 fnOS 接受。

---

## ⚙️ 配置示例

`etc/config.json`：

```json
{
  "theme": "midnight",
  "accent": "#3b82f6",
  "default_mode": "cycle",
  "rotate_seconds": 30,
  "fb_enabled": true,
  "fb_rotate": 0,
  "screen_inches": 0,
  "browser_path": "",
  "browser_window": [1920, 1080],
  "browser_scale": 1.0,
  "browser_timeout": 30,
  "hide_cursor": true,
  "allow_private_hosts": false,
  "pages": [
    {
      "id": "ha",
      "name": "Home Assistant",
      "type": "url",
      "url": "http://192.168.9.10:8123/lovelace/main",
      "mode": "single",
      "refresh_seconds": 300,
      "zoom": 1.0,
      "enabled": true
    },
    {
      "id": "weather",
      "name": "本地天气",
      "type": "url",
      "url": "https://www.qweather.com/",
      "mode": "cycle",
      "refresh_seconds": 600,
      "zoom": 0.85,
      "enabled": true
    },
    {
      "id": "clock",
      "name": "本地时钟",
      "type": "html_file",
      "path": "clock.html",
      "mode": "cycle",
      "refresh_seconds": 0,
      "zoom": 1.0,
      "enabled": false
    }
  ]
}
```

---

## 📜 版本与变更

| 版本 | 重点 |
|---|---|
| **v0.1.5** | 渲染进程自愈（watchdog + 内部重试）；拖拽上传即时显示；`/api/fb/restart` & `/api/fb/log` 诊断接口；修复 cmd/main 端口兜底 8200 → 8280；修复所有 shell 脚本 CRLF 换行 |
| v0.1.4 | 清理 manifest / README 的 GBK 编码乱码；changelog 补全历史 |
| v0.1.3 | 全部 8200 残留清理（argparse 默认 / 文档示例 / CLI 帮助文本） |
| v0.1.2 | CGI 反代端口解析修复（`index.cgi` 不再硬编码 8200） |
| v0.1.1 | 默认 HTTP 端口 8200 → 8280（避开部分 NAS 自带 MiniDLNA 占用） |
| v0.1.0 | 初版：headless Chromium + CDP，三类内容源，沿用 fnos-dashboard FPK 沙箱架构 |

详细 changelog 见 [GitHub Releases](https://github.com/kou147258/fnos-kiosk/releases)。

---

## ⚠️ 已知边界

- Chromium 进程会持续占用约 200 ~ 400 MB 内存（与目标页面复杂度相关），建议 NAS 内存 ≥ 2 GB
- WebGL、视频硬解等高负载页面在 headless 下可能掉帧
- 单 Chromium 实例：所有页面共享同一标签页，刷新模式等于 `Page.reload`
- fb 渲染器轮询截图 / blit 间隔默认 1 s（可在 `fb_render.py` 调整 `nav_interval`）
- headless Chromium 不支持触屏事件；fb0 触屏点击不会被转发到浏览器（已知 TODO）

---

## 🧱 目录结构

```
fnos-kiosk/
├── app/
│   ├── bin/                  # Python 后端（zero deps）
│   │   ├── dashboard.py      # HTTP 服务入口
│   │   ├── dash_config.py    # 配置 + 白名单
│   │   ├── dash_pages.py     # 页面源（URL / 本地 HTML / 媒体文件）
│   │   ├── dash_browser.py   # Chromium + stdlib WebSocket + CDP
│   │   ├── dash_http.py      # HTTP 路由
│   │   ├── fb_render.py      # 显示器渲染器 + BrowserCanvas
│   │   └── neon_crypto.py    # 扩展点（占位）
│   ├── web/                  # 前端面板与设置页
│   │   ├── index.html
│   │   ├── settings.html
│   │   └── assets/           # style.css / settings.css / app.js / settings.js
│   ├── ui/                   # fnOS 桌面入口
│   │   ├── index.cgi         # fnOS CGI 反代（读 var/port.txt → 8280）
│   │   ├── config            # 桌面图标声明
│   │   └── images/           # 64×64 / 256×256 图标
├── cmd/                      # FPK 生命周期脚本（main / install_callback / ...）
├── config/                   # privilege + resource
├── wizard/                   # install + config 向导表单
├── tools/
│   ├── make_icons.py         # 图标生成
│   └── pack_fpk.py           # 手写 FPK 打包（gzip 头合规）
├── manifest                  # FPK 元数据
└── build.sh                  # 构建脚本
```

---

## 🤝 参与开发

欢迎 PR。最有价值的几个方向：

- 新的「本地 HTML 模板」（日历 / 看板 / 大字时钟）
- 多 Chromium 实例支持（不同 URL 隔离进程）
- 触控事件转发（fb0 触屏 → 浏览器点击）
- 中文化主题（除现有 6 套外）

---

## 📜 许可证

MIT —— 详见 [LICENSE](LICENSE)。

---

## 🔗 链接

- 项目主页：<https://github.com/kou147258/fnos-kiosk>
- 架构参考：[fnos-dashboard](https://github.com/neon9809/fnos-dashboard)
- fnOS 应用开发文档：<https://developer.fnnas.com/>
- fnpack 工具：<https://developer.fnnas.com/docs/cli/fnpack>