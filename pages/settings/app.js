
var PLUGIN = "astrbot_plugin_galgame_web";
var API_BASE = "/api/plug/" + PLUGIN;
var BG_KEYS = ["background"];

var allFiles = [];
var config = {};
var selectedFiles = {};
var _assetCache = {};
var _assetWaiters = {};
var _assetQueue = {};
var _assetQueueTimer = null;
var _assetObserver = null;

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
  showConfirm("确定删除 " + names.length + " 个文件？", null, async function() {
    setStatus("批量删除中...");
    try {
      var data = await apiPost("assets/batch-delete", { filenames: names });
      if (data.deleted && data.deleted.length > 0) {
        data.deleted.forEach(function(name) { delete _assetCache[name]; });
        setStatus("已删除 " + data.deleted.length + " 个文件", "success");
        selectedFiles = {};
        await loadFiles();
      } else {
        setStatus(data.error || "批量删除失败", "error");
      }
    } catch(e) {
      setStatus("批量删除失败: " + e.message, "error");
    }
  });
}

function apiGet(endpoint, params) {
  if (window.AstrBotPluginPage && window.AstrBotPluginPage.apiGet) {
    return window.AstrBotPluginPage.apiGet(endpoint, params);
  }
  var url = API_BASE + "/" + endpoint;
  if (params) url += "?" + new URLSearchParams(params).toString();
  return fetch(url, { credentials: "include" }).then(function(resp) {
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
    _mainBgmPlaying = !!currentBgmFile && prefs.bgm_playing !== false;
  } catch(e) {
    currentBgmFile = "";
    _mainBgmPlaying = false;
  }
  renderBgmList();
}

function renderBgmList() {
  var container = document.getElementById("bgm-list");
  container.textContent = "";
  if (!bgmFiles.length) {
    var empty = document.createElement("div");
    empty.style.cssText = "color:#777;font-size:13px;padding:8px 0;";
    empty.textContent = "暂无音乐文件";
    container.appendChild(empty);
    return;
  }
  for (var i = 0; i < bgmFiles.length; i++) {
    var f = bgmFiles[i];
    var isSelected = f.name === currentBgmFile;
    var sizeStr = f.size ? formatSize(f.size) : "";
    var row = document.createElement("div");
    row.className = isSelected ? "audio-item selected" : "audio-item";
    row.id = "bgm-" + i;
    var nameEl = document.createElement("span");
    nameEl.className = "name";
    nameEl.textContent = f.name;
    row.appendChild(nameEl);
    if (sizeStr) {
      var sizeEl = document.createElement("span");
      sizeEl.className = "size";
      sizeEl.textContent = sizeStr;
      row.appendChild(sizeEl);
    }
    if (isSelected) {
      var currentTag = document.createElement("span");
      currentTag.className = "current-tag";
      currentTag.textContent = "当前";
      row.appendChild(currentTag);
      var playBtn = document.createElement("button");
      playBtn.className = "btn-play";
      playBtn.id = "bgm-play-pause-btn";
      playBtn.textContent = _mainBgmPlaying ? "\u23F8" : "\u25B6";
      playBtn.addEventListener("click", toggleMainBgm);
      row.appendChild(playBtn);
    }
    var selectBtn = document.createElement("button");
    selectBtn.className = "btn-sel";
    selectBtn.textContent = "选择";
    selectBtn.addEventListener("click", (function(name) {
      return function() { selectBgm(name); };
    })(f.name));
    row.appendChild(selectBtn);
    var deleteBtn = document.createElement("button");
    deleteBtn.className = "btn-del-audio";
    deleteBtn.textContent = "删除";
    deleteBtn.addEventListener("click", (function(name) {
      return function() { deleteBgm(name); };
    })(f.name));
    row.appendChild(deleteBtn);
    container.appendChild(row);
  }
}

async function fetchAssetChunk(chunk) {
  try {
    var response = await apiPost("assets/batch", { names: chunk });
    (response.files || []).forEach(function(file) {
      _assetCache[file.name] = file.data;
      var waiters = _assetWaiters[file.name] || [];
      waiters.forEach(function(img) { img.src = file.data; });
      delete _assetWaiters[file.name];
    });
  } catch (error) {
    if (chunk.length <= 1) throw error;
    var middle = Math.ceil(chunk.length / 2);
    await fetchAssetChunk(chunk.slice(0, middle));
    await fetchAssetChunk(chunk.slice(middle));
  }
}

async function fetchAssetNames(names) {
  var unique = [];
  names.forEach(function(name) {
    if (name && !_assetCache[name] && unique.indexOf(name) < 0) unique.push(name);
  });
  for (var offset = 0; offset < unique.length; offset += 24) {
    await fetchAssetChunk(unique.slice(offset, offset + 24));
  }
}

function flushAssetQueue() {
  _assetQueueTimer = null;
  var names = Object.keys(_assetQueue).slice(0, 24);
  names.forEach(function(name) { delete _assetQueue[name]; });
  if (!names.length) return;
  fetchAssetNames(names).catch(function(error) {
    console.warn("asset preview load failed:", error);
  }).finally(function() {
    if (Object.keys(_assetQueue).length) {
      _assetQueueTimer = setTimeout(flushAssetQueue, 0);
    }
  });
}

function queueAssetPreview(name) {
  if (!name || _assetCache[name]) return;
  _assetQueue[name] = true;
  if (!_assetQueueTimer) _assetQueueTimer = setTimeout(flushAssetQueue, 0);
}

function attachAssetPreview(img, name) {
  if (_assetCache[name]) {
    img.src = _assetCache[name];
    return;
  }
  (_assetWaiters[name] || (_assetWaiters[name] = [])).push(img);
  if (!("IntersectionObserver" in window)) {
    queueAssetPreview(name);
    return;
  }
  if (!_assetObserver) {
    _assetObserver = new IntersectionObserver(function(entries) {
      entries.forEach(function(entry) {
        if (!entry.isIntersecting) return;
        _assetObserver.unobserve(entry.target);
        queueAssetPreview(entry.target.dataset.assetName);
      });
    }, { rootMargin: "200px" });
  }
  img.dataset.assetName = name;
  _assetObserver.observe(img);
}

function readFileAsDataUrl(file) {
  return new Promise(function(resolve, reject) {
    var reader = new FileReader();
    reader.onload = function() { resolve(reader.result); };
    reader.onerror = reject;
    reader.readAsDataURL(file);
  });
}

async function uploadAssetFiles(fileList) {
  var files = Array.prototype.slice.call(fileList || []);
  if (!files.length) return;
  if (files.length > 32) {
    setStatus("一次最多上传 32 张图片", "error");
    return;
  }
  var totalBytes = 0;
  for (var i = 0; i < files.length; i++) {
    var file = files[i];
    var imageName = /\.(png|jpe?g|webp|bmp|gif)$/i.test(file.name);
    if ((!file.type.startsWith("image/") && !imageName) || file.size > 10 * 1024 * 1024) {
      setStatus("文件格式不支持或单张超过 10MB: " + file.name, "error");
      return;
    }
    totalBytes += file.size;
  }
  if (totalBytes > 30 * 1024 * 1024) {
    setStatus("一次上传的图片总大小不能超过 30MB", "error");
    return;
  }
  setStatus("正在上传 " + files.length + " 个文件...");
  try {
    var payload = await Promise.all(files.map(async function(file) {
      return { name: file.name, data: await readFileAsDataUrl(file) };
    }));
    var result = await apiPost("assets/upload", { files: payload });
    if (!result.uploaded || !result.uploaded.length) {
      throw new Error(result.error || "没有文件被上传");
    }
    setStatus("已上传 " + result.uploaded.length + " 个文件", "success");
    await loadFiles();
    await preloadAssets();
  } catch(e) {
    setStatus("上传失败: " + e.message, "error");
  }
}

function setupDragUpload() {
  var zone = document.getElementById("drag-zone");
  var input = document.getElementById("bulk-file-input");
  if (!zone || !input || zone.dataset.ready === "1") return;
  zone.dataset.ready = "1";
  zone.addEventListener("click", function() { input.click(); });
  zone.addEventListener("keydown", function(event) {
    if (event.key === "Enter" || event.key === " ") {
      event.preventDefault();
      input.click();
    }
  });
  input.addEventListener("change", function() {
    uploadAssetFiles(input.files).finally(function() { input.value = ""; });
  });
  ["dragenter", "dragover"].forEach(function(name) {
    zone.addEventListener(name, function(event) {
      event.preventDefault();
      zone.classList.add("drag-active");
    });
  });
  ["dragleave", "drop"].forEach(function(name) {
    zone.addEventListener(name, function(event) {
      event.preventDefault();
      zone.classList.remove("drag-active");
    });
  });
  zone.addEventListener("drop", function(event) {
    uploadAssetFiles(event.dataTransfer.files);
  });
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
  apiPost("prefs", { bgm_playing: _mainBgmPlaying }).catch(function() {});

  var preview = document.getElementById("bgm-preview-audio");
  if (_mainBgmPlaying) {
    if (preview && currentBgmFile) {
      apiGet("bgm/data", { name: currentBgmFile }).then(function(resp) {
        preview.src = "data:" + resp.mime + ";base64," + resp.audio;
        preview.play().catch(function() {});
      }).catch(function() {
        preview.src = "/api/plug/astrbot_plugin_galgame_web/bgm/file?name=" + encodeURIComponent(currentBgmFile);
        preview.play().catch(function() {});
      });
    }
  } else {
    if (preview) { preview.pause(); preview.src = ""; }
  }

  if (bgmChannel) bgmChannel.postMessage({ kind: _mainBgmPlaying ? "bgm-play" : "bgm-pause" });
}

async function selectBgm(name) {
  _mainBgmPlaying = true;
  currentBgmFile = name;
  renderBgmList();
  try {
    await apiPost("prefs", { bgm_file: name, bgm_playing: true });
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
    var data = await _proxyApiPost("bgm/upload", { name: file.name, data: base64 });
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

function _proxyApiPost(endpoint, body) {
  return apiPost(endpoint, body);
}

function deleteBgm(name) {
  showConfirm("确定删除 " + name + "？", null, async function() {
    try {
      var data = await apiPost("bgm/delete", { filename: name });
      if (data.deleted) {
        if (currentBgmFile === name) currentBgmFile = "";
        showToast("已删除: " + name, "success");
        await loadBgmList();
      }
    } catch(e) {
      showToast("删除失败: " + e.message, "error");
    }
  });
}

function setBgmStatus(msg, type) {
  var el = document.getElementById("bgm-status");
  if (!el) return;
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
  setupDragUpload();

  var rb = document.getElementById("refresh-btn");
  if (rb) rb.onclick = loadFiles;
  await loadFiles();
  await loadBgmList();
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
  var names = [];
  var exps = config.expressions || {};
  for (var k in exps) { if (exps[k]) names.push(exps[k]); }
  if (config.background) names.push(config.background);
  if (config.history_avatar) names.push(config.history_avatar);
  return fetchAssetNames(names).then(function() {
    applyBackground();
    renderAll();
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
  if (_assetObserver) _assetObserver.disconnect();
  _assetObserver = null;
  _assetWaiters = {};
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
  if (!labels[mode]) mode = "single";
  var el = document.getElementById("mode-indicator");
  el.textContent = "当前渲染模式：";
  var badge = document.createElement("span");
  badge.className = "mode-badge " + mode;
  badge.textContent = labels[mode];
  el.appendChild(badge);
  var hint = document.createElement("span");
  hint.style.cssText = "font-size:11px;color:#666;";
  hint.textContent = " （在插件配置页切换 sprite_mode）";
  el.appendChild(hint);
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
    var img = document.createElement("img");
    img.className = "slot-img";
    img.alt = key;
    attachAssetPreview(img, matchedFile.name);
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
    attachAssetPreview(img, f.name);
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
      await preloadAssets();
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

function deleteFile(filename) {
  showConfirm("确定删除 " + filename + "？", null, async function() {
    setStatus("删除中...");
    try {
      var data = await apiPost("assets/delete", { filename: filename });
      if (data.deleted) {
        delete _assetCache[filename];
        setStatus("已删除: " + data.deleted, "success");
        await loadFiles();
      } else {
        setStatus(data.error || "删除失败", "error");
      }
    } catch(e) {
      setStatus("删除失败: " + e.message, "error");
    }
  });
}

function setStatus(msg, type) {
  var el = document.getElementById("status");
  if (!el) return;
  el.textContent = msg;
  el.className = "status" + (type ? " " + type : "");
  if (msg) setTimeout(function() { if (el.textContent === msg) { el.textContent = ""; el.className = "status"; } }, 5000);
}

/* ---- confirm overlay & toast ---- */

var _confirmCb = null;
var _toastTimer = null;

function showConfirm(message, detail, onConfirm) {
  _confirmCb = onConfirm;
  var msgEl = document.getElementById("confirm-msg");
  var detEl = document.getElementById("confirm-detail");
  var okBtn = document.getElementById("confirm-ok");
  if (msgEl) msgEl.textContent = message;
  if (detEl) {
    detEl.textContent = detail || "";
    detEl.style.display = detail ? "" : "none";
  }
  var ov = document.getElementById("confirm-overlay");
  if (ov) ov.classList.add("active");
  if (okBtn) {
    okBtn.disabled = false;
    setTimeout(function() { okBtn.focus(); }, 50);
  }
}

function closeConfirm() {
  var ov = document.getElementById("confirm-overlay");
  if (ov) ov.classList.remove("active");
  _confirmCb = null;
}

function _confirmOk() {
  var okBtn = document.getElementById("confirm-ok");
  if (okBtn) okBtn.disabled = true;
  var cb = _confirmCb;
  if (typeof cb !== "function") { closeConfirm(); return; }
  Promise.resolve().then(function() { return cb(); }).finally(closeConfirm);
}

function showToast(msg, type) {
  var el = document.getElementById("app-toast");
  if (!el) return;
  if (_toastTimer) clearTimeout(_toastTimer);
  el.textContent = msg;
  el.className = "app-toast visible " + (type === "error" ? "toast-error" : "toast-success");
  _toastTimer = setTimeout(function() { el.classList.remove("visible"); }, 3000);
}

document.addEventListener("DOMContentLoaded", function() {
  var cancelBtn = document.getElementById("confirm-cancel");
  var okBtn = document.getElementById("confirm-ok");
  var ov = document.getElementById("confirm-overlay");
  if (cancelBtn) cancelBtn.addEventListener("click", closeConfirm);
  if (okBtn) okBtn.addEventListener("click", _confirmOk);
  if (ov) ov.addEventListener("click", function(e) { if (e.target === ov) closeConfirm(); });
  document.addEventListener("keydown", function(e) {
    if (e.key === "Escape" && ov && ov.classList.contains("active")) {
      e.stopPropagation();
      closeConfirm();
    }
  });
});

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

