
var PLUGIN = "astrbot_plugin_galgame_web";
var API_BASE = "/api/plug/" + PLUGIN;
var BG_KEYS = ["background"];

var allFiles = [];
var config = {};
var selectedFiles = {};

function updateBatchBar() {
  var bar = document.getElementById("batch-bar");
  var sa = document.getElementById("select-all");
  var btn = document.getElementById("batch-delete-btn");
  var count = Object.keys(selectedFiles).length;
  bar.style.display = allFiles.length > 0 ? "flex" : "none";
  sa.checked = allFiles.length > 0 && count === allFiles.length;
  sa.indeterminate = count > 0 && count < allFiles.length;
  btn.textContent = "删除已选 (" + count + ")";
  btn.disabled = count === 0;
}

function toggleSelectAll() {
  var sa = document.getElementById("select-all");
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
  if (!confirm("确定删除 " + names.length + " 个文件？")) return;
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
var bgmAudioEl = null;
var playingBgm = null;

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
    if (isSelected) html += "<span class='current-tag'>当前</span>";
    html += "<button class='btn-play' onclick='toggleBgmPreview(" + i + ", this)'>▶</button>";
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

function toggleBgmPreview(idx, btn) {
  if (bgmAudioEl && playingBgm === idx) {
    bgmAudioEl.pause();
    bgmAudioEl = null;
    playingBgm = null;
    btn.textContent = "▶";
    btn.classList.remove("playing");
    return;
  }
  if (bgmAudioEl) {
    bgmAudioEl.pause();
    var prevBtn = document.querySelector(".btn-play.playing");
    if (prevBtn) { prevBtn.textContent = "▶"; prevBtn.classList.remove("playing"); }
  }
  var f = bgmFiles[idx];
  bgmAudioEl = new Audio("/api/plug/astrbot_plugin_galgame_web/bgm/file?name=" + encodeURIComponent(f.name));
  bgmAudioEl.onended = function() {
    btn.textContent = "▶";
    btn.classList.remove("playing");
    playingBgm = null;
    bgmAudioEl = null;
  };
  bgmAudioEl.play().then(function() {
    btn.textContent = "⏸";
    btn.classList.add("playing");
    playingBgm = idx;
  }).catch(function(e) {
    console.warn("BGM preview failed:", e);
    bgmAudioEl = null;
  });
}

async function selectBgm(name) {
  currentBgmFile = name;
  renderBgmList();
  try {
    await apiPost("prefs", { bgm_file: name });
  } catch(e) {
    console.warn("Failed to save bgm_file:", e);
  }
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
    } else {
      setBgmStatus(data.error || "上传失败", "error");
    }
  } catch(e) {
    setBgmStatus("上传失败: " + e.message, "error");
  }
  input.value = "";
}

async function deleteBgm(name) {
  if (!confirm("确定删除 " + name + "？")) return;
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
  var vv = document.getElementById("voice-volume");
  var bv = document.getElementById("bgm-volume");
  var vvv = document.getElementById("voice-vol-val");
  var bvv = document.getElementById("bgm-vol-val");
  vv.value = Math.round((config.voice_volume != null ? config.voice_volume : 1.0) * 100);
  bv.value = Math.round((config.bgm_volume != null ? config.bgm_volume : 0.5) * 100);
  vvv.textContent = vv.value + "%";
  bvv.textContent = bv.value + "%";
}

var _volTimer;
function saveVolumes() {
  clearTimeout(_volTimer);
  _volTimer = setTimeout(function() {
    var vv = document.getElementById("voice-volume");
    var bv = document.getElementById("bgm-volume");
    apiPost("prefs", { voice_volume: parseInt(vv.value) / 100, bgm_volume: parseInt(bv.value) / 100 }).catch(function(){});
  }, 300);
}

function onVoiceVolume() {
  var vv = document.getElementById("voice-volume");
  document.getElementById("voice-vol-val").textContent = vv.value + "%";
  saveVolumes();
}

function onBgmVolume() {
  var bv = document.getElementById("bgm-volume");
  document.getElementById("bgm-vol-val").textContent = bv.value + "%";
  saveVolumes();
}

async function init() {
  try {
    config = await apiGet("config");
  } catch(e) {
    config = {};
  }

  var rb = document.getElementById("refresh-btn");
  if (rb) rb.onclick = loadFiles;
  applyBackground();
  await loadFiles();
  await loadBgmList();
  loadVolumePrefs();
}

function applyBackground() {
  var bg = config.background;
  if (bg) {
    document.body.style.backgroundImage = "url(/api/plug/astrbot_plugin_galgame_web/assets/file?name=" + encodeURIComponent(bg) + ")";
    document.body.classList.add("bg-loaded");
  }
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

  if (matchedFile && matchedFile.url) {
    var img = document.createElement("img");
    img.className = "slot-img";
    img.alt = key;
    img.src = matchedFile.url;
    card.appendChild(img);
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
    img.src = f.url || "";
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
  if (!confirm("确定删除 " + filename + "？")) return;
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
  el.textContent = msg;
  el.className = "status" + (type ? " " + type : "");
  if (msg) setTimeout(function() { if (el.textContent === msg) { el.textContent = ""; el.className = "status"; } }, 5000);
}

init();

