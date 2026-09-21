## v0.1.33 — 媒体文件自动生成 wrapper 填满 fb0

### 问题
升级到 v0.1.32 后，**首页系统信息模板**能全屏显示，但上传的 URL 和图片依旧不能全屏——图片只在屏幕中央显示原始像素大小，周围一片黑。

### 根因
浏览器在用 `<img src="file:///path/to/img.png">` 时，Chromium 自带的图片查看器只按图片**原始像素尺寸**渲染，浏览器背景是默认黑色。这就是为什么 800×600 的图片在 1024×768 的 fb0 上看起来"很小、居中、四周黑"。

URL 的情况不一样——Chromium 确实按 1024×768 全屏渲染了，但是 URL **自己**的页面布局决定了它是否填满（比如 HA 有自己的 margin/padding）。

### 修复
对每个上传的图片/视频，**自动生成一个同名的 `_wrap_<name>.html`** 包裹页，CSS 强制 img/video 元素铺满 viewport：

```css
html, body { margin:0; padding:0; width:100vw; height:100vh;
             overflow:hidden; background:#000 }
img, video { width:100vw; height:100vh; object-fit:contain;
             display:block }
```

`resolve_url` 检测到图片/视频时返回 wrapper URL 而非原始文件 URL；`delete` 同时清理 wrapper。

- 图片：保持纵横比居中显示，背景纯黑
- 视频：自动播放循环静音（headless Chromium 自动播放必须 muted）

### 升级到 v0.1.33 后
1. **fnOS 应用管理 → 卸载 fnos-kiosk**（不只是升级，因为 install_callback 一次性清理只在首次安装时跑）
2. 重新从 fnOS 应用商店安装 v0.1.33
3. 上传图片/视频，wrapper 会自动生成

### 已知限制
- 物理 16:9 面板 + fb0 1024×768 → 硬件 pillarbox 无法在应用层消除，需要改内核 cmdline `video=1920x1080@60` 后重启
- URL 全屏取决于 URL 自己是否填满 1024×768