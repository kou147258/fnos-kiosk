# 参与开发

欢迎加入 fnos-kiosk 开发！本项目沿袭 fnos-dashboard 的「零第三方 Python 依赖 +
纯原生 Web 前端」哲学，但因 headless Chromium 是渲染引擎，apt 依赖是不可避免的。

## ⚙️ 开发环境

```bash
git clone https://github.com/kou147258/fnos-kiosk.git
cd fnos-kiosk
# 安装 Chromium（任何发行版的 headless Chromium 即可）
sudo apt install -y chromium python3-pil
# 不需要 fnOS 也能跑（dashboard 会自动 fallback 到当前环境）
python3 app/bin/dashboard.py --port 8280 --web app/web
# 浏览器打开
open http://127.0.0.1:8280/
```

## 🧱 模块划分

- `dash_browser.py` —— Chromium 生命周期 + **纯标准库 WebSocket**（RFC 6455）
  + CDP 协议。如要扩展新 CDP 调用，先在 `Browser.call()` 上层封装高层方法。
- `fb_render.py` —— fb 渲染循环 + `BrowserCanvas`（截图解码 / 缩放 / 旋转）。
  修改 PIL 后端请保留 ASCII fallback（虽然这里不强制，但利于调试）。
- `dash_config.py` —— 配置白名单是项目的安全基线，所有外部输入必须过 `_sanitize`。
- `dash_http.py` —— 管理面 127.0.0.1 限制是项目安全模型核心，不要去掉。

## 🧪 自检清单（提交前必过）

- [ ] `python3 -m py_compile app/bin/*.py` 全部通过
- [ ] `python3 app/bin/dashboard.py --port 8280 --web app/web` 能启动
- [ ] `curl http://127.0.0.1:8280/api/status` 返回 ok
- [ ] `curl -X POST http://127.0.0.1:8280/api/settings -d '{}' -H 'Content-Type: application/json'`
      从非本机返回 403（本机可用）
- [ ] fb 路径（如 `/dev/fb0`）不存在时仍能拉起 dashboard，仅 fb 渲染进程不启动
- [ ] `tools/make_icons.py` 生成两个 PNG 不报错

## 📐 代码风格

- Python：PEP 8 + 4 空格缩进；无 `from foo import *`
- HTML/JS：2 空格缩进；vanilla JS / vanilla CSS（无构建链）
- 中文注释 OK；变量名英文

## 🐞 提 Issue

如发现 bug 或想要新功能，请开 Issue 描述：
- 重现步骤 / 期望行为 / 实际行为
- fnOS 版本、Chromium 版本（`chromium --version`）
- `/var/apps/com.fnos.kiosk/var/app.log` 或 `fb_chromium.log` 相关片段

## 🔁 PR 流程

1. fork 后新建分支（`feature/<name>` 或 `fix/<name>`）
2. 本地通过自检清单
3. 提交 PR 描述：动机 + 改动点 + 是否影响向后兼容
4. 等待 review + merge
