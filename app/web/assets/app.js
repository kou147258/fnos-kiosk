/* fnOS 浏览器屏 —— 面板（只读） */
"use strict";

var cfg = null;
var fbInfo = null;
var pages = [];
var localFiles = [];

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

function showOffline() { var el = document.getElementById("offline"); if (el) el.classList.remove("hidden"); }
function hideOffline() { var el = document.getElementById("offline"); if (el) el.classList.add("hidden"); }

function tickClock() {
  var el = document.getElementById("clock");
  if (el) el.textContent = new Date().toLocaleTimeString("zh-CN", { hour12: false });
}

function applyTheme() {
  if (!cfg) return;
  document.body.dataset.theme = cfg.theme || "midnight";
  if (cfg.accent) document.body.style.setProperty("--accent", cfg.accent);
  else document.body.style.removeProperty("--accent");
}

function renderFbGrid() {
  var grid = document.getElementById("fb-grid");
  if (!grid || !fbInfo) return;
  var state = document.getElementById("fb-state");
  if (fbInfo.exists) {
    state.textContent = (fbInfo.renderer_running ? "运行中" : "未运行");
    state.style.color = fbInfo.renderer_running ? "var(--ok)" : "var(--dim)";
  } else {
    state.textContent = "未检测到 /dev/fb0";
    state.style.color = "var(--dim)";
  }
  var rows = [];
  if (fbInfo.exists) {
    rows.push(["分辨率", fbInfo.w + " × " + fbInfo.h + " @ " + fbInfo.bpp + "bpp"]);
    rows.push(["PIL 中文渲染", fbInfo.pil ? "已安装" : "未安装"]);
    rows.push(["渲染进程", fbInfo.renderer_running
      ? "✓ 运行中（PID " + (fbInfo.renderer_pid || "?") + "）"
      : "✗ 未运行"]);
  } else {
    rows.push(["状态", "本环境无 fb0（可能是 SSH 远程窗口）"]);
  }
  rows.push(["HTTP API 端口", fbInfo.http_port || "—"]);
  rows.push(["Chromium CDP 端口", fbInfo.cdp_port || "—"]);
  rows.push(["轮换间隔", cfg && cfg.rotate_seconds ? cfg.rotate_seconds + " 秒" : "—"]);
  rows.push(["显示方向", cfg && cfg.fb_rotate != null ? cfg.fb_rotate + "°" : "0°"]);
  rows.push(["默认模式", cfg && cfg.default_mode === "single" ? "单 URL 全屏" : "URL 列表轮换"]);
  grid.textContent = "";
  rows.forEach(function (r) {
    var k = document.createElement("span"); k.className = "k"; k.textContent = r[0];
    var v = document.createElement("span"); v.className = "v"; v.textContent = r[1];
    grid.appendChild(k); grid.appendChild(v);
  });
}

function renderPages() {
  var list = document.getElementById("pages-list");
  var cnt = document.getElementById("pages-count");
  var meta = document.getElementById("meta-pages");
  if (!list) return;
  list.textContent = "";
  var enabled = pages.filter(function (p) { return p.enabled !== false; });
  if (cnt) cnt.textContent = pages.length + " 个";
  if (meta) meta.textContent = enabled.length + " / " + pages.length + " 个启用";
  pages.forEach(function (p) {
    var row = document.createElement("div");
    row.className = "page-item" + (p.enabled === false ? " disabled" : "");
    var dot = document.createElement("span");
    dot.className = "dot" + (p.mode === "single" ? " single" : "") +
      (p.enabled === false ? " disabled" : "");
    var name = document.createElement("span");
    name.className = "name"; name.textContent = p.name || p.id;
    var url = document.createElement("span");
    url.className = "url";
    if (p.type === "html_file") {
      url.textContent = "file: var/pages/" + p.path;
    } else {
      url.textContent = p.url;
    }
    var tag = document.createElement("span");
    tag.className = "tag";
    tag.textContent = p.mode === "single" ? "SINGLE" :
      (p.refresh_seconds > 0 ? (p.refresh_seconds + "s 刷新") : "cycle");
    row.appendChild(dot);
    row.appendChild(name);
    row.appendChild(url);
    row.appendChild(tag);
    list.appendChild(row);
  });
}

function renderLocal() {
  var list = document.getElementById("local-list");
  var cnt = document.getElementById("local-count");
  if (!list) return;
  list.textContent = "";
  if (cnt) cnt.textContent = localFiles.length + " 个";
  if (!localFiles.length) {
    var empty = document.createElement("div");
    empty.style.color = "var(--dim)";
    empty.style.fontSize = "13px";
    empty.style.padding = "8px";
    empty.textContent = "暂无本地 HTML 文件（在「设置 → 高级」里创建）";
    list.appendChild(empty);
    return;
  }
  localFiles.forEach(function (f) {
    var row = document.createElement("div");
    row.className = "page-item";
    var dot = document.createElement("span"); dot.className = "dot";
    var name = document.createElement("span");
    name.className = "name"; name.textContent = f.name;
    var detail = document.createElement("span");
    detail.className = "url";
    detail.textContent = (f.size / 1024).toFixed(1) + " KB · " +
      new Date(f.mtime * 1000).toLocaleString("zh-CN");
    row.appendChild(dot); row.appendChild(name); row.appendChild(detail);
    list.appendChild(row);
  });
}

function renderMode() {
  var el = document.getElementById("meta-mode");
  if (!el) return;
  el.textContent = cfg && cfg.default_mode === "single" ? "单 URL 全屏" : "URL 列表轮换";
}

function pollStatus() {
  api("GET", "api/status").then(function (data) {
    cfg = data.config || {};
    pages = data.pages || [];
    applyTheme();
    renderMode();
    renderPages();
    renderFbGrid();
    hideOffline();
  }).catch(function () { showOffline(); });
}

function pollFb() {
  Promise.all([api("GET", "api/fb/info"), api("GET", "api/pages")])
    .then(function (a) {
      fbInfo = (a[0].fb) || null;
      localFiles = a[1].pages || [];
      renderFbGrid();
      renderLocal();
    }).catch(function () {});
}

function refreshPreview() {
  var img = document.getElementById("fb-preview");
  var hide = document.getElementById("preview-placeholder");
  if (!img) return;
  img.src = "api/fb/dump.png?t=" + Date.now();
  img.onerror = function () {
    if (hide) hide.classList.remove("hidden");
  };
  img.onload = function () {
    if (hide) hide.classList.add("hidden");
  };
}

function boot() {
  tickClock();
  setInterval(tickClock, 1000);
  pollStatus();
  setInterval(pollStatus, 5000);
  pollFb();
  refreshPreview();
  var auto = document.getElementById("auto-refresh");
  if (auto && auto.checked) setInterval(refreshPreview, 3000);
  auto && auto.addEventListener("change", function () {
    if (auto.checked) setInterval(refreshPreview, 3000);
  });
}
boot();