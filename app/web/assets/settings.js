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
    enabled: true,
  };
}

function renderPageList() {
  var list = document.getElementById("page-list");
  list.textContent = "";
  cfg.pages.forEach(function (p, idx) {
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

    // 类型
    var row2 = document.createElement("div");
    row2.className = "row";
    var lab2 = document.createElement("span"); lab2.className = "label-mini"; lab2.textContent = "类型";
    var sel = document.createElement("select");
    [["url", "远程 URL"], ["html_file", "本地 HTML"], ["media_file", "媒体文件（图片/视频）"]].forEach(function (o) {
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

    // URL / path（按 type 切换）
    var rowUrl = document.createElement("div");
    rowUrl.className = "row full";
    if (p.type === "url") {
      var labU = document.createElement("span"); labU.className = "label-mini"; labU.textContent = "URL";
      var inU = document.createElement("input"); inU.type = "text"; inU.placeholder = "https://...";
      inU.value = p.url || "";
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
    var labZ = document.createElement("span"); labZ.className = "label-mini"; labZ.textContent = "缩放";
    var inZ = document.createElement("input"); inZ.type = "number"; inZ.min = 0.3; inZ.max = 3; inZ.step = 0.1;
    inZ.value = p.zoom || 1.0;
    inZ.addEventListener("input", function () {
      p.zoom = parseFloat(inZ.value) || 1.0;
    });
    row5.appendChild(labZ); row5.appendChild(inZ);
    div.appendChild(row5);

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
    row.appendChild(dot);
    row.appendChild(icon);
    row.appendChild(name);
    row.appendChild(detail);
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

// ---------- 远程控制（CDP 转发）----------
var _remoteImg = null;
var _remotePlaceholder = null;
var _remoteUrlInput = null;
var _remoteInput = null;
var _remoteAutoTimer = null;

function _remoteNaturalDims() {
  if (!_remoteImg) _remoteImg = document.getElementById("remote-img");
  if (!_remoteImg) return { w: 1920, h: 1080, sx: 1, sy: 1 };
  var natW = _remoteImg.naturalWidth || 1920;
  var natH = _remoteImg.naturalHeight || 1080;
  var rect = _remoteImg.getBoundingClientRect();
  return {
    w: natW, h: natH,
    dispW: rect.width, dispH: rect.height,
    sx: natW / Math.max(1, rect.width),
    sy: natH / Math.max(1, rect.height),
  };
}

function _refreshRemote() {
  if (!_remoteImg) _remoteImg = document.getElementById("remote-img");
  if (!_remotePlaceholder) _remotePlaceholder = document.getElementById("remote-placeholder");
  if (!_remoteImg) return;
  var url = "api/fb/live.png?t=" + Date.now();
  var probe = new Image();
  probe.onload = function () {
    _remoteImg.src = url;
    if (_remotePlaceholder) _remotePlaceholder.classList.add("hidden");
  };
  probe.onerror = function () {
    // 503 表示 Chromium 还没连上
    if (_remotePlaceholder) {
      _remotePlaceholder.classList.remove("hidden");
      _remotePlaceholder.querySelector(".ph-text").innerHTML =
        "⚠ Chromium 暂不可用<br>请检查「显示」tab 是否显示「渲染进程：运行中」";
    }
  };
  probe.src = url;
  // 顺便拉 URL 信息
  fetch("api/fb/live.json").then(function (r) { return r.json(); })
    .then(function (j) {
      if (j.ok && _remoteUrlInput) {
        _remoteUrlInput.value = j.url || "";
      }
    }).catch(function () {});
}

function _setupRemote() {
  _remoteImg = document.getElementById("remote-img");
  _remotePlaceholder = document.getElementById("remote-placeholder");
  _remoteUrlInput = document.getElementById("remote-url");
  _remoteInput = document.getElementById("remote-input");
  if (!_remoteImg) return;

  // 截图点击 → 转发 mouse click 事件到 Chromium
  _remoteImg.addEventListener("click", function (e) {
    var d = _remoteNaturalDims();
    var rect = _remoteImg.getBoundingClientRect();
    var x = (e.clientX - rect.left) * d.sx;
    var y = (e.clientY - rect.top) * d.sy;
    api("POST", "api/fb/click", { x: x, y: y })
      .then(function () { toast("已点击 (" + Math.round(x) + ", " + Math.round(y) + ")"); })
      .catch(function (err) { toast("点击失败：" + (err.message || err), true); });
  });
  // 滚轮
  _remoteImg.addEventListener("wheel", function (e) {
    e.preventDefault();
    var d = _remoteNaturalDims();
    var rect = _remoteImg.getBoundingClientRect();
    var x = (e.clientX - rect.left) * d.sx;
    var y = (e.clientY - rect.top) * d.sy;
    api("POST", "api/fb/scroll", {
      x: x, y: y,
      deltaX: e.deltaX, deltaY: e.deltaY
    }).catch(function (err) { toast(err.message || err, true); });
  });

  // URL 跳转
  document.getElementById("btn-remote-go").addEventListener("click", function () {
    var url = (_remoteUrlInput.value || "").trim();
    if (!url) return toast("请填 URL", true);
    if (!/^https?:\/\//i.test(url)) url = "http://" + url;
    api("POST", "api/fb/go", { url: url })
      .then(function () { toast("已导航到 " + url); _refreshRemote(); })
      .catch(function (e) { toast(e.message || "导航失败", true); });
  });

  // 文本输入
  document.getElementById("btn-remote-input").addEventListener("click", function () {
    var text = _remoteInput.value;
    if (!text) return toast("请先填写文字", true);
    api("POST", "api/fb/type", { text: text })
      .then(function () { _remoteInput.value = ""; toast("已输入 " + text.length + " 字符"); })
      .catch(function (e) { toast(e.message || "输入失败", true); });
  });
  document.getElementById("btn-remote-submit").addEventListener("click", function () {
    var text = _remoteInput.value;
    if (!text) return toast("请先填写文字", true);
    api("POST", "api/fb/type", { text: text })
      .then(function () {
        _remoteInput.value = "";
        return api("POST", "api/fb/key", { key: "Enter" });
      })
      .then(function () { toast("已输入 + 回车"); })
      .catch(function (e) { toast(e.message || "失败", true); });
  });

  // 特殊键
  document.querySelectorAll(".key-btn").forEach(function (btn) {
    btn.addEventListener("click", function () {
      var key = btn.dataset.key;
      api("POST", "api/fb/key", { key: key })
        .then(function () { /* toast("已按 " + key); */ })
        .catch(function (e) { toast(e.message || "按键失败", true); });
    });
  });

  // 手动刷新 + 自动刷新
  document.getElementById("btn-remote-refresh").addEventListener("click", _refreshRemote);
  var autoCb = document.getElementById("remote-auto");
  function _setupTimer() {
    if (_remoteAutoTimer) clearInterval(_remoteAutoTimer);
    _remoteAutoTimer = null;
    if (autoCb && autoCb.checked) {
      _remoteAutoTimer = setInterval(_refreshRemote, 1000);
    }
  }
  if (autoCb) autoCb.addEventListener("change", _setupTimer);
  _setupTimer();

  // 初次拉
  _refreshRemote();
}

_setupRemote();

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
}

function fillFromCfg() {
  document.getElementById("set-fb").checked = !!cfg.fb_enabled;
  document.getElementById("set-theme").value = cfg.theme || "midnight";
  document.getElementById("set-accent").value = cfg.accent || "";
  document.getElementById("set-rotate").value = cfg.rotate_seconds || 30;
  document.getElementById("set-inches").value = cfg.screen_inches || 0;
  // seg
  document.querySelectorAll("#seg-rotate button").forEach(function (b) {
    b.classList.toggle("active", parseInt(b.dataset.v, 10) === (cfg.fb_rotate || 0));
  });
  document.querySelectorAll("#seg-fit button").forEach(function (b) {
    b.classList.toggle("active", b.dataset.v === (cfg.display_fit || "contain"));
  });
  document.querySelectorAll("#seg-mode button").forEach(function (b) {
    b.classList.toggle("active", b.dataset.v === (cfg.default_mode || "cycle"));
  });
  // browser
  document.getElementById("set-browser-path").value = cfg.browser_path || "";
  var win = cfg.browser_window || [1920, 1080];
  document.getElementById("set-win-w").value = win[0];
  document.getElementById("set-win-h").value = win[1];
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
  }).then(loadLocalFiles).then(loadFbInfo);
}

bindConfig();
loadAll().catch(function (e) {
  toast(e.message || "加载失败", true);
});
setInterval(refreshPreview, 3000);