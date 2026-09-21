## v0.1.44 — 强制 body 直接子元素铺满 viewport

### 问题
v0.1.42 viewport = 1280×960（fb 的 4:3 ×1.25），dashboard 在里面自适应。
v0.1.43 加了字体 fallback 和 #app/.container 等常见 wrapper 强制宽高 100%。
**但仍不够**：很多 dashboard 的第一层 wrapper 就在 `body` 下（不是 #app 等命名），它们继承了 body 的 100% 但内部卡片还是按 dashboard 自己 CSS 的尺寸排列——外面留黑边。

### 修复（v0.1.44）
默认 `url_kiosk_css` 增加更激进的强制：

```css
/* body 直接子元素强制铺满 viewport */
body > * {
  width:100vw !important; height:100vh !important;
  margin:0 !important; padding:0 !important;
  max-width:none !important; max-height:none !important;
  box-sizing:border-box !important;
}

/* body 孙元素也强制铺满 */
body > * > * {
  width:100% !important; height:100% !important;
  max-width:none !important; max-height:none !important;
}

/* 常见 dashboard wrapper 强制 flex 列布局 */
#app, #root, .app, .container, .wrapper, .main, .content,
.layout, .dashboard, .page, section, main, article {
  width:100% !important; height:100% !important;
  max-width:none !important; font-family:inherit !important;
  display:flex !important; flex-direction:column !important;
}
```

任何 dashboard 只要第一层 wrapper 在 body 下，都会被强制 100vw×100vh 铺满 viewport。

### 升级步骤
1. fnOS 应用管理 → 卸载 fnos-kiosk
2. （强烈建议）`ssh root@192.168.9.10 && apt install fonts-noto-cjk`
3. 重新装 v0.1.44
4. URL dashboard 应该**整页铺满 fb0**（之前是 viewport 边界但 fb0 边缘可能黑边）

### 已知限制
- **未装字体前**，v0.1.43 的字体 fallback 链也没用——必须 apt install
- **物理 16:9 面板 + fb0 1024×768 (4:3)** → 硬件 pillarbox 仍需内核 cmdline `video=1920x1080@60`