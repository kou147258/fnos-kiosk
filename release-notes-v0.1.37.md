## v0.1.37 — 跨平台 file:// URL 修复

### 问题
v0.1.36 二轮核查时发现：老代码 `"file://" + path.replace(os.sep, "/")` 在 Windows 上产出 `file://C:/...`（少一个 `/`），Chromium 无法解析（协议头 `file://` + 主机名 `C:` 无效）。

Linux 上 `/var/lib/...` 拼接出来正好是 `file:///var/lib/...`（三个 `/`），所以用户 NAS（Debian Linux）不受影响。

### 修复
新增 `_file_url(path)` 辅助函数：
- Linux 绝对路径 `/var/lib/...` → `file:///var/lib/...`
- Windows 绝对路径 `C:\Users\...` → `file:///C:/Users/...`
- 三个斜杠，跨平台统一

应用范围：
1. wrapper HTML 的 `<img src>` / `<video src>`
2. `PageStore.to_file_url()` 返回值（wrapper URL + HTML/SVG 直链）

### 升级步骤（必须卸载再装）
1. fnOS 应用管理 → 卸载 fnos-kiosk
2. 重新从 fnOS 应用商店装 v0.1.37
3. 用户无感（Linux 上输出和之前完全一致）

### 测试覆盖
- `test_smoke.py`（项目根目录）覆盖了所有 v0.1.35/36/37 关键路径：跨平台 file URL、per-page fit、url_kiosk_css 校验、wrapper fit 三档、fmtZ 显示