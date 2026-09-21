/* fnOS 浏览器屏 —— 设置页逻辑 */
"use strict";

var THEMES = [
  { id: "midnight", name: "午夜蓝" },
  { id: "graphite", name: "石墨黑" },
  { id: "emerald", name: "翡翠绿" },
  { id: "solar", name: "日光橙" },
  { id: "sakura", name: "樱粉" },
  { id: "light", name: "云白" },
];

var cfg = null;        // 当前配置（可编辑副本）
var localFiles = [];   // var/pages/ 文件列表

function api(method, url, body, raw) {
  var opts = { method: method };
  if (body !== undefined) {
    if (raw) opts.body = body;
    else { opts.headers = { "Content-Type": "application/json" }; opts.body = JSON.stringify(body); }
  }
  return fetch(url, opts).then(function (r) {
    return r.json().catch(function () { throw new Error("HTTP " + r.status); })
      .then(function (j) {
        if (!r.ok || j.ok === false) throw new Error(j.error || ("HTTP " + r.status));
        return j;
      });
  });
}

function toast(msg, isError) {
  var el = document.getElementById("toast");
  el.textContent = msg;
  el.classList.remove("hidden", "error");
  if (isError) el.classList.add("error");
  clearTimeout(el._t);
  el._t = setTimeout(function () { el.classList.add("hidden"); }, 3000);
}

// ---------- Tabs ----------
document.getElementById("tabs").addEventListener("click", function (e) {
  var btn = e.target.closest("button[data-tab]");
  if (!btn) return;
  document.querySelectorAll("#tabs button").forEach(function (b) { b.classList.remove("active"); });
  btn.classList.add("active");
  document.querySelectorAll(".tab").forEach(function (s) { s.classList.remove("active"); });
  document.getElementById("tab-" + btn.dataset.tab).classList.add("active");
});

// ---------- 页面编辑器 ----------
function newPage() {
  return {
    id: "page" + Date.now().toString(36).slice(-4),
    name: "新页面",
    type: "url",
    url: "https://example.com",
    path: "",
    mode: "cycle",
    refresh_seconds: 0,
    zoom: 1.0,
    fit: "none",
    enabled: true,
  };
}

function renderPageList() {
  var list = document.getElementById("page-list");
  list.textContent = "";
  cfg.pages.forEach(function (p, idx) {
    // v0.1.30: 跳过模板类型（已废弃）。理论上 _sanitize_page 已经丢弃了，这里再防御一道。
    if (p.type === "template") return;
    var div = document.createElement("div");
    div.className = "page-edit";

    // 名字 + ID
    var row1 = document.createElement("div");
    row1.className = "row full";
    var lab1 = document.createElement("span"); lab1.className = "label-mini"; lab1.textContent = "名称";
    var in1 = document.createElement("input"); in1.type = "text"; in1.value = p.name || "";
    in1.addEventListener("input", function () { p.name = in1.value; });
    row1.appendChild(lab1); row1.appendChild(in1);
    div.appendChild(row1);

    // 类型（v0.1.30: 移除「✨ 内置模板」选项）
    var row2 = document.createElement("div");
    row2.className = "row";
    var lab2 = document.createElement("span"); lab2.className = "label-mini"; lab2.textContent = "类型";
    var sel = document.createElement("select");
    [["url", "🌐 远程 URL"], ["html_file", "📝 本地 HTML"], ["media_file", "🎬 媒体文件（图片/视频）"]].forEach(function (o) {
      var op = document.createElement("option");
      op.value = o[0]; op.textContent = o[1];
      if (p.type === o[0]) op.selected = true;
      sel.appendChild(op);
    });
    sel.style.cssText = "background:rgba(0,0,0,.3);color:var(--text);border:1px solid var(--card-brd);border-radius:6px;padding:4px 6px;font-size:12px;font-family:inherit;flex:1";
    sel.addEventListener("change", function () {
      p.type = sel.value;
      renderPageList();
    });
    row2.appendChild(lab2); row2.appendChild(sel);
    div.appendChild(row2);

    // 模式
    var row3 = document.createElement("div");
    row3.className = "row";
    var lab3 = document.createElement("span"); lab3.className = "label-mini"; lab3.textContent = "模式";
    var seg = document.createElement("div"); seg.className = "seg";
    ["cycle", "single"].forEach(function (m) {
      var b = document.createElement("button");
      b.type = "button"; b.textContent = m === "cycle" ? "轮换" : "全屏";
      if (p.mode === m) b.classList.add("active");
      b.addEventListener("click", function () {
        p.mode = m; renderPageList();
      });
      seg.appendChild(b);
    });
    row3.appendChild(lab3); row3.appendChild(seg);
    div.appendChild(row3);

    // URL / path（按 type 切换；v0.1.30: 不再有 template 类型）
    var rowUrl = document.createElement("div");
    rowUrl.className = "row full";
    if (p.type === "url") {
      var labU = document.createElement("span"); labU.className = "label-mini"; labU.textContent = "URL";
      var inU = document.createElement("input"); inU.type = "text"; inU.placeholder = "https://...";
      inU.value = p.url || "";
      inU.setAttribute("list", "recent-urls");   // 自动补全历史 URL
      inU.addEventListener("input", function () { p.url = inU.value; });
      rowUrl.appendChild(labU); rowUrl.appendChild(inU);
    } else {
      var labP = document.createElement("span"); labP.className = "label-mini"; labP.textContent = "文件";
      var sel2 = document.createElement("select");
      sel2.style.cssText = "background:rgba(0,0,0,.3);color:var(--text);border:1px solid var(--card-brd);border-radius:6px;padding:4px 6px;font-size:12px;font-family:inherit;flex:1";
      if (!localFiles.length) {
        var op = document.createElement("option"); op.value = ""; op.textContent = "（请先在「高级」里创建文件）"; sel2.appendChild(op);
      }
      localFiles.forEach(function (f) {
        var op = document.createElement("option"); op.value = f.name; op.textContent = f.name;
        if (p.path === f.name) op.selected = true;
        sel2.appendChild(op);
      });
      if (p.path) sel2.value = p.path;
      sel2.addEventListener("change", function () { p.path = sel2.value; });
      rowUrl.appendChild(labP); rowUrl.appendChild(sel2);
    }
    div.appendChild(rowUrl);

    // 刷新间隔 + zoom
    var row4 = document.createElement("div");
    row4.className = "row";
    var labR = document.createElement("span"); labR.className = "label-mini"; labR.textContent = "刷新(秒)";
    var inR = document.createElement("input"); inR.type = "number"; inR.min = 0; inR.max = 86400;
    inR.value = p.refresh_seconds || 0;
    inR.addEventListener("input", function () {
      p.refresh_seconds = parseInt(inR.value, 10) || 0;
    });
    row4.appendChild(labR); row4.appendChild(inR);
    div.appendChild(row4);

    var row5 = document.createElement("div");
    row5.className = "row";
    row5.style.flexWrap = "wrap";
    var labZ = document.createElement("span"); labZ.className = "label-mini";
    labZ.textContent = "缩放";
    labZ.style.minWidth = "48px";
    // v0.1.35: 缩放改为 9 档分段按钮 + 自定义输入。预设值 [50, 67, 75, 100, 125,
    // 150, 200, 250, 300]%，点击直接应用；自定义值输入框用于精细调节（如 1.15）。
    var ZOOM_PRESETS = [0.5, 0.67, 0.75, 1.0, 1.25, 1.5, 2.0, 2.5, 3.0];
    function fmtZ(v) {
      // 整数百分比：100% / 125% 等；统一用 (v*100).toFixed(0) 避免 1.0 → "1%" 的 bug
      return Math.round(v * 100) + "%";
    }
    var segZ = document.createElement("div");
    segZ.className = "seg";
    segZ.id = "seg-page-zoom-" + (p.id || idx);
    segZ.style.flexWrap = "wrap";
    ZOOM_PRESETS.forEach(function (v) {
      var b = document.createElement("button");
      b.type = "button";
      b.dataset.v = String(v);
      b.textContent = fmtZ(v);
      b.addEventListener("click", function () {
        p.zoom = v;
        renderPageList();  // 重新渲染以刷新高亮
      });
      segZ.appendChild(b);
    });
    var cur = parseFloat(p.zoom || 1.0);
    segZ.querySelectorAll("button").forEach(function (b) {
      var v = parseFloat(b.dataset.v);
      b.classList.toggle("active", Math.abs(v - cur) < 0.005);
    });
    var inZ = document.createElement("input");
    inZ.type = "number"; inZ.min = 0.3; inZ.max = 3; inZ.step = 0.05;
    inZ.style.width = "72px";
    inZ.title = "自定义缩放（0.3 ~ 3.0）";
    inZ.value = (p.zoom != null) ? p.zoom : 1.0;
    inZ.addEventListener("input", function () {
      var v = parseFloat(inZ.value);
      if (!isNaN(v) && v >= 0.3 && v <= 3) {
        p.zoom = v;
        // 取消 seg 高亮（不在预设列表里）
        segZ.querySelectorAll("button").forEach(function (b) {
          b.classList.remove("active");
        });
      }
    });
    row5.appendChild(labZ);
    row5.appendChild(segZ);
    row5.appendChild(inZ);
    div.appendChild(row5);

    // v0.1.35: per-page 画面适配模式（none/stretch/contain/cover）
    // "none"（默认）→ 跟随全局 display_fit；显式选择 → 覆盖全局
    // 对 type=media_file 同时触发 wrapper 重生成（contain/cover/fill 改 object-fit）
    var row6 = document.createElement("div");
    row6.className = "row";
    row6.style.flexWrap = "wrap";
    var labF = document.createElement("span"); labF.className = "label-mini";
    labF.textContent = "适配";
    labF.style.minWidth = "48px";
    var FIT_OPTIONS = [
      ["none", "默认（跟随全局）"],
      ["stretch", "↔ 拉伸"],
      ["contain", "📐 完整可见"],
      ["cover", "🖼 铺满裁切"]
    ];
    var segF = document.createElement("div");
    segF.className = "seg";
    FIT_OPTIONS.forEach(function (o) {
      var b = document.createElement("button");
      b.type = "button";
      b.dataset.v = o[0];
      b.textContent = o[1];
      b.addEventListener("click", function () {
        p.fit = o[0];
        renderPageList();
      });
      segF.appendChild(b);
    });
    var curFit = (p.fit || "none");
    segF.querySelectorAll("button").forEach(function (b) {
      b.classList.toggle("active", b.dataset.v === curFit);
    });
    row6.appendChild(labF);
    row6.appendChild(segF);
    div.appendChild(row6);

    // 启用 + 删除 + 上移/下移
    var acts = document.createElement("div");
    acts.className = "actions";
    var lbl = document.createElement("label");
    lbl.style.cssText = "display:flex;align-items:center;gap:6px;font-size:12px;color:var(--dim);flex:1";
    var cb = document.createElement("input"); cb.type = "checkbox"; cb.checked = p.enabled !== false;
    cb.addEventListener("change", function () { p.enabled = cb.checked; });
    lbl.appendChild(cb);
    lbl.appendChild(document.createTextNode("启用"));
    acts.appendChild(lbl);
    function btn(label, fn, danger) {
      var b = document.createElement("button");
      b.type = "button"; b.textContent = label;
      b.className = "btn-mini" + (danger ? " danger" : "");
      b.addEventListener("click", fn);
      return b;
    }
    acts.appendChild(btn("↑ 上移", function () {
      if (idx > 0) {
        var t = cfg.pages[idx - 1];
        cfg.pages[idx - 1] = cfg.pages[idx];
        cfg.pages[idx] = t;
        renderPageList();
      }
    }));
    acts.appendChild(btn("↓ 下移", function () {
      if (idx < cfg.pages.length - 1) {
        var t = cfg.pages[idx + 1];
        cfg.pages[idx + 1] = cfg.pages[idx];
        cfg.pages[idx] = t;
        renderPageList();
      }
    }));
    acts.appendChild(btn("删除", function () {
      cfg.pages.splice(idx, 1); renderPageList();
    }, true));
    div.appendChild(acts);

    list.appendChild(div);
  });
}

document.getElementById("btn-page-add").addEventListener("click", function () {
  cfg.pages.push(newPage());
  renderPageList();
});

// ---------- 默认模式 ----------
document.getElementById("seg-mode").addEventListener("click", function (e) {
  var b = e.target.closest("button");
  if (!b) return;
  document.querySelectorAll("#seg-mode button").forEach(function (x) { x.classList.remove("active"); });
  b.classList.add("active");
  cfg.default_mode = b.dataset.v;
});

// ---------- 显示 ----------
document.getElementById("seg-rotate").addEventListener("click", function (e) {
  var b = e.target.closest("button");
  if (!b) return;
  document.querySelectorAll("#seg-rotate button").forEach(function (x) { x.classList.remove("active"); });
  b.classList.add("active");
  cfg.fb_rotate = parseInt(b.dataset.v, 10);
});

document.getElementById("seg-fit").addEventListener("click", function (e) {
  var b = e.target.closest("button");
  if (!b) return;
  document.querySelectorAll("#seg-fit button").forEach(function (x) { x.classList.remove("active"); });
  b.classList.add("active");
  cfg.display_fit = b.dataset.v;
});

document.getElementById("seg-zoom").addEventListener("click", function (e) {
  var b = e.target.closest("button");
  if (!b) return;
  document.querySelectorAll("#seg-zoom button").forEach(function (x) { x.classList.remove("active"); });
  b.classList.add("active");
  cfg.display_zoom = parseFloat(b.dataset.v);
});

document.getElementById("seg-win-preset").addEventListener("click", function (e) {
  var b = e.target.closest("button");
  if (!b) return;
  document.querySelectorAll("#seg-win-preset button").forEach(function (x) { x.classList.remove("active"); });
  b.classList.add("active");
  var v = b.dataset.v;
  if (v === "custom") {
    // 不动 cfg，让用户用下方两个输入框
    return;
  }
  if (v === "match_fb") {
    cfg.browser_window = "match_fb";
  } else {
    var parts = v.split(",");
    cfg.browser_window = [parseInt(parts[0], 10), parseInt(parts[1], 10)];
    document.getElementById("set-win-w").value = parts[0];
    document.getElementById("set-win-h").value = parts[1];
  }
});

function renderAuthInfo(info) {
  // 在「浏览器」tab 顶部展示登录态信息
  var stateEl = document.getElementById("auth-state");
  var pathEl = document.getElementById("profile-path-show");
  if (pathEl && info && info.profile_dir) pathEl.textContent = info.profile_dir;
  if (stateEl) {
    if (info && info.profile_exists) {
      stateEl.innerHTML = '<span style="color:var(--ok)">✓ Profile 已就绪</span> —— 浏览器登录态会自动持久化。';
    } else {
      stateEl.innerHTML = '<span style="color:var(--dim)">⌛ Profile 未创建</span> —— 首次导航时自动生成。';
    }
  }
}

document.getElementById("btn-auth-reset").addEventListener("click", function () {
  if (!confirm("确认清空所有登录态？包括 cookies / localStorage / 已存密码。\n渲染器将重建 Chromium 并要求重新登录。")) return;
  api("POST", "api/auth/reset", {})
    .then(function (j) {
      toast("已重置登录态：" + (j.msg || ""));
      loadFbInfo();
    })
    .catch(function (e) { toast(e.message || "重置失败", true); });
});

document.getElementById("btn-fb-restart").addEventListener("click", function () {
  var btn = this;
  btn.disabled = true;
  btn.textContent = "重启中…";
  api("POST", "api/fb/restart", {})
    .then(function (j) { toast(j.msg || "已重启"); loadFbInfo(); })
    .catch(function (e) { toast(e.message || "重启失败", true); })
    .then(function () { btn.disabled = false; btn.textContent = "🔄 手动重启渲染进程"; });
});

document.getElementById("btn-fb-log").addEventListener("click", function () {
  var el = document.getElementById("fb-log");
  if (!el) return;
  if (el.classList.contains("hidden")) {
    api("GET", "api/fb/log").then(function (j) {
      el.textContent = j.log || "（无日志）";
      el.classList.remove("hidden");
    }).catch(function (e) { toast(e.message || "读取失败", true); });
  } else {
    el.classList.add("hidden");
  }
});

document.getElementById("btn-fb-diag").addEventListener("click", function () {
  var el = document.getElementById("fb-diag");
  if (!el) return;
  if (el.classList.contains("hidden")) {
    api("GET", "api/fb/diag").then(function (j) {
      var d = j.diag || {};
      var lines = [];
      // fb0 状态
      lines.push("=== fb0 ===");
      lines.push("存在: " + (d.fb0_exists ? "✓" : "✗"));
      if (d.fb0_exists) {
        lines.push("权限: " + (d.fb0_mode_octal || "?") +
                   "  uid=" + (d.fb0_uid || "?") +
                   "  gid=" + (d.fb0_gid || "?"));
        lines.push("可读: " + (d.fb0_readable ? "✓" : "✗") +
                   "  可写: " + (d.fb0_writable ? "✓" : "✗"));
        lines.push("规格: " + (d.fb0_virtual_size || "?") + " @ " +
                   (d.fb0_bpp || "?") + "bpp");
      }
      lines.push("");
      // 进程身份
      lines.push("=== 当前进程身份 ===");
      lines.push("uid=" + (d.puid || "?") + "  gid=" + (d.pgid || "?"));
      lines.push("video 组存在: " + (d.video_gid != null ? "✓ (gid=" + d.video_gid + ")" : "✗"));
      lines.push("当前进程在 video 组: " + (d.in_video_group ? "✓" : "✗"));
      lines.push("");
      // 进程状态
      lines.push("=== 渲染 / watchdog ===");
      lines.push("fb_render: " + (d.fb_render_alive ?
        "运行中 (PID " + d.fb_render_pid + ")" :
        "未运行" + (d.fb_render_pid ? "（残留 PID " + d.fb_render_pid + "）" : "")));
      lines.push("watchdog: " + (d.watchdog_alive ? "运行中" : "未运行"));
      lines.push("");
      // 依赖
      lines.push("=== 依赖 ===");
      lines.push("chromium: " + (d.chromium_path ?
          (d.chromium_name + " → " + d.chromium_path) : "✗ 未找到"));
      lines.push("python3-PIL: " + (d.pil_available ? "✓" : "✗ 缺失"));
      lines.push("profile 目录: " + (d.profile_exists ? "✓ 已创建" : "未创建") +
                 " (" + (d.profile_dir || "?") + ")");
      lines.push("");
      // 配置
      lines.push("=== 配置 ===");
      lines.push("fb_enabled: " + (d.fb_enabled_in_config ? "true" : "false"));
      lines.push("已配置页面数: " + (d.pages_count || 0));
      lines.push("");
      // fb.log
      lines.push("=== fb.log 末尾 ===");
      lines.push(d.fb_log_tail || "（无日志）");
      el.textContent = lines.join("\n");
      el.classList.remove("hidden");
    }).catch(function (e) { toast(e.message || "诊断失败", true); });
  } else {
    el.classList.add("hidden");
  }
});

document.getElementById("btn-login-help").addEventListener("click", function () {
  var h = document.getElementById("login-help");
  if (h) h.classList.toggle("hidden");
});

function renderFbInfo(info) {
  var el = document.getElementById("fb-info");
  if (!info || !info.exists) {
    el.innerHTML = "未检测到 <b>/dev/fb0</b>（当前环境无帧缓冲输出设备）。";
    return;
  }
  var lines = [];
  lines.push("分辨率 <b>" + info.w + " × " + info.h + "</b> @ " + info.bpp + "bpp");
  lines.push("渲染进程：" + (info.renderer_running
    ? '<span class="ok">运行中</span>（PID ' + info.renderer_pid + "）"
    : '<span class="bad">未运行</span>（保存设置后会自动拉起）'));
  el.innerHTML = lines.join("<br>");
  // 端口信息
  var httpPort = document.getElementById("port-http");
  var cdpPort = document.getElementById("port-cdp");
  if (httpPort && info.http_port) httpPort.textContent = info.http_port;
  if (cdpPort && info.cdp_port) cdpPort.textContent = info.cdp_port;
}

// ---------- 本地 HTML 文件 ----------
function renderLocalList() {
  var list = document.getElementById("local-edit-list");
  list.textContent = "";
  if (!localFiles.length) {
    var empty = document.createElement("div");
    empty.style.cssText = "color:var(--dim);font-size:13px;padding:8px";
    empty.textContent = "暂无文件。在上方上传或新建 HTML。";
    list.appendChild(empty);
    return;
  }
  localFiles.forEach(function (f) {
    var row = document.createElement("div");
    row.className = "page-item";
    var dot = document.createElement("span"); dot.className = "dot";
    var icon = document.createElement("span");
    icon.style.cssText = "font-size:14px;min-width:18px;text-align:center";
    icon.textContent = f.kind === "image" ? "🖼" :
      f.kind === "video" ? "🎬" :
      f.kind === "html" ? "📝" : "📄";
    var name = document.createElement("span");
    name.className = "name"; name.textContent = f.name;
    name.style.cursor = "pointer";
    name.addEventListener("click", function () {
      // 文本类（HTML/SVG）→ 读 raw 写入编辑器
      if (f.kind === "html" || f.kind === "other") {
        api("GET", "api/pages/raw?name=" + encodeURIComponent(f.name))
          .then(function (j) {
            document.getElementById("local-name").value = f.name;
            document.getElementById("local-content").value = j.content;
          })
          .catch(function (e) { toast(e.message, true); });
      } else {
        // 媒体类 → 在新窗口预览
        window.open("api/pages/file?name=" + encodeURIComponent(f.name),
                    "_blank");
      }
    });
    var detail = document.createElement("span");
    detail.className = "url";
    detail.textContent = (f.size / 1024).toFixed(1) + " KB · " +
      new Date(f.mtime * 1000).toLocaleString("zh-CN") + " · " +
      (f.mime || "");
    var delBtn = document.createElement("button");
    delBtn.className = "btn-mini danger";
    delBtn.textContent = "🗑 删除";
    delBtn.style.cssText = "margin-left:auto;padding:2px 8px;font-size:12px";
    delBtn.addEventListener("click", function (e) {
      e.stopPropagation();
      if (!confirm("确认删除文件 " + f.name + "？\n（页面 tab 中引用此文件的 URL 配置也会失效）")) return;
      api("POST", "api/pages/delete", { name: f.name })
        .then(function () { toast("已删除 " + f.name); loadLocalFiles(); })
        .catch(function (err) { toast(err.message || "删除失败", true); });
    });
    row.appendChild(dot);
    row.appendChild(icon);
    row.appendChild(name);
    row.appendChild(detail);
    row.appendChild(delBtn);
    list.appendChild(row);
  });
}

document.getElementById("btn-local-save").addEventListener("click", function () {
  var name = document.getElementById("local-name").value.trim();
  var content = document.getElementById("local-content").value;
  if (!name) return toast("请填写文件名", true);
  api("POST", "api/pages/save", { name: name, content: content })
    .then(function () {
      toast("已保存 " + name);
      loadLocalFiles();
    })
    .catch(function (e) { toast(e.message || "保存失败", true); });
});
document.getElementById("btn-local-delete").addEventListener("click", function () {
  var name = document.getElementById("local-name").value.trim();
  if (!name) return toast("请先选择文件", true);
  if (!confirm("确认删除 " + name + "？")) return;
  api("POST", "api/pages/delete", { name: name })
    .then(function () {
      toast("已删除");
      document.getElementById("local-name").value = "";
      document.getElementById("local-content").value = "";
      loadLocalFiles();
    })
    .catch(function (e) { toast(e.message || "删除失败", true); });
});
document.getElementById("btn-local-new").addEventListener("click", function () {
  document.getElementById("local-name").value = "new.html";
  document.getElementById("local-content").value =
    "<!DOCTYPE html>\n<html>\n<head><meta charset=\"UTF-8\">\n" +
    "<title>新页面</title>\n<style>\nbody{margin:0;padding:24px;background:#0e1013;color:#e7eaf0;font-family:sans-serif}\nh1{margin-top:0}\n</style></head>\n<body>\n<h1>Hello Kiosk</h1>\n<p>这是示例本地页面。编辑后保存即可引用。</p>\n</body></html>";
});

// ---------- 配置导入 / 导出 ----------
document.getElementById("btn-config-export").addEventListener("click", function () {
  window.location.href = "api/config/export";
});
document.getElementById("btn-config-import").addEventListener("click", function () {
  document.getElementById("config-import-file").click();
});
document.getElementById("config-import-file").addEventListener("change", function (e) {
  var f = e.target.files && e.target.files[0];
  if (!f) return;
  if (!confirm("确认用 " + f.name + " 替换当前配置？\n（已上传的文件不会被覆盖；仅页面 + 设置被替换）")) {
    e.target.value = "";
    return;
  }
  var reader = new FileReader();
  reader.onload = function () {
    api("POST", "api/config/import", { config: reader.result })
      .then(function (j) {
        toast("已导入 " + (j.msg || ""));
        bindConfig();      // 重新拉配置
      })
      .catch(function (err) { toast(err.message || "导入失败", true); });
  };
  reader.readAsText(f, "utf-8");
  e.target.value = "";
});

// ---------- 上传（图片/视频/HTML） ----------
document.getElementById("btn-local-upload").addEventListener("click", function () {
  var fi = document.getElementById("local-file");
  var overrideName = document.getElementById("local-upload-name").value.trim();
  var state = document.getElementById("upload-state");
  if (!fi.files || !fi.files.length) {
    return toast("请先选择文件", true);
  }
  uploadFile(fi.files[0], overrideName, state).then(function (ok) {
    if (ok) {
      fi.value = "";
      document.getElementById("local-upload-name").value = "";
      loadLocalFiles();
    }
  });
});

// ---------- 上传核心（按钮 + 拖拽共用） ----------
var _ALLOWED_RE = /\.(html?|svg|jpg|jpeg|png|gif|webp|bmp|ico|mp4|webm|ogg|mov)$/i;
var _ALLOWED_KINDS = { html: "html_file", image: "media_file", video: "media_file" };

function classifyExt(name) {
  var m = /\.([a-z0-9]+)$/i.exec(name || "");
  var ext = (m && m[1].toLowerCase()) || "";
  if (["html", "htm", "svg"].indexOf(ext) >= 0) return { kind: "html", type: "html_file" };
  if (["jpg", "jpeg", "png", "gif", "webp", "bmp", "ico"].indexOf(ext) >= 0)
    return { kind: "image", type: "media_file" };
  if (["mp4", "webm", "ogg", "mov"].indexOf(ext) >= 0)
    return { kind: "video", type: "media_file" };
  return null;
}

function uploadFile(file, overrideName, stateEl) {
  var name = overrideName || file.name;
  if (!_ALLOWED_RE.test(name)) {
    toast("不支持的文件类型：" + name, true);
    return Promise.resolve(false);
  }
  if (file.size > 16 * 1024 * 1024) {
    toast("文件超过 16MB 上限：" + name, true);
    return Promise.resolve(false);
  }
  if (stateEl) stateEl.textContent = "读取中…";
  return new Promise(function (resolve) {
    var reader = new FileReader();
    reader.onload = function () {
      var b64 = String(reader.result).split(",", 2)[1];
      if (stateEl) stateEl.textContent = "上传中…";
      api("POST", "api/pages/save",
          { name: name, content: b64, encoding: "base64" })
        .then(function () {
          if (stateEl) stateEl.textContent = "✓ " + name + " (" +
            (file.size / 1024).toFixed(1) + " KB)";
          resolve({ ok: true, name: name, size: file.size });
        })
        .catch(function (e) {
          if (stateEl) stateEl.textContent = "✗ 上传失败";
          toast(e.message || "上传失败", true);
          resolve({ ok: false, name: name });
        });
    };
    reader.onerror = function () {
      if (stateEl) stateEl.textContent = "✗ 读取失败";
      toast("读取文件失败", true);
      resolve({ ok: false, name: name });
    };
    reader.readAsDataURL(file);
  });
}

// 上传后立即把页面注册到 cfg.pages 并保存 → 显示屏立即显示
function registerAndDisplay(result, mode) {
  if (!result.ok) return;
  var info = classifyExt(result.name);
  if (!info) return;
  var page = {
    id: "page" + Date.now().toString(36).slice(-4) + Math.floor(Math.random()*1000),
    name: result.name,
    type: info.type,
    path: result.name,
    mode: mode || "single",
    refresh_seconds: 0,
    zoom: 1.0,
    fit: "none",
    enabled: true,
  };
  // 移除同名旧页面（避免重复显示）
  cfg.pages = (cfg.pages || []).filter(function (p) { return p.name !== result.name && p.path !== result.name; });
  // single 模式：放在最前面；如果一次拖多个，只有最后一个保留 single，其它转 cycle
  if (page.mode === "single") {
    cfg.pages.unshift(page);
  } else {
    cfg.pages.push(page);
  }
  cfg.default_mode = page.mode === "single" ? "single" : (cfg.default_mode || "cycle");
}

// ---------- 拖拽上传（直接到显示屏） ----------
var _dropOverlay = null;
var _dropDepth = 0;

function _showDrop() {
  if (!_dropOverlay) _dropOverlay = document.getElementById("drop-overlay");
  if (_dropOverlay) _dropOverlay.classList.remove("hidden");
}
function _hideDrop() {
  if (!_dropOverlay) _dropOverlay = document.getElementById("drop-overlay");
  if (_dropOverlay) _dropOverlay.classList.add("hidden");
}

function _attachDragDrop() {
  // dragenter/dragleave 用 depth counter：子元素反复触发也能正确显示
  document.addEventListener("dragenter", function (e) {
    if (!e.dataTransfer || !Array.from(e.dataTransfer.types || []).includes("Files")) return;
    e.preventDefault();
    _dropDepth++;
    _showDrop();
  });
  document.addEventListener("dragover", function (e) {
    if (!e.dataTransfer || !Array.from(e.dataTransfer.types || []).includes("Files")) return;
    e.preventDefault();
    e.dataTransfer.dropEffect = "copy";
  });
  document.addEventListener("dragleave", function (e) {
    _dropDepth = Math.max(0, _dropDepth - 1);
    if (_dropDepth === 0) _hideDrop();
  });
  document.addEventListener("drop", function (e) {
    if (!e.dataTransfer) return;
    e.preventDefault();
    _dropDepth = 0;
    _hideDrop();
    var files = Array.from(e.dataTransfer.files || []);
    if (!files.length) return;
    handleDroppedFiles(files);
  });
}

function handleDroppedFiles(files) {
  // 按文件名排序，避免 single 模式下顺序错乱
  files.sort(function (a, b) { return a.name.localeCompare(b.name); });
  var valid = files.filter(function (f) { return _ALLOWED_RE.test(f.name); });
  var rejected = files.length - valid.length;
  if (rejected > 0) {
    toast(rejected + " 个文件类型不支持，已跳过", true);
  }
  if (!valid.length) return;

  toast("正在上传 " + valid.length + " 个文件…");
  // 串行上传，避免一次性 base64 大块请求
  var chain = Promise.resolve();
  var lastResult = null;
  valid.forEach(function (f, idx) {
    chain = chain.then(function () {
      // 最后一个文件（按文件名排序）设为 single；其他为 cycle
      var mode = (idx === valid.length - 1) ? "single" : "cycle";
      return uploadFile(f, "", null).then(function (r) {
        if (r && r.ok) {
          registerAndDisplay({ ok: true, name: r.name }, mode);
          lastResult = r;
        }
      });
    });
  });
  chain.then(function () {
    if (lastResult) {
      // 立即保存配置 + 触发渲染器拉取新页面
      return api("POST", "api/settings", cfg).then(function (j) {
        cfg = j.config;
        renderPageList();
        loadLocalFiles();
        loadFbInfo();
        toast("✓ 已上传并显示：" + lastResult.name);
      }).catch(function (e) { toast(e.message || "保存失败", true); });
    }
  });
}

_attachDragDrop();

// ---------- 保存 ----------
function bindConfig() {
  document.getElementById("set-fb").addEventListener("change", function (e) { cfg.fb_enabled = e.target.checked; });
  document.getElementById("set-theme").addEventListener("change", function (e) { cfg.theme = e.target.value; });
  document.getElementById("set-accent").addEventListener("input", function (e) { cfg.accent = e.target.value.trim(); });
  document.getElementById("set-rotate").addEventListener("change", function (e) { cfg.rotate_seconds = parseInt(e.target.value, 10); });
  document.getElementById("set-inches").addEventListener("change", function (e) { cfg.screen_inches = parseFloat(e.target.value); });
  document.getElementById("set-browser-path").addEventListener("input", function (e) { cfg.browser_path = e.target.value.trim(); });
  document.getElementById("set-win-w").addEventListener("input", function (e) { cfg.browser_window = cfg.browser_window || [1920, 1080]; cfg.browser_window[0] = parseInt(e.target.value, 10) || 1920; });
  document.getElementById("set-win-h").addEventListener("input", function (e) { cfg.browser_window = cfg.browser_window || [1920, 1080]; cfg.browser_window[1] = parseInt(e.target.value, 10) || 1080; });
  document.getElementById("set-browser-scale").addEventListener("change", function (e) { cfg.browser_scale = parseFloat(e.target.value); });
  document.getElementById("set-browser-timeout").addEventListener("input", function (e) { cfg.browser_timeout = parseInt(e.target.value, 10) || 30; });
  document.getElementById("set-hide-cursor").addEventListener("change", function (e) { cfg.hide_cursor = e.target.checked; });
  document.getElementById("set-allow-private").addEventListener("change", function (e) { cfg.allow_private_hosts = e.target.checked; });
  // v0.1.34: URL 全屏 CSS 注入设置
  document.getElementById("set-url-kiosk-css").addEventListener("input", function (e) { cfg.url_kiosk_css = e.target.value; });
  document.getElementById("set-btn-reset-css").addEventListener("click", function () {
    var ta = document.getElementById("set-url-kiosk-css");
    ta.value = DEFAULT_URL_KIOSK_CSS;
    cfg.url_kiosk_css = DEFAULT_URL_KIOSK_CSS;
  });
}

// v0.1.34 默认注入 CSS —— 与 dash_config.DEFAULT_URL_KIOSK_CSS 保持一致。
// 这里再写一份是因为 settings.js 是静态前端，不能 import Python。
// 真值以 dash_config 为准；这里只是 UI 默认值，提交保存后服务端会原样落盘。
var DEFAULT_URL_KIOSK_CSS = "html,body{margin:0!important;padding:0!important;width:100%!important;height:100%!important;background:#000!important;overflow:hidden!important}body>*{max-width:100vw!important;max-height:100vh!important;box-sizing:border-box!important}";

function fillFromCfg() {
  document.getElementById("set-fb").checked = !!cfg.fb_enabled;
  document.getElementById("set-theme").value = cfg.theme || "midnight";
  document.getElementById("set-accent").value = cfg.accent || "";
  document.getElementById("set-rotate").value = cfg.rotate_seconds || 30;
  document.getElementById("set-inches").value = cfg.screen_inches || 0;
  // v0.1.34: URL 全屏 CSS 回填。空 = 留空（用户主动关掉了注入）。
  document.getElementById("set-url-kiosk-css").value = (cfg.url_kiosk_css != null) ? cfg.url_kiosk_css : DEFAULT_URL_KIOSK_CSS;
  document.getElementById("set-btn-default-css").textContent = DEFAULT_URL_KIOSK_CSS;
  // seg
  document.querySelectorAll("#seg-rotate button").forEach(function (b) {
    b.classList.toggle("active", parseInt(b.dataset.v, 10) === (cfg.fb_rotate || 0));
  });
  document.querySelectorAll("#seg-fit button").forEach(function (b) {
    b.classList.toggle("active", b.dataset.v === (cfg.display_fit || "stretch"));
  });
  // 把当前 zoom + browser_window + fb 实际尺寸 → 推算 Chromium 实际窗口大小
  // 显示在 zoom 段的 hint 里，让用户能立刻看到「缩放有没有真的生效」
  api("GET", "api/fb/zoom-debug").then(function (j) {
    var fbEl = document.getElementById("fb-fb-size");
    var effEl = document.getElementById("fb-effective-win");
    if (j && fbEl) fbEl.textContent = (j.fb_physical[0] || 0) + " × " + (j.fb_physical[1] || 0);
    if (j && effEl) effEl.textContent =
      (j.effective_chromium_window[0] || 0) + " × " +
      (j.effective_chromium_window[1] || 0) +
      " (zoom " + (j.display_zoom_config || 1) + "×)";
  }).catch(function () {});
  document.querySelectorAll("#seg-zoom button").forEach(function (b) {
    var v = parseFloat(b.dataset.v);
    var cur = parseFloat(cfg.display_zoom || 1);
    b.classList.toggle("active", Math.abs(v - cur) < 0.01);
  });
  document.querySelectorAll("#seg-mode button").forEach(function (b) {
    b.classList.toggle("active", b.dataset.v === (cfg.default_mode || "cycle"));
  });
  // browser
  document.getElementById("set-browser-path").value = cfg.browser_path || "";
  // browser_window 支持 "match_fb" 字符串 或 [w, h]
  var win = cfg.browser_window;
  var fbDimEl = document.getElementById("fb-dim-show");
  // 从 /api/fb/info 拿 fb 尺寸
  api("GET", "api/fb/info").then(function (j) {
    if (fbDimEl && j && j.fb) {
      fbDimEl.textContent = (j.fb.w || 0) + " × " + (j.fb.h || 0);
    }
  }).catch(function () {});
  // 判断当前 browser_window 对应哪个预设
  var preset = "custom";
  if (typeof win === "string") {
    preset = win.toLowerCase();
  } else if (Array.isArray(win)) {
    preset = win[0] + "," + win[1];
  }
  document.querySelectorAll("#seg-win-preset button").forEach(function (b) {
    b.classList.toggle("active", b.dataset.v === preset);
  });
  if (Array.isArray(win)) {
    document.getElementById("set-win-w").value = win[0];
    document.getElementById("set-win-h").value = win[1];
  } else {
    // match_fb 时显示 fb 尺寸作为预览
    api("GET", "api/fb/info").then(function (j) {
      if (j && j.fb) {
        document.getElementById("set-win-w").value = j.fb.w || "";
        document.getElementById("set-win-h").value = j.fb.h || "";
      }
    }).catch(function () {});
  }
  document.getElementById("set-browser-scale").value = cfg.browser_scale || 1;
  document.getElementById("set-browser-timeout").value = cfg.browser_timeout || 30;
  document.getElementById("set-hide-cursor").checked = cfg.hide_cursor !== false;
  document.getElementById("set-allow-private").checked = !!cfg.allow_private_hosts;
}

document.getElementById("btn-save").addEventListener("click", function () {
  var btn = this;
  btn.disabled = true;
  btn.textContent = "保存中…";
  document.getElementById("save-state").textContent = "";
  api("POST", "api/settings", cfg)
    .then(function (j) {
      cfg = j.config;
      fillFromCfg();
      renderPageList();
      toast("已保存并同步到显示屏");
      loadFbInfo();
    })
    .catch(function (e) { toast(e.message || "保存失败", true); })
    .then(function () {
      btn.disabled = false;
      btn.textContent = "保存并同步到显示屏";
    });
});

// ---------- 预览 ----------
function refreshPreview() {
  var img = document.getElementById("fb-preview");
  var hide = document.getElementById("preview-placeholder");
  if (!img) return;
  img.src = "api/fb/dump.png?t=" + Date.now();
  img.onerror = function () { if (hide) hide.classList.remove("hidden"); };
  img.onload = function () { if (hide) hide.classList.add("hidden"); };
}
document.getElementById("preview-refresh").addEventListener("click", refreshPreview);

// ---------- 加载 ----------
function loadLocalFiles() {
  return api("GET", "api/pages").then(function (j) {
    localFiles = j.pages || [];
    renderLocalList();
  });
}
function loadRecentUrls() {
  return api("GET", "api/recent-urls").then(function (j) {
    var dl = document.getElementById("recent-urls");
    if (!dl) return;
    dl.textContent = "";
    (j.urls || []).slice(0, 20).forEach(function (u) {
      var op = document.createElement("option");
      op.value = u;
      dl.appendChild(op);
    });
  }).catch(function () {});
}
function loadFbInfo() {
  return api("GET", "api/fb/info").then(function (j) {
    renderFbInfo(j.fb);
    renderAuthInfo(j.fb);
  });
}
function loadAll() {
  return api("GET", "api/status").then(function (j) {
    cfg = j.config;
    fillFromCfg();
    renderPageList();
  }).then(loadLocalFiles).then(loadFbInfo).then(loadRecentUrls);
}

bindConfig();
loadAll().catch(function (e) {
  toast(e.message || "加载失败", true);
});
setInterval(refreshPreview, 3000);