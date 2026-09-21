## v0.1.38 — per-page zoom 真正生效

### 问题（用户截图反馈）
v0.1.35 引入的"每页缩放"按钮（50%/67%/75%/100%/125%/150%/200%/250%/300%）**完全没效果**——把 zoom 设到 300%，副屏上的画面还是原尺寸。

### 根因
v0.1.25 引入 `display_fit=stretch`（默认填满 fb）后，`_render_background` 的 stretch 分支会把截图 resize 回 fb 尺寸：
```python
if fit_mode == "stretch":
    if (bw, bh) != (self.w, self.h):
        pil_img = pil_img.resize((self.w, self.h), LANCZOS)
```

之前的实现先 PIL 把 shot 缩到 N 倍（zoom>1 → N 倍大），再交给 `_render_background`——结果 stretch 一行直接把 zoom 抵消了。

**事实上对所有 display_fit 都失效**：
- stretch：N 倍图 → resize 回 fb（抵消）
- contain：N 倍图 → 等比缩到 fb（s=N 倍分之一的 s，还原 fb 尺寸）
- cover：同上（s=min/max，反正还是 fb 尺寸）

### 修复
在 `begin()` 内就完成 zoom 的几何变换（不再让 `_render_background` 处理）：
- **zoom > 1**：upscale 到 N 倍 → 取中心 fb 区域 → 用户看到的内容变少但每样东西变大
- **zoom < 1**：downscale 到 N 倍 → `_render_background` 在 fb 中心粘贴，剩下黑边 → 用户看到的内容变多但每样东西变小
- **zoom == 1**：原样

`_render_background(shot, zoom_applied=zoom)` 多了一个 zoom_applied 参数，对 zoom<1 的 shot 强制居中黑边（不能 stretch，否则又抵消了）。

### 升级步骤（必须卸载再装）
1. fnOS 应用管理 → 卸载 fnos-kiosk
2. 重新从 fnOS 应用商店装 v0.1.38
3. 把页面的"缩放"按钮点到 200% 应该立刻看到内容**变大**（看到的内容变少）；点到 50% 应该看到内容**变小**（看到的内容更多但有黑边）

### 已知副作用
- zoom>1 时显示的是**中心区域**（不是整个内容放大）。这是单次截图后期变换的物理限制；要做到"整个内容放大"，需要 Chromium viewport 调整（即全局 display_zoom 行为），那会触发 Chromium 重启——开销太大。当前 post-screenshot 实现保留了 Chromium viewport 不变，只是后期裁切中心。

### 已知限制
- 物理 16:9 面板 + fb0 1024×768 (4:3) → 硬件 pillarbox 仍需内核 cmdline `video=1920x1080@60`