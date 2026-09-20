# fnOS 浏览器屏（fnos-kiosk）

把任意 **Web 页面**直接显示到 NAS 副屏（HDMI / VGA 直连的 `/dev/fb0`）。
基于 **headless Chromium + CDP**（纯 Python 标准库 WebSocket），沿用
[fnos-dashboard](https://github.com/neon9809/fnos-dashboard) 的 FPK 架构
（沙箱用户、udev 规则、仅本机管理面、CGI 反代、单进程 fb 渲染器）。

## ✦ 核心亮点

| 能力 | 说明 |
|---|---|
| **任意内容源** | 远程 URL / 本地 HTML / **本地图片（PNG/JPG/GIF/WebP/SVG/BMP/ICO）** / **本地视频（MP4/WebM/Ogg/Mov）** |
| **本地上传** | 直接从浏览器拖文件 → 上传 → 副屏显示，无需 SSH/手动复制 |
| **多页轮换** | URL 列表按时间自动翻页（与 fnos-dashboard 同套机制） |
| **显示方向** | 0°/90°/180°/270° 旋转、PPI 自适应缩放 |
| **CJK 中文** | PIL + 系统字体自动回退；缺失 PIL 时英文仍可用 |
| **管理面安全** | 设置页与全部管理接口仅限 127.0.0.1；URL 白名单防 SSRF |
| **fpk 沙箱** | `run-as=package` + `join-groups:["video"]`；udev 收紧 fb0 权限 |

## 📦 安装与使用

### 1. 准备 Chromium

```bash
sudo apt install -y chromium python3-pil
# 或
sudo apt install -y chromium-browser python3-pil
```

### 2. 安装 FPK

1. 把项目根目录打包为 `.fpk`（见下方「构建」章节）
2. 在 fnOS 应用中心 → 手动安装 → 选择 `.fpk`
3. 安装向导选择默认模式（URL 列表轮换 / 单 URL 全屏）、轮换时间、显示方向
4. 桌面会出现「浏览器屏」入口；点击进入设置页

### 3. 显示内容

**三种内容源、4 种使用方式：**

#### 方式 ①：远程 URL（网页）

设置页 → 「页面」→ `+ 新增页面` → 类型「远程 URL」→ 填 URL。
Chromium 完整渲染（JS / WebGL / 现代 CSS 全支持）。

#### 方式 ②：本地图片（从电脑拖上去）

设置页 → 「高级」→ 文件选择 → 选 PNG/JPG/GIF/WebP/SVG/BMP/ICO → ⬆ 上传。
上传后在「页面」→ `+ 新增页面` → 类型「媒体文件」→ 文件名下拉选刚上传的文件。
**Chromium 直接渲染图片 → fb0 输出到屏幕**。

#### 方式 ③：本地视频（MP4/WebM/Ogg/Mov）

同上，但视频文件。**Chromium 自动播放**（已加 `--autoplay-policy=no-user-gesture-required`）。
副屏会以截图频率（约 1 帧/秒）刷新——视频能播，但帧率受截图周期限制。
适合循环播放的短片、宣传片。

#### 方式 ④：本地 HTML（含交互、图表、时钟）

同上，类型「本地 HTML」→ 写 HTML 内容。

### 4. 模式选择

- **URL 列表轮换**：所有页面按时间自动翻页（默认 30 秒一页）
- **单 URL 全屏**：把某个页面设为 `mode=single`，它永远独占全屏，其他忽略（适合主看板）
- 同一份配置里可以混排：单 URL 页面独占 + 其他页面轮换

URL 默认禁止内网主机（防 SSRF），如需访问 192.168 等内网服务，
在「高级 → 允许内网主机」勾选。

### 5. 登录态持久化

默认情况下，Chromium 的 profile 存在 `var/chromium-profile/`。这意味着：

- ✅ **登录态自动持久化**——cookies / localStorage / 已存密码 / Service Worker 都在
- ✅ 重启 FPK / Chromium / NAS 后**自动恢复登录**，不需要每次输账号密码
- ✅ 适合「登录一次，长期展示」场景（HA、Grafana、自建面板等）

#### 首次登录（headless 不能直接交互）

设置页 → 「浏览器」→ 「📖 如何首次登录？」 里有详细三种方式。推荐 **方式 A**：

```bash
# 1. SSH 隧道把 NAS 的 CDP 端口转到你 PC
ssh -L 9223:127.0.0.1:9223 user@<NAS-IP>

# 2. PC 浏览器开 chrome://inspect/#devices
#    → Configure → 加 localhost:9223

# 3. 看到 kiosk 的 headless Chromium 后点「inspect」
#    → 打开 DevTools → Elements 面板里手动登录

# 4. 登录完关掉 DevTools 窗口 → kiosk 自动接管（用已保存的 cookies）
```

后续重启无需重登。

#### 重置登录态（账号换了 / 清缓存）

设置页 → 「浏览器」→ 「🗑 清空登录态」→ 确认。
渲染器自动重启 Chromium，下次导航会重新提示登录。

## 🛠️ 构建

```bash
# 生成图标 + 准备打包
./build.sh

# 直接跑本地预览（无需 fnOS）
python3 app/bin/dashboard.py --port 8200 --web app/web
# 浏览器打开 http://127.0.0.1:8200/
```

`build.sh` 默认会调用 `fnpack pack .` 生成 `.fpk`（需先安装 fnpack：
[developer.fnnas.com/docs/cli/fnpack](https://developer.fnnas.com/docs/cli/fnpack)）。

## 🌐 端口说明

应用启动后占用 **两个 127.0.0.1 绑定**端口：

| 端口 | 默认 | 作用 | 改法 |
|---|---|---|---|
| **HTTP API** | `8280` | 后端服务（前端面板 / 设置页 / CGI 反代目标） | 编辑 `manifest` 的 `service_port=`，重新 `fnpack build` 即可 |
| **CDP 远程调试** | `10303`（= HTTP 端口 + 1023） | Chromium DevTools Protocol；fb 渲染器通过它导航/截屏 | 设环境变量 `KIOSK_CDP_PORT=<其他端口>` 后重启 FPK；或在 `cmd/main` 启动前注入 |

### 不冲突的理由

- fnOS 系统核心口：80 / 443 / 5666 / 5667 / 22 / 8000（已弃用）/ 8001（已弃用）—— 都不在 8280
- fnos-dashboard：8199 —— 错开 +1
- 其他 FPK 应用各自声明 `service_port`，fnOS 安装时 `checkport=true` 实测空闲——撞车会拒绝安装
- HTTP API 与 CDP 都绑定 127.0.0.1（`--remote-debugging-address=127.0.0.1`），不对外暴露

### 想换 HTTP 端口？

```bash
# 编辑 manifest
sed -i 's/service_port=8280/service_port=9500/' manifest
# 重新打包
./build.sh && fnpack pack .
```

`fb_render.py` 默认通过 `TRIM_SERVICE_PORT` 环境变量读取 fnOS 注入的端口号，
运行时不再硬编码 8280。

### 想换 CDP 端口（罕见）？

在 `cmd/main` 里 `start_fb()` 之前一行加：

```bash
export KIOSK_CDP_PORT=10523  # 默认 = service_port + 1023
```

设置页「显示 → 显示器输出」下方会实时显示当前两个端口。

## 🔌 API

| 端点 | 方法 | 访问 | 说明 |
|---|---|---|---|
| `/` `/assets/*` | GET | 局域网 | 只读面板 |
| `/api/status` | GET | 局域网 | 配置 + 页面列表 |
| `/api/config` | GET | 局域网 | 读取配置 |
| `/api/pages` | GET | 局域网 | 本地 HTML 文件列表 |
| `/settings` | GET | **127.0.0.1** | 设置页 |
| `/api/settings` | POST | **127.0.0.1** | 保存配置（白名单 + 原子写盘 + 必要时重启渲染器） |
| `/api/pages/save` `/api/pages/delete` | POST | **127.0.0.1** | 本地 HTML 文件 CRUD |
| `/api/fb/info` | GET | **127.0.0.1** | fb0 状态 + 渲染进程 PID |
| `/api/fb/dump.png` | GET | **127.0.0.1** | 帧缓冲实时预览 PNG |

## 📐 架构（与 fnos-dashboard 同）

```
                 ┌─────────────┐
                 │  Chromium   │ ← CDP WebSocket（stdlib 手写）
                 │ headless=new│
                 └─────┬───────┘
                       │ Page.captureScreenshot
                       ▼
┌──────────────┐  ┌──────────────┐  HTTP  ┌──────────────┐
│  settings    │→ │ dashboard.py │←────── │ fb_render.py │ ─→ /dev/fb0
│ (127.0.0.1)  │  │ config/pages │       │ BrowserCanvas│
└──────────────┘  └──────────────┘        └──────────────┘
   浏览器              ▲                         ▲
                       │ /api/*                 │
                       └──── Chromium 子进程 ────┘
                            (start_new_session)
```

- **`dashboard.py`** —— HTTP 服务 + 配置/页面管理（接页面拉取、本地文件 CRUD）
- **`dash_browser.py`** —— Chromium 生命周期 + 纯 stdlib WebSocket + CDP 协议
- **`fb_render.py`** —— fb 渲染进程；`BrowserCanvas` 取截屏 → PIL 缩放 → 输出 BGRA → `FB.blit()`

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

## ⚠️ 已知边界

- Chromium 进程会持续占用约 200–400MB 内存（与目标页面复杂度相关），建议 NAS 内存 ≥ 2GB
- WebGL、视频硬解等高负载页面在 headless 下可能掉帧
- 单 Chromium 实例：所有页面共享同一标签页，刷新模式等于 Page.reload
- fb 渲染器轮询截图 → blit 间隔默认 1s（可在 fb_render.py 调整 nav_interval）

## 🧱 目录结构

```
fnos-kiosk/
├── app/
│   ├── bin/
│   │   ├── dashboard.py       # HTTP 后端入口
│   │   ├── dash_config.py     # 配置 + 白名单
│   │   ├── dash_pages.py      # 页面源（URL / 本地 HTML）
│   │   ├── dash_browser.py    # Chromium + stdlib WebSocket + CDP
│   │   ├── dash_http.py       # HTTP 路由
│   │   ├── fb_render.py       # 显示器渲染器 + BrowserCanvas
│   │   └── neon_crypto.py     # 扩展点（.neon-dash 模组系统的占位）
│   ├── web/
│   │   ├── index.html         # 只读面板
│   │   ├── settings.html      # 设置页（左配置右预览）
│   │   └── assets/            # style.css / settings.css / app.js / settings.js
│   ├── ui/
│   │   ├── index.cgi          # fnOS CGI 反代
│   │   ├── config             # 桌面图标声明
│   │   └── images/            # 64×64 / 256×256 图标
├── cmd/
│   ├── main                   # 启停（start/stop/status）
│   ├── install_callback       # 安装钩子：写配置 + udev 规则
│   ├── uninstall_callback     # 卸载钩子：清 udev 规则
│   ├── upgrade_callback       # 升级钩子
│   ├── config_callback        # 配置向导回调
│   └── ..._init               # 向导入口占位
├── config/
│   ├── privilege              # run-as=package + join-groups:["video"]
│   └── resource               # apt 依赖声明
├── wizard/
│   ├── install                # 安装向导表单
│   └── config                 # 配置向导表单
├── tools/make_icons.py        # 图标生成器
├── manifest                   # FPK 元数据
└── build.sh                   # 构建脚本
```

## 🤝 参与开发

欢迎 PR。最有价值的几个方向：
- 新的「本地 HTML 模板」（日历 / 看板 / 大字时钟）
- 多 Chromium 实例支持（不同 URL 不同隔离进程）
- 触控事件转发（fb0 触屏 → 浏览器点击）
- 中文化主题（除现有 6 套外）

## 📜 许可证

MIT