/* HaloEchoLyric 前端逻辑 */

const $ = (id) => document.getElementById(id);

let S = null;              // 最近一次完整状态
let lyricOffset = 0;       // 歌词延迟（毫秒）
let localMode = "scroll";  // 静态 / 滚动

function api() {
  // pywebview 会先注入一个空的 api 对象再挂方法，必须检查具体方法是否存在
  const w = window.pywebview;
  if (w && w.api && typeof w.api.get_state === "function") return w.api;
  return null;
}

function toast(msg, kind) {
  const el = $("toast");
  el.textContent = msg;
  el.className = "toast show" + (kind ? " " + kind : "");
  clearTimeout(toast._t);
  toast._t = setTimeout(() => { el.className = "toast"; }, 2600);
}

async function call(name, ...args) {
  const a = api();
  if (!a || typeof a[name] !== "function") {
    toast("界面与后端尚未连接完成", "err");
    return null;
  }
  try {
    return await a[name](...args);
  } catch (e) {
    toast("调用失败：" + (e && e.message ? e.message : e), "err");
    return null;
  }
}

/* ---------------- 导航 ---------------- */
function activatePage(name) {
  const btn = document.querySelector('.nav-item[data-page="' + name + '"]');
  if (!btn) return;
  document.querySelectorAll(".nav-item").forEach((b) => b.classList.remove("active"));
  document.querySelectorAll(".page").forEach((p) => p.classList.remove("active"));
  btn.classList.add("active");
  const page = $("page-" + name);
  if (page) page.classList.add("active");
  if (name === "logs") renderLogs();
}

function initNav() {
  document.querySelectorAll(".nav-item").forEach((btn) => {
    btn.addEventListener("click", () => activatePage(btn.dataset.page));
  });
  const hash = (location.hash || "").replace(/^#/, "");
  if (hash) activatePage(hash);
}

/* ---------------- 窗口按钮 ---------------- */
function initWindow() {
  $("winMin").addEventListener("click", () => call("minimize"));
  $("winMax").addEventListener("click", () => call("toggle_maximize"));
  $("winClose").addEventListener("click", () => call("request_close"));
}

/* ---------------- 分段控件 ---------------- */
function setSeg(key, val) {
  document.querySelectorAll('.seg[data-key="' + key + '"] button').forEach((b) => {
    b.classList.toggle("on", b.dataset.val === val);
  });
}

function initSegs() {
  document.querySelectorAll(".seg").forEach((seg) => {
    seg.querySelectorAll("button").forEach((btn) => {
      if (btn.disabled) return;
      btn.addEventListener("click", () => {
        const key = seg.dataset.key;
        setSeg(key, btn.dataset.val);
        if (key === "mode") {
          localMode = btn.dataset.val;
          pushDisplay();
        } else if (key === "align") {
          pushDisplay({ layout: btn.dataset.val });
        } else if (key === "scroll") {
          pushDisplay({ scroll_direction: btn.dataset.val });
        } else if (key === "brightness") {
          // 亮度只在点「应用灯效」时下发
        } else if (key === "close") {
          pushConfig({ ui: { close_action: btn.dataset.val } });
        }
      });
    });
  });
}

/* ---------------- 配置下发 ---------------- */
async function pushConfig(patch) {
  const r = await call("set_config", patch);
  if (r && r.ok) applyConfig(r.config);
  return r;
}

async function pushDisplay(patch) {
  const d = { enabled: true };
  if (localMode === "static") {
    d.scroll_always = false;
    d.long_line_mode = "paging";
    d.layout = currentAlign();
  } else {
    d.scroll_always = true;
    d.long_line_mode = "scroll";
  }
  Object.assign(d, patch || {});
  await pushConfig({ display: d });
}

function currentAlign() {
  const on = document.querySelector('.seg[data-key="align"] button.on');
  return on ? on.dataset.val : "center";
}

function applyConfig(cfg) {
  if (!cfg) return;
  const d = cfg.display || {};
  const u = cfg.ui || {};
  localMode = d.scroll_always ? "scroll" : "static";
  setSeg("mode", localMode);
  setSeg("align", d.layout || "center");
  setSeg("scroll", d.scroll_direction || "right_to_left");
  setSeg("close", u.close_action || "tray");
  setSeg("brightness", (cfg.light || {}).brightness || "high");

  $("dvEnable").checked = d.enabled !== false;
  $("stAutoConnect").checked = !!(cfg.device || {}).auto_connect;
  $("stAutostart").checked = !!u.autostart;

  if ($("scCols") !== document.activeElement) $("scCols").value = d.max_columns || 20;
  if ($("scLyricColor")) $("scLyricColor").value = rgbToHex(d.color || [255, 255, 255]);
  if ($("scSongInfo") !== document.activeElement) $("scSongInfo").value = d.song_info_seconds ?? 3;
  if ($("scIdle") !== document.activeElement) $("scIdle").value = d.idle_to_ui_seconds ?? 30;

  const l = cfg.light || {};
  if ($("ltColor")) $("ltColor").value = rgbToHex(l.color || [255, 255, 255]);
  if ($("ltSpeed") && $("ltSpeed") !== document.activeElement) {
    $("ltSpeed").value = l.speed || 10;
    $("ltSpeedVal").textContent = l.speed || 10;
  }
  renderLightEffects((l.effect) || "dynamic");
}

function rgbToHex(rgb) {
  return "#" + rgb.slice(0, 3).map((v) => ("0" + (v | 0).toString(16)).slice(-2)).join("").toUpperCase();
}

/* ---------------- 渲染 ---------------- */
function fmtTime(sec) {
  sec = Math.max(0, Math.floor(sec || 0));
  const m = Math.floor(sec / 60), s = sec % 60;
  return (m < 10 ? "0" : "") + m + ":" + (s < 10 ? "0" : "") + s;
}

function renderDevice(dv) {
  const online = dv.state === "online";
  const waiting = dv.state === "connecting";
  $("sideDot").className = "dot " + (online ? "on" : waiting ? "wait" : "off");
  $("sideStatus").textContent = dv.label;
  $("dvDot").className = "dot " + (online ? "on" : waiting ? "wait" : "off");
  $("dvLabel").textContent = dv.label;

  const info = dv.info || {};
  const serial = info.serial || "";
  $("dvModel").textContent = (info.product || "花再 Halo PixelBar") +
    (serial ? " · " + serial.slice(-6).toUpperCase() : "");
  $("dvVid").textContent = "VID " + (info.vid || "0x2D99") + " · PID " + (info.pid || "0xA106");
  $("dvDesc").textContent = online
    ? (info.describe || "已连接")
    : (dv.error || "未检测到设备，请用 USB 连接并开机");
  $("dvDesc").style.color = online ? "" : "var(--warn)";
  $("dvDisconnect").textContent = online ? "断开设备" : "连接设备";

  const stopped = !S || !S.lyric.enabled;
  $("ovEq").className = "eq" + (stopped || !(S.lyric.isPlaying) ? " paused" : "");
  $("dvEnable").checked = S ? S.lyric.enabled : true;
}

function renderLyric(l) {
  const has = !!(l.title);
  $("ovTitle").textContent = has ? l.title : "等待播放器…";
  $("ovArtist").textContent = has ? (l.artist || "未知歌手") : "EchoMusic（酷狗概念版）";

  let state = "等待播放器 · 同步未就绪";
  let cls = "";
  if (!l.enabled) {
    state = "同步已暂停";
  } else if (!l.source_online) {
    state = "EchoMusic 未连接 · 请在插件管理中启用「Halo PixelBar 歌词桥」";
  } else if (!has) {
    state = "已连接，等待播放";
  } else if (l.isPlaying) {
    state = "实时同步中 · 第 " + (l.lineIndex + 1) + " / " + l.lineCount + " 行";
    cls = "ok";
  } else {
    state = "已暂停";
  }
  $("ovState").textContent = state;
  $("ovState").className = "np-state " + cls;
  $("ovSync").textContent = l.source_online ? "实时同步" : "未连接";

  const pct = l.duration > 0 ? Math.min(100, (l.currentTime / l.duration) * 100) : 0;
  $("ovBar").style.width = pct.toFixed(1) + "%";
  $("ovCur").textContent = fmtTime(l.currentTime);
  $("ovDur").textContent = fmtTime(l.duration);

  const pv = $("ovPreview");
  const text = l.lineText || "";
  if (text && l.lineIndex >= 0) {
    pv.textContent = text;
    pv.classList.add("live");
  } else {
    pv.textContent = text || "暂无同步歌词";
    pv.classList.remove("live");
  }

  $("lsUrl").textContent = S ? "http://" + S.config.source.host + ":" + S.config.source.port + "/state" : "";
  $("lsNote").textContent = l.source_online
    ? "EchoMusic 插件已连接 · 本机回环"
    : ("未连接：" + (l.source_error || "请确认插件已启用"));

  const btn = $("lsInstall");
  btn.textContent = (S && S.plugin.installed) ? "重装 / 更新 EchoMusic 插件" : "安装 EchoMusic 插件";
}

function renderTimeline(l) {
  const box = $("tlList");
  const lines = l.lines || [];
  if (!lines.length) {
    if (box.dataset.key !== "empty") {
      box.innerHTML = '<div class="tl-line empty">暂无歌词数据</div>';
      box.dataset.key = "empty";
    }
    return;
  }
  const key = (l.trackKey || "") + "|" + lines.length;
  if (box.dataset.key !== key) {
    box.dataset.key = key;
    box.dataset.cur = "";
    box.innerHTML = lines.map((ln, i) =>
      '<div class="tl-line" data-i="' + i + '">' +
      '<span class="t">' + fmtTime(ln.s || 0) + "</span>" +
      '<span class="x">' + escapeHtml(ln.t || "") + "</span></div>"
    ).join("");
  }
  const cur = l.lineIndex;
  const prev = box.querySelector(".tl-line.on");
  if (prev) prev.classList.remove("on");
  const el = box.querySelector('.tl-line[data-i="' + cur + '"]');
  if (!el) return;
  el.classList.add("on");
  // 只在当前行变化时滚动，避免和用户手动滚动打架
  if (box.dataset.cur !== String(cur)) {
    box.dataset.cur = String(cur);
    const top = el.offsetTop - box.clientHeight / 2 + el.offsetHeight / 2;
    box.scrollTop = Math.max(0, top);
  }
}

function escapeHtml(s) {
  return String(s).replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
}

function renderViz() {
  const box = $("dvViz");
  if (box.childElementCount === 0) {
    for (let i = 0; i < 32; i++) box.appendChild(document.createElement("i"));
  }
}

function animateViz() {
  const box = $("dvViz");
  const playing = S && S.lyric.enabled && S.lyric.isPlaying;
  const t = Date.now() / 260;
  box.querySelectorAll("i").forEach((bar, i) => {
    let h;
    if (playing) {
      h = 6 + Math.abs(Math.sin(t + i * 0.42)) * 56 + Math.sin(t * 2.7 + i) * 6;
    } else {
      h = 4 + (i % 4) * 2;
    }
    bar.style.height = Math.max(3, Math.min(64, h)) + "px";
  });
}

function renderScenes() {
  const box = $("scScenes");
  if (!S) return;
  if (box.dataset.init) return;
  const modes = S.options.uiModes;
  box.innerHTML = Object.keys(modes)
    .map((k) => '<button data-val="' + k + '">' + modes[k] + "</button>").join("");
  box.querySelectorAll("button").forEach((b) => {
    b.addEventListener("click", async () => {
      const r = await call("set_ui_mode", b.dataset.val);
      if (r && r.ok) {
        box.querySelectorAll("button").forEach((x) => x.classList.remove("on"));
        b.classList.add("on");
        toast("已切换到「" + b.textContent + "」", "ok");
      } else {
        toast((r && r.error) || "切换失败", "err");
      }
    });
  });
  box.dataset.init = "1";
}

function renderLightEffects(current) {
  const box = $("ltEffects");
  if (!S) return;
  const effects = S.options.lightEffects;
  if (!box.dataset.init) {
    box.innerHTML = Object.keys(effects)
      .map((k) => '<button data-val="' + k + '">' + effects[k] + "</button>").join("");
    box.querySelectorAll("button").forEach((b) => {
      b.addEventListener("click", () => {
        box.querySelectorAll("button").forEach((x) => x.classList.remove("on"));
        b.classList.add("on");
        $("ltCur").textContent = "当前：" + b.textContent;
      });
    });
    box.dataset.init = "1";
  }
  box.querySelectorAll("button").forEach((b) => b.classList.toggle("on", b.dataset.val === current));
  const label = effects[current];
  if (label) $("ltCur").textContent = "当前：" + label;
}

function renderLogs() {
  if (!S) return;
  const box = $("lgBox");
  const atBottom = box.scrollTop + box.clientHeight >= box.scrollHeight - 24;
  box.textContent = (S.logs || []).join("\n");
  if (atBottom) box.scrollTop = box.scrollHeight;
}

function renderPaths() {
  if (!S) return;
  $("stPaths").textContent =
    "插件目录：" + S.plugin.path + "\n配置与日志：%APPDATA%\\HaloEchoLyric";
  $("abVer").textContent = "v" + S.app.version;
  $("sideVer").textContent = "v" + S.app.version;
}

/* ---------------- 交互 ---------------- */
function initActions() {
  $("dvScan").addEventListener("click", async () => {
    const r = await call("scan_devices");
    if (!r) return;
    toast(r.count ? "发现 " + r.count + " 个 Halo 接口" : "未发现 Halo 接口", r.count ? "ok" : "err");
    $("stUsb").textContent = r.count
      ? r.items.map((i) => i.describe + (i.isScreen ? "   ← 像素屏通道" : "")).join("\n")
      : "未发现匹配 VID 0x2D99 / PID 0xA106 的接口";
  });

  $("dvDisconnect").addEventListener("click", async () => {
    const online = S && S.device.state === "online";
    if (online) {
      await call("disconnect_device");
      toast("已断开设备");
    } else {
      const r = await call("connect_device");
      toast(r && r.ok ? "已连接设备" : "连接失败，请检查 USB", r && r.ok ? "ok" : "err");
    }
    refresh();
  });

  $("dvEnable").addEventListener("change", async (e) => {
    await pushConfig({ display: { enabled: e.target.checked } });
    toast(e.target.checked ? "同步已开启" : "同步已暂停", "ok");
  });

  $("lsInstall").addEventListener("click", async () => {
    const r = await call("install_plugin");
    toast(r && r.ok ? (r.message || "插件已安装") : ((r && r.error) || "安装失败"), r && r.ok ? "ok" : "err");
    refresh();
  });

  $("lsStatus").addEventListener("click", () => refresh(true));

  $("offMinus").addEventListener("click", () => changeOffset(-100));
  $("offPlus").addEventListener("click", () => changeOffset(100));

  $("scSend").addEventListener("click", async () => {
    const r = await call("send_custom_text", $("scText").value);
    toast(r && r.ok ? "已发送到屏幕" : ((r && r.error) || "发送失败"), r && r.ok ? "ok" : "err");
  });
  $("scTest").addEventListener("click", async () => {
    const r = await call("send_test_text");
    toast(r && r.ok ? "测试文字已发送" : ((r && r.error) || "发送失败"), r && r.ok ? "ok" : "err");
  });
  $("scColorBtn").addEventListener("click", () => $("scColor").click());
  $("scColor").addEventListener("change", async (e) => {
    const r = await call("set_screen_color", e.target.value);
    toast(r && r.ok ? "屏幕纯色已应用" : ((r && r.error) || "失败"), r && r.ok ? "ok" : "err");
  });

  $("scApply").addEventListener("click", async () => {
    await pushConfig({
      display: {
        max_columns: parseInt($("scCols").value, 10) || 20,
        color: hexToRgb($("scLyricColor").value),
        song_info_seconds: parseFloat($("scSongInfo").value) || 0,
        idle_to_ui_seconds: parseFloat($("scIdle").value) || 0,
      },
    });
    toast("已保存", "ok");
  });

  $("ltApply").addEventListener("click", async () => {
    const effect = (document.querySelector("#ltEffects button.on") || {}).dataset;
    const brightness = (document.querySelector('.seg[data-key="brightness"] button.on') || {}).dataset;
    const r = await call("apply_light",
      (effect && effect.val) || "dynamic",
      $("ltColor").value,
      (brightness && brightness.val) || "high",
      parseInt($("ltSpeed").value, 10) || 10,
      true);
    toast(r && r.ok ? "灯效已应用" : ((r && r.error) || "失败"), r && r.ok ? "ok" : "err");
  });
  $("ltOff").addEventListener("click", async () => {
    const r = await call("apply_light", "static", "#ffffff", "high", 10, false);
    toast(r && r.ok ? "已关闭氛围灯" : ((r && r.error) || "失败"), r && r.ok ? "ok" : "err");
  });
  $("ltSpeed").addEventListener("input", (e) => { $("ltSpeedVal").textContent = e.target.value; });

  $("stAutoConnect").addEventListener("change", (e) =>
    pushConfig({ device: { auto_connect: e.target.checked } }));
  $("stAutostart").addEventListener("change", async (e) => {
    const r = await call("set_autostart", e.target.checked);
    if (!(r && r.ok)) {
      toast((r && r.error) || "设置失败", "err");
      refresh();
    } else {
      toast(e.target.checked ? "已开启开机自启" : "已关闭开机自启", "ok");
    }
  });
  $("stRescan").addEventListener("click", () => $("dvScan").click());
  $("stOpenLog").addEventListener("click", () => call("open_log_dir"));
  $("abLog").addEventListener("click", () => call("open_log_dir"));
  $("abPlugin").addEventListener("click", () => $("lsInstall").click());
  $("stReset").addEventListener("click", async () => {
    const r = await call("reset_config");
    if (r && r.ok) { applyConfig(r.config); toast("已恢复默认配置", "ok"); }
  });
  $("stUninstall").addEventListener("click", async () => {
    if (!confirm("将删除 EchoMusic 插件、开机自启项、配置目录，并移除本程序。确定继续？")) return;
    await call("uninstall");
  });
  $("lgClear").addEventListener("click", async () => {
    await call("clear_logs");
    refresh();
  });
}

function hexToRgb(hex) {
  const t = String(hex || "").replace("#", "");
  if (t.length !== 6) return [255, 255, 255];
  return [parseInt(t.slice(0, 2), 16), parseInt(t.slice(2, 4), 16), parseInt(t.slice(4, 6), 16)];
}

async function changeOffset(delta) {
  lyricOffset = Math.max(-5000, Math.min(5000, lyricOffset + delta));
  $("offVal").textContent = (lyricOffset > 0 ? "+" : "") + lyricOffset + " ms";
  // 通过反向下发到配置：写入 display 的展示偏移由 engine 使用
  await pushConfig({ display: { lyric_offset_ms: lyricOffset } });
}

/* ---------------- 主循环 ---------------- */
let lastCfgJson = "";

async function refresh(loud) {
  const s = await call("get_state");
  if (!s) return;
  S = s;
  // 配置变化时才回填表单，避免每 600ms 覆盖用户正在输入的内容
  const cfgJson = JSON.stringify(s.config);
  if (cfgJson !== lastCfgJson) {
    lastCfgJson = cfgJson;
    applyConfig(s.config);
  }
  renderDevice(s.device);
  renderLyric(s.lyric);
  renderTimeline(s.lyric);
  renderLogs();
  if (s.options && !$("scScenes").dataset.init) { renderScenes(); renderPaths(); }
  if (loud) toast(s.lyric.source_online ? "EchoMusic 已连接" : "EchoMusic 未连接", s.lyric.source_online ? "ok" : "err");
}

let shellReady = false;
let dataReady = false;

/* 外壳（导航、控件、动画）立即初始化，不依赖后端：
   这样即使 WebView2 注入桥较慢，界面也能点、深链接也能立刻生效 */
function initShell() {
  if (shellReady) return;
  shellReady = true;
  initNav();
  initWindow();
  initSegs();
  initActions();
  renderViz();
  setInterval(animateViz, 90);
}

function startData() {
  if (dataReady) return;
  dataReady = true;
  refresh();
  setInterval(refresh, 600);
}

if (document.readyState === "loading") {
  document.addEventListener("DOMContentLoaded", initShell);
} else {
  initShell();
}

/* pywebview 注入桥的时机不固定，且会先给个空 api 对象再挂方法，
   所以必须等到具体方法可用才算就绪 */
function whenBridgeReady(cb) {
  let tries = 0;
  const timer = setInterval(() => {
    tries += 1;
    if (api()) {
      clearInterval(timer);
      cb();
    } else if (tries > 300) {
      clearInterval(timer);
      cb();
    }
  }, 100);
  if (api()) {
    clearInterval(timer);
    cb();
  }
}

whenBridgeReady(startData);
