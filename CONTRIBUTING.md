# 参与开发

欢迎加入 fnos-kiosk 开发！本项目沿袭 fnos-dashboard 的「**零第三方 Python 依赖 + 纯原生 Web 前端**」哲学，
但因 headless Chromium 是渲染引擎，apt 依赖是不可避免的（不算第三方 Python 包）。

---

## ⚙️ 开发环境

```bash
git clone https://github.com/kou147258/fnos-kiosk.git
cd fnos-kiosk

# 安装 Chromium（任何发行版的 headless Chromium 即可）
sudo apt install -y chromium python3-pil
# 不需要 fnOS 也能跑（fb_render 没 /dev/fb0 会自动 fallback）
python3 app/bin/dash_http.py --port 8280 --web app/web
# 浏览器打开
open http://127.0.0.1:8280/
```

---

## 🧱 模块划分（v0.1.61 当前架构）

- **`dash_http.py`** —— HTTP 路由（设置页 / 配置 / 页面 CRUD / 诊断接口）。管理面 127.0.0.1 限制是项目安全模型核心，**不要去掉**。
- **`dash_browser.py`** —— Chromium 生命周期 + **纯标准库 WebSocket**（RFC 6455）+ CDP 协议。
  新增了 `Browser.set_viewport(w, h, dpr=1.0)` 通过 CDP `Emulation.setDeviceMetricsOverride`
  强制 inner viewport——这是 v0.1.61 dashboard 3 列布局能在各种 headless 模式下都跑对的关键。
  扩展新 CDP 调用先在 `Browser.call()` 上层封装高层方法。
- **`fb_render.py`** —— fb 渲染循环 + `BrowserCanvas`（截图解码 / 缩放 / 旋转 / stretch）。
  修改 PIL 后端请保留 fallback。
- **`dash_config.py`** —— 配置白名单是项目的安全基线，所有外部输入必须过 `_sanitize`。
  v0.1.61 扩展：URL 页强制 `_fit_mode = "stretch"`、`_sanitize` 接受 `match_dashboard` / `match_fb_wide` /
  `url_desktop` 字面量 + `url_viewport_size` 列表。
- **`dash_pages.py`** —— 三类内容源统一抽象（`resolve_url`）。

---

## 🧪 自检清单（提交前必过）

- [ ] `python3 -m py_compile app/bin/*.py` 全部通过
- [ ] `python3 app/bin/dash_http.py --port 8280 --web app/web` 能启动
- [ ] `curl http://127.0.0.1:8280/api/status` 返回 ok
- [ ] `curl -X POST http://127.0.0.1:8280/api/config -d '{}' -H 'Content-Type: application/json'`
      从非本机返回 403（本机可用）
- [ ] fb 路径（如 `/dev/fb0`）不存在时仍能拉起 HTTP 服务，仅 fb 渲染进程不启动
- [ ] fb.log 出现 `Emulation.setDeviceMetricsOverride WxH dpr=1.0` + `Chromium ready (window=WxH)` 两行 banner
- [ ] URL 页面 fb0 看到 6 张卡完整（3×2 网格），无 dashboard 自带黑条

---

## 📐 代码风格

- Python：PEP 8 + 4 空格缩进；无 `from foo import *`
- HTML/JS：2 空格缩进；vanilla JS / vanilla CSS（无构建链）
- 中文注释 OK；变量名英文
- FBK 打包用 `K:\ESP\fnpack.exe build .`（cwd 必须 FPK 根，LF 行尾）

---

## 🐞 提 Issue

如发现 bug 或想要新功能，请开 Issue 描述：
- 重现步骤 / 期望行为 / 实际行为
- fnOS 版本、Chromium 版本（`chromium --version`）
- `/vol2/@appcenter/com.fnos.kiosk/bin/fb.log` 或 `fb_chromium.log` 相关片段
- fb0 截图（手机拍 NAS 副屏也行）

---

## 🔁 PR 流程

1. fork 后新建分支（`feature/<name>` 或 `fix/<name>`）
2. 本地通过自检清单
3. 提交 PR 描述：动机 + 改动点 + 是否影响向后兼容
4. 等 review + merge
5. **当前维护策略：单版本策略**——本项目当前只维护 v0.1.61 一个 release，PR 合并后发 v0.1.62 覆盖式发布，不会保留多版本历史。
