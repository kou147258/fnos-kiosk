## v0.1.39 — 缩放/适配 真正热更新（无需重启应用）

### 问题（用户截图反馈）
1. **URL 页面总是显示不全**：URL 内容似乎一直只显示部分，看不到完整页面
2. **zoom/fit 设置后必须重启应用**：把缩放按钮从 300% 改到 100%，副屏上看不到变化；必须"应用停用 → 启用"才生效

### 根因（两个 bug 是同一个）
v0.1.25 引入 `display_fit=stretch` 时我做了个"优化"：在 fb_render 主循环里只检测 page.id 变化才调 `set_page()`。代价是同一页面改 zoom/fit/适配 后，`canvas._page` 仍是旧字典引用，begin() 读到旧 zoom：
- 用户实验 zoom=300%（v0.1.35 的新控件），但 zoom 控件"失效"，于是设置回 100%——但实际仍卡在 300%（应用不重启旧值不丢）
- v0.1.38 把 zoom 修好后，旧残留状态显现为"URL 总是只显示部分页面"（中心 1/9 区域）

### 修复
把 `set_page()` 改成幂等：
- 主循环**每帧**都调用 `set_page(page, kiosk_css=...)`
- 仅在 URL/path 实际变化时才重置 `_loaded_at`（触发重新导航 + 截图）
- 其它字段（zoom/fit/kiosk_css）改了立刻同步到 canvas 状态，**不重导航**（省 Chromium 重启开销）

### 验证覆盖
`test_idempotent.py`（项目根）跑了 8 个场景：
1. 首次 set → 触发导航
2. 同页面改 zoom → 不重导航
3. 同页面改 fit → 不重导航
4. 切换不同 URL → 重导航
5. 同页面再 set → 幂等不重导航
6. None page → 重置
7. media_file path 变 → 重导航
8. media_file 同 path 再 set → 幂等

### 升级步骤（必须卸载再装）
1. fnOS 应用管理 → 卸载 fnos-kiosk
2. 重新从 fnOS 应用商店装 v0.1.39
3. 设置 zoom/fit 后立刻看到效果（无需重启）

### 已知限制
- v0.1.38 zoom>1 仍然只显示中心区域（post-screenshot 变换的物理限制）；若你希望"整个内容放大"而不是"中心裁切放大"，需要重启 Chromium 调整 viewport（display_zoom 全局机制），告诉我可加方案