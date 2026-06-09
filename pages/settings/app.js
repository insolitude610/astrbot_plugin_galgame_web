
var PLUGIN = "astrbot_plugin_galgame_web";
var API_BASE = "/api/plug/" + PLUGIN;
var BG_KEYS = ["background"];

var allFiles = [];
var config = {};
var selectedFiles = {};
var _assetCache = {};

function updateBatchBar() {
  var bar = document.getElementById("batch-bar");
  if (!bar) return;
  var sa = document.getElementById("select-all");
  var btn = document.getElementById("batch-delete-btn");
  if (!sa || !btn) return;
  var count = Object.keys(selectedFiles).length;
  bar.style.display = allFiles.length > 0 ? "flex" : "none";
  sa.checked = allFiles.length > 0 && count === allFiles.length;
  sa.indeterminate = count > 0 && count < allFiles.length;
  btn.textContent = "删除已选 (" + count + ")";
  btn.disabled = count === 0;
}

function toggleSelectAll() {
  var sa = document.getElementById("select-all");
  if (!sa) return;
  if (sa.checked) {
    for (var i = 0; i < allFiles.length; i++) selectedFiles[allFiles[i].name] = true;
  } else {
    selectedFiles = {};
  }
  renderFileGrid();
  updateBatchBar();
}

function toggleFileSelect(name) {
  if (selectedFiles[name]) { delete selectedFiles[name]; }
  else { selectedFiles[name] = true; }
  updateBatchBar();
}

async function batchDeleteSelected() {
  var names = Object.keys(selectedFiles);
  if (names.length === 0) return;
  setStatus("批量删除中...");
  try {
    var data = await apiPost("assets/batch-delete", { filenames: names });
    if (data.deleted && data.deleted.length > 0) {
      setStatus("已删除 " + data.deleted.length + " 个文件", "success");
      selectedFiles = {};
      await loadFiles();
    } else {
      setStatus(data.error || "批量删除失败", "error");
    }
  } catch(e) {
    setStatus("批量删除失败: " + e.message, "error");
  }
}

function apiGet(endpoint) {
  if (window.AstrBotPluginPage && window.AstrBotPluginPage.apiGet) {
    return window.AstrBotPluginPage.apiGet(endpoint);
  }
  return fetch(API_BASE + "/" + endpoint, { credentials: "include" }).then(function(resp) {
    if (!resp.ok) throw new Error(endpoint + " returned " + resp.status);
    return resp.json();
  });
}

function apiPost(endpoint, body) {
  if (window.AstrBotPluginPage && window.AstrBotPluginPage.apiPost) {
    return window.AstrBotPluginPage.apiPost(endpoint, body);
  }
  return fetch(API_BASE + "/" + endpoint, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    credentials: "include",
    body: JSON.stringify(body),
  }).then(function(resp) {
    if (!resp.ok) throw new Error(endpoint + " returned " + resp.status);
    return resp.json();
  });
}

/* ---- BGM ---- */

var bgmFiles = [];
var currentBgmFile = "";
var _mainBgmPlaying = false;
var bgmChannel;

async function loadBgmList() {
  try {
    var data = await apiGet("bgm/list");
    bgmFiles = data.files || [];
  } catch(e) {
    bgmFiles = [];
  }
  try {
    var prefs = await apiGet("prefs");
    currentBgmFile = prefs.bgm_file || "";
  } catch(e) {
    currentBgmFile = "";
  }
  renderBgmList();
}

function renderBgmList() {
  var container = document.getElementById("bgm-list");
  if (!bgmFiles.length) {
    container.innerHTML = "<div style='color:#777;font-size:13px;padding:8px 0;'>暂无音乐文件</div>";
    return;
  }
  var html = "";
  for (var i = 0; i < bgmFiles.length; i++) {
    var f = bgmFiles[i];
    var isSelected = f.name === currentBgmFile;
    var cls = isSelected ? "audio-item selected" : "audio-item";
    var sizeStr = f.size ? formatSize(f.size) : "";
    html += "<div class='" + cls + "' id='bgm-" + i + "'>";
    html += "<span class='name'>" + escHtml(f.name) + "</span>";
    if (sizeStr) html += "<span class='size'>" + sizeStr + "</span>";
    if (isSelected) {
      html += "<span class='current-tag'>当前</span>";
      html += "<button class='btn-play' onclick='toggleMainBgm()' id='bgm-play-pause-btn'>" + (_mainBgmPlaying ? "\u23F8" : "\u25B6") + "</button>";
    }
    html += "<button class='btn-sel' onclick='selectBgm(\"" + escJs(f.name) + "\")'>选择</button>";
    html += "<button class='btn-del-audio' onclick='deleteBgm(\"" + escJs(f.name) + "\")'>删除</button>";
    html += "</div>";
  }
  container.innerHTML = html;
}

function escHtml(s) {
  return s.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;").replace(/"/g, "&quot;");
}
function escJs(s) {
  return s.replace(/\\/g, "\\\\").replace(/'/g, "\\'").replace(/"/g, "\\\"");
}
function formatSize(bytes) {
  if (bytes < 1024) return bytes + "B";
  if (bytes < 1048576) return (bytes / 1024).toFixed(1) + "KB";
  return (bytes / 1048576).toFixed(1) + "MB";
}

function toggleMainBgm() {
  _mainBgmPlaying = !_mainBgmPlaying;
  var btn = document.getElementById("bgm-play-pause-btn");
  if (btn) btn.textContent = _mainBgmPlaying ? "\u23F8" : "\u25B6";
  if (bgmChannel) bgmChannel.postMessage({ kind: _mainBgmPlaying ? "bgm-play" : "bgm-pause" });
}

async function selectBgm(name) {
  _mainBgmPlaying = true;
  currentBgmFile = name;
  renderBgmList();
  try {
    await apiPost("prefs", { bgm_file: name });
  } catch(e) {
    console.warn("Failed to save bgm_file:", e);
  }
  if (bgmChannel) bgmChannel.postMessage({ kind: "bgm-change", file: name });
}

async function uploadBgm(input) {
  var file = input.files[0];
  if (!file) return;
  var MAX = 30 * 1024 * 1024;
  if (file.size > MAX) {
    setBgmStatus("文件太大 (最大30MB)", "error");
    input.value = "";
    return;
  }
  setBgmStatus("上传中...");
  try {
    var base64 = await new Promise(function(resolve, reject) {
      var reader = new FileReader();
      reader.onload = function() { resolve(reader.result); };
      reader.onerror = reject;
      reader.readAsDataURL(file);
    });
    var data = await apiPost("bgm/upload", { name: file.name, data: base64 });
    if (data.uploaded) {
      setBgmStatus("已上传: " + data.uploaded, "success");
      await loadBgmList();
      selectBgm(file.name);
    } else {
      setBgmStatus(data.error || "上传失败", "error");
    }
  } catch(e) {
    setBgmStatus("上传失败: " + e.message, "error");
  }
  input.value = "";
}

async function deleteBgm(name) {
  try {
    var data = await apiPost("bgm/delete", { filename: name });
    if (data.deleted) {
      if (currentBgmFile === name) currentBgmFile = "";
      await loadBgmList();
    }
  } catch(e) {
    alert("删除失败: " + e.message);
  }
}

function setBgmStatus(msg, type) {
  var el = document.getElementById("bgm-status");
  el.textContent = msg;
  el.className = "status" + (type ? " " + type : "");
  if (msg) setTimeout(function() { if (el.textContent === msg) { el.textContent = ""; el.className = "status"; } }, 5000);
}

/* ---- volume ---- */

function loadVolumePrefs() {
  var vv = document.getElementById("voice-vol");
  var bv = document.getElementById("bgm-vol");
  var vvv = document.getElementById("voice-vol-val");
  var bvv = document.getElementById("bgm-vol-val");
  if (!vv || !bv || !vvv || !bvv) return;
  vv.value = (config.voice_volume != null ? config.voice_volume : 1.0);
  bv.value = (config.bgm_volume != null ? config.bgm_volume : 0.5);
  vvv.textContent = Math.round(vv.value * 100) + "%";
  bvv.textContent = Math.round(bv.value * 100) + "%";
}

var _volTimer;
function saveVolumes() {
  clearTimeout(_volTimer);
  _volTimer = setTimeout(function() {
    var vv = document.getElementById("voice-vol");
    var bv = document.getElementById("bgm-vol");
    if (!vv || !bv) return;
    apiPost("prefs", { voice_volume: parseFloat(vv.value), bgm_volume: parseFloat(bv.value) }).catch(function(){});
  }, 300);
}

function onVoiceVolume() {
  var vv = document.getElementById("voice-vol");
  if (!vv) return;
  document.getElementById("voice-vol-val").textContent = Math.round(vv.value * 100) + "%";
  saveVolumes();
  if (bgmChannel) bgmChannel.postMessage({ kind: "voice-volume", volume: parseFloat(vv.value) });
}

function onBgmVolume() {
  var bv = document.getElementById("bgm-vol");
  if (!bv) return;
  document.getElementById("bgm-vol-val").textContent = Math.round(bv.value * 100) + "%";
  saveVolumes();
  if (bgmChannel) bgmChannel.postMessage({ kind: "bgm-volume", volume: parseFloat(bv.value) });
}

async function init() {
  try {
    config = await apiGet("config");
  } catch(e) {
    config = {};
  }

  try { bgmChannel = new BroadcastChannel("galgame-comms"); } catch(e) {}

  var rb = document.getElementById("refresh-btn");
  if (rb) rb.onclick = loadFiles;
  await loadFiles();
  await loadBgmList();
  if (currentBgmFile) _mainBgmPlaying = true;
  loadVolumePrefs();
  await preloadAssets();
}

function applyBackground() {
  var bg = config.background;
  if (bg && _assetCache[bg]) {
    document.body.style.backgroundImage = "url(" + _assetCache[bg] + ")";
    document.body.classList.add("bg-loaded");
  }
}

function preloadAssets() {
  return apiGet("assets/list").then(function(listData) {
    var allFiles = listData.files || [];
    var names = [];
    allFiles.forEach(function(f) { names.push(f.name); });
    var exps = config.expressions || {};
    for (var k in exps) { if (exps[k] && names.indexOf(exps[k]) < 0) names.push(exps[k]); }
    if (config.background && names.indexOf(config.background) < 0) names.push(config.background);
    if (config.history_avatar && names.indexOf(config.history_avatar) < 0) names.push(config.history_avatar);
    if (!names.length) { applyBackground(); renderAll(); return; }
    return apiPost("assets/batch", { names: names }).then(function(resp) {
      (resp.files || []).forEach(function(f) { _assetCache[f.name] = f.data; });
      applyBackground();
      renderAll();
    });
  }).catch(function(e) {
    console.warn("preloadAssets failed:", e);
    renderAll();
  });
}

/* ---- data ---- */

function getEmotionKeys() {
  return config.emotion_keys || ["neutral","happy","sad","angry","surprised","blush","thinking"];
}

function getMatchedFile(key, prefix) {
  var keyL = key.toLowerCase();
  // 1) exact stem match: prefix_key
  if (prefix) {
    var prefixed = prefix + "_" + keyL;
    for (var i = 0; i < allFiles.length; i++) {
      var stem = allFiles[i].name.replace(/\.[^.]+$/, "").toLowerCase();
      if (stem === prefixed) return allFiles[i];
    }
  }
  // 2) exact stem match without prefix
  for (var i = 0; i < allFiles.length; i++) {
    var stem = allFiles[i].name.replace(/\.[^.]+$/, "").toLowerCase();
    if (stem === keyL) return allFiles[i];
  }
  // 3) word-parts match with prefix
  if (prefix) {
    var prefixL = prefix.toLowerCase();
    for (var i = 0; i < allFiles.length; i++) {
      var stem = allFiles[i].name.replace(/\.[^.]+$/, "").toLowerCase();
      var parts = stem.split(/[_\-\s.]+/);
      if (parts.indexOf(prefixL) !== -1 && parts.indexOf(keyL) !== -1) return allFiles[i];
    }
  }
  // 4) word-parts match
  for (var i = 0; i < allFiles.length; i++) {
    var stem = allFiles[i].name.replace(/\.[^.]+$/, "").toLowerCase();
    var parts = stem.split(/[_\-\s.]+/);
    if (parts.indexOf(keyL) !== -1) return allFiles[i];
  }
  // 5) substring fallback
  for (var i = 0; i < allFiles.length; i++) {
    var stem = allFiles[i].name.replace(/\.[^.]+$/, "").toLowerCase();
    if (stem.indexOf(keyL) !== -1) return allFiles[i];
  }
  return null;
}

/* ---- render ---- */

function renderAll() {
  renderModeIndicator();
  renderSingleSlots();
  renderVRMSlot();
  renderBgSlot();
  renderAvatarSlot();
  renderFileGrid();
}

function renderModeIndicator() {
  var mode = config.sprite_mode || "single";
  var labels = { single: "Single 单图", vrm: "VRM 3D" };
  var el = document.getElementById("mode-indicator");
  el.innerHTML = '当前渲染模式：<span class="mode-badge ' + mode + '">' + (labels[mode] || "Single 单图") + '</span> &nbsp;<span style="font-size:11px;color:#666;">（在插件配置页切换 sprite_mode）</span>';
}

function renderSingleSlots() {
  var section = document.getElementById("section-single");
  var grid = document.getElementById("slots-single");
  var mode = config.sprite_mode || "single";
  section.className = "section " + (mode === "single" ? "active" : "inactive");
  grid.innerHTML = "";
  var keys = getEmotionKeys();
  for (var i = 0; i < keys.length; i++) {
    grid.appendChild(slotCard(keys[i], getMatchedFile(keys[i], "single"), keys[i], "single"));
  }
}

function renderVRMSlot() {
  var section = document.getElementById("section-layered");
  var grid = document.getElementById("slots-vrm");
  var mode = config.sprite_mode || "single";
  section.className = "section " + (mode === "vrm" ? "active" : "inactive");
  grid.innerHTML = "";
  grid.appendChild(slotCard("vrm_model", getMatchedFile("model", "vrm") || getMatchedFile("vrm", "vrm"), "VRM 3D模型 (.vrm)", "vrm"));
}

function renderBgSlot() {
  var grid = document.getElementById("slots-bg");
  grid.innerHTML = "";
  grid.appendChild(slotCard("background", getMatchedFile("background", "bg"), "背景图", "bg"));
}

function renderAvatarSlot() {
  var grid = document.getElementById("slots-avatar");
  grid.innerHTML = "";
  grid.appendChild(slotCard("history_avatar", getMatchedFile("history_avatar", "avatar"), "头像", "avatar"));
}

function slotCard(key, matchedFile, label, idPrefix) {
  var card = document.createElement("div");
  card.className = matchedFile ? "slot-card matched" : "slot-card missing";
  card.id = "slot-" + idPrefix + "-" + key;

  if (matchedFile) {
    var cached = _assetCache[matchedFile.name];
    if (cached) {
      var img = document.createElement("img");
      img.className = "slot-img";
      img.alt = key;
      img.src = cached;
      card.appendChild(img);
    } else {
      var ph = document.createElement("div");
      ph.className = "slot-img placeholder";
      ph.textContent = "🖼";
      card.appendChild(ph);
    }
  } else {
    var ph = document.createElement("div");
    ph.className = "slot-img placeholder";
    ph.textContent = "🖼";
    card.appendChild(ph);
  }

  var nameDiv = document.createElement("div");
  nameDiv.className = "slot-name";
  nameDiv.textContent = label;
  card.appendChild(nameDiv);

  var statusDiv = document.createElement("div");
  statusDiv.className = "slot-status " + (matchedFile ? "matched" : "missing");
  statusDiv.textContent = matchedFile ? "\u2705 " + matchedFile.name : "\u274C 未上传";
  card.appendChild(statusDiv);

  var fid = "file-" + idPrefix + "-" + key;
  var uploadKey = idPrefix + "_" + key;
  var fileInput = document.createElement("input");
  fileInput.type = "file";
  fileInput.accept = "image/*";
  fileInput.id = fid;
  fileInput.style.display = "none";
  (function(k, inp) { inp.onchange = function() { uploadToSlot(k, inp); }; })(uploadKey, fileInput);
  card.appendChild(fileInput);

  var btn = document.createElement("button");
  btn.className = "btn btn-primary";
  btn.textContent = "上传";
  (function(fidRef) { btn.onclick = function() { document.getElementById(fidRef).click(); }; })(fid);
  card.appendChild(btn);

  if (allFiles.length > 0) {
    var select = document.createElement("select");
    select.style.cssText = "margin-top:4px;font-size:11px;padding:2px 4px;background:#1a1a2e;color:#ccc;border:1px solid #444;border-radius:4px;width:100%;";
    var opt0 = document.createElement("option");
    opt0.value = "";
    opt0.textContent = "选择已有文件...";
    select.appendChild(opt0);
    for (var j = 0; j < allFiles.length; j++) {
      var opt = document.createElement("option");
      opt.value = allFiles[j].name;
      opt.textContent = allFiles[j].name;
      select.appendChild(opt);
    }
    (function(k, sel) { sel.onchange = function() { if (sel.value) assignToSlot(k, sel.value); }; })(uploadKey, select);
    card.appendChild(select);
  }

  return card;
}

function renderFileGrid() {
  var container = document.getElementById("grid-container");
  if (allFiles.length === 0) {
    container.innerHTML = '<div class="loading">暂无文件</div>';
    return;
  }
  var grid = document.createElement("div");
  grid.className = "grid";
  for (var i = 0; i < allFiles.length; i++) {
    var f = allFiles[i];
    var card = document.createElement("div");
    card.className = "card";

    var cb = document.createElement("input");
    cb.type = "checkbox";
    cb.className = "card-check";
    cb.checked = !!selectedFiles[f.name];
    (function(fn) { cb.onchange = function() { toggleFileSelect(fn); }; })(f.name);
    card.appendChild(cb);

    var img = document.createElement("img");
    img.className = "card-img";
    img.alt = f.name;
    img.loading = "lazy";
    img.src = _assetCache[f.name] || f.url || "";
    card.appendChild(img);

    var body = document.createElement("div");
    body.className = "card-body";
    var nameEl = document.createElement("div");
    nameEl.className = "card-name";
    nameEl.textContent = f.name;
    body.appendChild(nameEl);

    var actions = document.createElement("div");
    actions.className = "card-actions";
    var delBtn = document.createElement("button");
    delBtn.className = "btn btn-danger";
    delBtn.textContent = "删除";
    delBtn.onclick = function(fn) { return function() { deleteFile(fn); }; }(f.name);
    actions.appendChild(delBtn);
    body.appendChild(actions);

    card.appendChild(body);
    grid.appendChild(card);
  }
  container.innerHTML = "";
  container.appendChild(grid);
}

/* ---- upload ---- */

async function uploadToSlot(key, input) {
  var file = input.files[0];
  if (!file) return;
  input.value = "";

  var base64 = await new Promise(function(resolve, reject) {
    var reader = new FileReader();
    reader.onload = function() { resolve(reader.result); };
    reader.onerror = reject;
    reader.readAsDataURL(file);
  });

  setStatus("上传 " + key + " ...");
  try {
    var data = await apiPost("assets/upload-key", { key: key, data: base64 });
    if (data.uploaded) {
      setStatus("✅ " + key + " → " + data.uploaded, "success");
      await loadFiles();
      await preloadAssets();
    } else {
      setStatus("❌ " + key + ": " + (data.error || "失败"), "error");
    }
  } catch(e) {
    setStatus("❌ " + key + ": " + e.message, "error");
  }
}

async function assignToSlot(key, sourceName) {
  setStatus("分配 " + sourceName + " → " + key + " ...");
  try {
    var data = await apiPost("assets/copy", { source: sourceName, key: key });
    if (data.copied) {
      setStatus("✅ " + data.source + " → " + data.copied, "success");
      await loadFiles();
    } else {
      setStatus("❌ " + (data.error || "失败"), "error");
    }
  } catch(e) {
    setStatus("❌ " + e.message, "error");
  }
}

/* ---- list / delete ---- */

async function loadFiles() {
  setStatus("");
  var loading = document.getElementById("loading");
  loading.style.display = "block";
  try {
    var data = await apiGet("assets/list");
    var rawFiles = data.files || [];
    for (var i = 0; i < rawFiles.length; i++) {
      rawFiles[i].url = "/api/plug/astrbot_plugin_galgame_web/assets/file?name=" + encodeURIComponent(rawFiles[i].name);
    }
    allFiles = rawFiles;
    selectedFiles = {};
    renderAll();
    updateBatchBar();
  } catch(e) {
    setStatus("加载失败: " + e.message, "error");
  }
  loading.style.display = "none";
}

async function deleteFile(filename) {
  setStatus("删除中...");
  try {
    var data = await apiPost("assets/delete", { filename: filename });
    if (data.deleted) {
      setStatus("已删除: " + data.deleted, "success");
      await loadFiles();
    } else {
      setStatus(data.error || "删除失败", "error");
    }
  } catch(e) {
    setStatus("删除失败: " + e.message, "error");
  }
}

function setStatus(msg, type) {
  var el = document.getElementById("status");
  if (!el) return;
  el.textContent = msg;
  el.className = "status" + (type ? " " + type : "");
  if (msg) setTimeout(function() { if (el.textContent === msg) { el.textContent = ""; el.className = "status"; } }, 5000);
}

if (window.AstrBotPluginPage) {
  init();
} else {
  var _sPoll = setInterval(function() {
    if (window.AstrBotPluginPage) {
      clearInterval(_sPoll);
      init();
    }
  }, 100);
  setTimeout(function() { clearInterval(_sPoll); }, 10000);
}

