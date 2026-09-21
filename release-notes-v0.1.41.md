## v0.1.41 — auto-fit 改 body + 调试块 + MutationObserver

### 问题（用户截图反馈）
v0.1.40 的 URL auto-fit 看起来没生效，URL 仍然显示不全。

### 根因
v0.1.40 的注入脚本把 zoom 设在了 `<html>` 元素（`documentElement`）上。但 **`<html>` 不是有渲染盒子的元素**，headless Chromium 的 `style.zoom` 在 `<html>` 上**不生效**——zoom 只对 `<body>`、`<div>` 等有渲染盒子的元素起作用。

### 修复
- **改 `body.style.zoom`**：zoom 现在设在 body 上（Chromium 公认生效）
- **加调试小绿块**：左上角会显示 `fit 0.92 (1280x832→1024x768)`，**用户可以一眼看出脚本是否运行**、算出了什么 scale
- **MutationObserver 监听 DOM 变化**：SPA / AJAX 加载的内容会自动重新测量并 fit
- **更多重试延时**：200 / 800 / 2000 / 5000 / 10000ms

### 升级后验证
1. 卸载 fnos-kiosk → 重新装 v0.1.41
2. URL dashboard 加载后**左上角应该出现一个绿色小方块**，写着类似 `fit 0.92 (1280x832->1024x768)`——证明脚本运行了
3. 内容应该**自动缩放**到填满 fb0，所有 6 个卡片都能看到
4. **如果绿块没出现** = 脚本被拦截/失败，请截图 fb.log 发我

### 已知限制
- 调试小绿块是临时的，可以手动改默认 url_kiosk_css 去掉它（后续版本默认隐藏）
- 物理 16:9 面板 + fb0 1024×768 (4:3) → 硬件 pillarbox 仍需内核 cmdline `video=1920x1080@60`