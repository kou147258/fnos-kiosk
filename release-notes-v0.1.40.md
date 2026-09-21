## v0.1.40 — URL 内容自动缩放填满 fb0

### 问题（用户截图反馈）
URL `http://192.168.9.22:8199/`（带 dashboard）只显示了 CPU + 内存 + 部分网络，看不到存储空间 / 温度 / 系统信息等其他卡片。

### 根因
dashboard 是给 1280+ 宽 viewport 设计的 3 列网格布局，Chromium viewport 默认 1024×768（match_fb）下右、下方卡片被 viewport 裁掉；v0.1.34 引入的 `url_kiosk_css` 强制 `overflow:hidden` 让 dashboard 自己的滚动条也失效。

### 修复
在 `set_kiosk_css` 的 `Page.addScriptToEvaluateOnNewDocument` 注入脚本里**追加**一段 auto-fit JS：

```javascript
function __kioskFit() {
  var de = document.documentElement;
  var w = Math.max(de.scrollWidth, de.offsetWidth);
  var h = Math.max(de.scrollHeight, de.offsetHeight);
  var ww = window.innerWidth || de.clientWidth || 1024;
  var wh = window.innerHeight || de.clientHeight || 768;
  if (!w || !h || !ww || !wh) return;
  var s = Math.min(ww/w, wh/h, 1);
  if (s < 0.05 || s > 1) s = 1;
  de.style.zoom = s;
}
```

- 内容比 viewport 小时 s=1 → 不变
- 内容超出 viewport 时按比例自动缩小到铺满
- 多次重试（200ms / 800ms / 2s + load + resize）覆盖 SPA 异步渲染
- 尺寸异常都兜底到 s=1

### 升级步骤（必须卸载再装）
1. fnOS 应用管理 → 卸载 fnos-kiosk
2. 重新从 fnOS 应用商店装 v0.1.40
3. URL 重新设置（v0.1.39 install_callback 已跑过）

### 已知限制
- 物理 16:9 面板 + fb0 1024×768 (4:3) → 硬件 pillarbox 仍需内核 cmdline `video=1920x1080@60`
- 自动 zoom 在 Chromium 内置 PDF viewer / iframe 跨域页面可能不生效