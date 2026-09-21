## v0.1.35 — 每页独立缩放 + 画面适配模式

### 问题
每个页面只有一个数字输入框调缩放（不直观），图片也没法切换「铺满裁切 vs 完整可见」。

### 新增
1. **每页"缩放"换成 9 档分段按钮**：`50% / 67% / 75% / 100% / 125% / 150% / 200% / 250% / 300%` + 自定义数值输入框（0.3 ~ 3.0，0.05 步进）。preset 不在列表里时高亮自动取消。
2. **每页新增"适配"分段按钮**：`默认 / ↔ 拉伸 / 📐 完整可见 / 🖼 铺满裁切`。`默认` 走全局 display_fit；显式选择则覆盖全局（仅对本页生效）。
3. **对 type=media_file 页面**：fit 切换会**自动重生成 wrapper HTML** 改 object-fit（`contain` 完整可见 / `cover` 铺满裁切 / `fill` 强制拉伸）。
4. **服务端校验**：`fit` 字段白名单 `contain / cover / stretch / none`，无效值兜底 `none`。
5. **`/api/settings` 保存时**：调用 `_sync_page_wrappers` 扫描 fit 实际变化的页面触发 wrapper 重生成，没变的不动（不浪费 IO）。

### 设计权衡
- 缩放是 **post-screenshot 缩放**（PIL resize 截图），URL/图片都一样生效；不会改 Chromium 窗口大小
- 适配是 **post-screenshot fit**（同样的 fit 逻辑 + 三种 object-fit 影响 wrapper 内 img/video 渲染）
- 缩放 100% 适配默认 = 当前 v0.1.34 行为；想恢复 v0.1.33 之前的行为：每页适配选「默认」+ 全局 display_fit 改 contain

### 升级步骤（必须卸载再装）
1. fnOS 应用管理 → 卸载 fnos-kiosk
2. 重新从 fnOS 应用商店装 v0.1.35
3. 老的媒体文件 wrapper 还是 object-fit:contain；想换 cover/fill 进设置页改 fit 即时生效

### 已知限制
- 物理 16:9 面板 + fb0 1024×768 (4:3) → 硬件 pillarbox 仍需内核 cmdline `video=1920x1080@60`