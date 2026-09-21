## v0.1.34 — URL 页面强制全屏（CDP CSS 注入）

### 问题
升级到 v0.1.33 后，**图片**能全屏了，但 **URL 页面**还是「看上去没填满 viewport」——比如 HA dashboard 这种 URL 自带 `body { margin: 8px }`、内部 `max-width: 1200px` 限制宽度子元素。

### 根因
Chromium **已经**按 1024×768 viewport 渲染 URL 了。但 URL 自己的 CSS（默认 margin、内部响应式布局、固定宽度子元素）让它看起来「没填满 fb0」。这不是 Chromium 的 bug，是 URL 自己不响应 1024×768 这个 viewport。

### 修复
新增 config 字段 **`url_kiosk_css`**（默认 200 多字节 reset CSS），通过 CDP `Page.addScriptToEvaluateOnNewDocument` 在每个 URL 页面加载时自动注入 `<style id="__kiosk_injected_css">` 到 `<head>`，`!important` 覆盖页面自身样式：

```css
html,body{margin:0!important;padding:0!important;
  width:100%!important;height:100%!important;
  background:#000!important;overflow:hidden!important}
body>*{max-width:100vw!important;max-height:100vh!important;
  box-sizing:border-box!important}
```

### 关键设计
- **只注入 type=url 页面**；type=html_file / media_file（kiosk 自己生成的 wrapper.html）不注入，避免破坏 kiosk 自身布局
- 每次 `set_kiosk_css` 调用先 `removeScriptToEvaluateOnNewDocument` 旧脚本、再注册新脚本——避免 `<style>` 元素越积越多
- 二次保险：DOMContentLoaded + window.load 后 100ms / 500ms 再 reapply，处理 SPA / 框架动态替换 head 的情况
- 跨导航跟踪：`_kiosk_css_applied` 元组缓存，避免每帧重发 CDP 调用
- 设置页「URL 全屏 CSS」textarea 实时显示当前值 + 「恢复默认」按钮
- 服务端 patch 校验：拒绝 `<script>` / `on*=` / `javascript:` / `expression()`，避免恶意 config 走 CDP 注入攻击

### 升级步骤（**必须卸载再装**）
1. fnOS 应用管理 → **卸载** fnos-kiosk
2. 重新从 fnOS 应用商店装 v0.1.34
3. 上传图片/视频会自动 wrapper；URL 会自动注入默认全屏 CSS

### 如果 URL 还是没填满
- 有些页面用了 shadow DOM / iframe 跨域——这些内容 kpiOS 控制不到，需要 URL 自己配合
- 进设置页 → 「URL 全屏 CSS」→ 改成更激进的 CSS（如 `* { margin:0!important } * { width:100vw!important }`）
- 留空 = 不注入，URL 按浏览器默认渲染

### 已知限制
- 物理 16:9 面板 + fb0 1024×768 (4:3) → 硬件 pillarbox 仍需内核 cmdline `video=1920x1080@60`