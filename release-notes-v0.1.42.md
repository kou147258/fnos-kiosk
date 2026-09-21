## v0.1.42 — 改默认 viewport 到 1280×960，让 dashboard 整页无黑边

### 问题（用户截图反馈）
v0.1.41 的 auto-fit 在跑（绿色调试块会出现），但 dashboard 仍然显示不全——dashboard 内容外面有黑色边框，不满 fb0。

### 根因
默认 Chromium viewport = fb 尺寸（1024×768），dashboard 自适应渲染到 1024×768 viewport；但 dashboard 的自然尺寸（1280×720）和 viewport 长宽比不同：
- viewport 4:3 (1024/768)
- dashboard 16:9 (1280/720)
- 即使 auto-fit 用 zoom 缩放，"宽够高不够"或"高够宽不够"必然留一边黑边

### 修复
改默认 `browser_window` 为 **`match_fb_wide`**（保持 fb 长宽比 ×1.25 = 1024×768 → **1280×960 viewport**）：
- dashboard 在 1280×960 viewport 里**完整填满**（3 列 × 2 行 + header）
- PIL scale 1280×960 → 1024×768 fb（×0.8 双轴，无 squish）
- **整页无黑边**，dashboard 像在真实浏览器里一样显示

### 升级后行为变化
- 设置页「窗口尺寸」默认选中**「自适应显示器 ×1.25」**（之前是「自适应显示器」= 严格匹配 fb）
- 用户可手动选其它预设（严格匹配 / 1024×768 / 1280×800 / 1920×1080 / 自定义）
- 老的 `match_fb` 字符串仍然支持（严格 1024×768）

### 升级步骤（必须卸载再装）
1. fnOS 应用管理 → 卸载 fnos-kiosk
2. 重新从 fnOS 应用商店装 v0.1.42
3. URL dashboard 应该**整页无黑边**填满 fb0

### 已知限制
- 物理 16:9 面板 + fb0 1024×768 (4:3) → 硬件 pillarbox 仍需内核 cmdline `video=1920x1080@60`