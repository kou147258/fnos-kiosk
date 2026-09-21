## v0.1.43 — 中文字体 fallback + 强制 dashboard 容器样式

### 问题（用户截图反馈）
1. **个别字体显示乱码**（中文字符变豆腐块 / 缺字）
2. URL 仍不能完全像在浏览器里那样显示

### 根因
1. Debian 12 bookworm 默认**不带任何中文字体**——`apt install chromium` 装的 Chromium 用 fontconfig 找字体，但 `/usr/share/fonts/` 下没中文字体文件。中文 fallback 到 Latin 字体，Unicode 范围没覆盖，渲染豆腐块
2. Dashboard 的常见根容器（`#app` / `#root` / `.app` / `.container`）有自定义 width: 1280px、margin: 0 auto 等，我之前的 url_kiosk_css 没强制宽高 100%

### 修复（v0.1.43）

#### A. 字体 fallback 链
扩展默认 `url_kiosk_css` 加 font-family：

```css
html,body,body *{
  font-family:
    'Noto Sans CJK SC','Noto Sans CJK TC','Source Han Sans SC','Source Han Sans CN',
    'WenQuanYi Zen Hei','WenQuanYi Micro Hei',
    'PingFang SC','Hiragino Sans GB','Microsoft YaHei','Microsoft JhengHei',
    'SimHei','SimSun',sans-serif !important;
}
```

`!important` 覆盖 dashboard 自身的字体设置。

#### B. 强制 dashboard 容器宽高 100%

```css
#app,#root,.app,.container,section,main,article{
  width:100%!important;height:100%!important;max-width:none!important;
  font-family:inherit!important
}
svg,canvas{max-width:100%!important;height:auto!important}
```

#### C. **仍需 apt 安装字体**（kiosk 装不了字体，只能注入 fallback）
kiosk 自身只注入 CSS 让浏览器**优先选**这些字体——但 NAS 系统里必须装有这个字体文件：

```bash
ssh root@192.168.9.10
apt install fonts-noto-cjk fonts-wqy-microhei fonts-wqy-zenhei
# ~80MB，覆盖 7 万 + 汉字 + 拉丁 + 简繁
```

### 升级步骤（必须卸载再装）
1. fnOS 应用管理 → 卸载 fnos-kiosk
2. （可选，但强烈建议）`ssh` 上 NAS 跑 `apt install fonts-noto-cjk`
3. 重新装 v0.1.43
4. URL `http://192.168.9.22:8199/` 中文应正常显示

### 已知限制
- **未安装字体前，CSS 注入也救不了豆腐块**——font-family fallback 只是告诉浏览器"用哪个字体"，没装就没渲染数据
- 物理 16:9 面板 + fb0 1024×768 (4:3) → 硬件 pillarbox 仍需内核 cmdline `video=1920x1080@60`