## v0.1.36 — 修复 v0.1.35 三个 bug

### Bug 1: fmtZ 显示错误（**轻微**）
**症状**：每个页面的"缩放"分段按钮，100% 显示成 "1%"，200% 显示成 "2%"，300% 显示成 "3%"。

**根因**：settings.js 里 `fmtZ` 函数用了 `"00".slice(0, 0)`——结果就是空字符串，整数倍 zoom 被剥掉了 "00"。

**修复**：改成 `Math.round(v * 100) + "%"`，统一整数百分比。

### Bug 2: per-page fit 被主循环覆盖（**严重**）
**症状**：v0.1.35 的核心功能——每页独立 fit（拉伸/完整可见/铺满裁切）——**完全失效**。用户在设置页把页面 A 改成"完整可见"，第一次渲染确实生效，下一帧就被覆盖回全局 display_fit 的"拉伸"。

**根因**：fb_render.py 主循环每次迭代都无条件 `canvas._fit_mode = cfg.display_fit`，但 `set_page()` 会在切页时根据 `page.fit` 设置 `_fit_mode`。主循环的覆盖发生在 set_page 之后、下一次 begin 之前，导致 per-page fit 在第二次渲染就丢失。

**修复**：主循环只在 `current_page.fit == "none"` 时才覆盖 `canvas._fit_mode`；per-page fit 时保留 set_page 设置的。

### Bug 3: url_kiosk_css 不热加载（**轻微**）
**症状**：v0.1.34 引入的"URL 全屏 CSS"功能，保存后要等下一次切页才生效。

**根因**：`url_kiosk_css` 不在 `fb_restart_needed` 白名单（不该触发 Chromium 重启），Chromium 不重启；`set_page()` 只在页面变化时调用，相同页面也读不到新 CSS。

**修复**：主循环每帧把 `cfg.url_kiosk_css` 推到 `canvas._kiosk_css_pending`；`begin()` 内会和 `_kiosk_css_applied` 比较并决定是否重新 `set_kiosk_css`。

### 升级步骤（必须卸载再装）
1. fnOS 应用管理 → **卸载** fnos-kiosk
2. 重新从 fnOS 应用商店装 v0.1.36
3. 升级后每页"适配"按钮实际生效（之前是装饰）；设置页改 URL 全屏 CSS 立即生效