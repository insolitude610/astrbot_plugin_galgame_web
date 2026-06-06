const PLUGIN_NAME = "astrbot_plugin_galgame_web";
const API_BASE = "/api/plug/" + PLUGIN_NAME;

var sessionId = null;
var currentEmotion = "neutral";
var spriteMode = "single";
var ttsProvider = "";
var rapidThreshold = 5;
var rapidWindowMs = 3000;
var expressions = {};
var layers = {};
var characterName = "小星";
var backgroundFile = "";
var historyAvatar = "";
var voiceVolume = 1.0;
var bgmVolume = 0.5;
var bgmStarted = false;
var historyLimit = 40;
var _assetCache = {};

var _memStore = {};
function getLocal(key) {
  try { return localStorage.getItem(key); } catch (e) { return _memStore[key] || null; }
}
function setLocal(key, val) {
  try { localStorage.setItem(key, val); } catch (e) { _memStore[key] = val; }
}
function removeLocal(key) {
  try { localStorage.removeItem(key); } catch (e) { delete _memStore[key]; }
}

var typewriterTimer = null;
var typewriterSpeed = 60;
var typewriterFullText = "";
var typewriterLastEmotion = "";
var isAudioPlaying = false;
var lastReplyData = null;
var expressionTimers = [];

function clearExpressionTimers() {
  for (var t = 0; t < expressionTimers.length; t++) clearTimeout(expressionTimers[t]);
  expressionTimers = [];
}

function scheduleExpressionTimers(emotionList, totalChars, audioDuration) {
  clearExpressionTimers();
  for (var i = 0; i < emotionList.length; i++) {
    var emo = emotionList[i][0];
    var pos = emotionList[i][1];
    var delay = (pos / totalChars) * audioDuration * 1000;
    expressionTimers.push(setTimeout((function(e) {
      return function() { switchExpression(e); };
    })(emo), delay));
  }
}

/* ---- VRM 3D renderer ---- */
var vrmModule = null;
var vrmStarted = false;
var vrmModelPath = "";
var expressionsBlink = {};
var currentExpr = "neutral";

function startVRMRender() {
  var container = document.getElementById("vrm-container");
  if (!container || !vrmModule) return;
  vrmStarted = true;
  vrmModule.startVRM(container, vrmModelPath).then(function() {
    if (currentEmotion !== "neutral") vrmModule.setVRMExpression(currentEmotion);
  });
}

function stopVRMRender() {
  vrmStarted = false;
  if (vrmModule) vrmModule.stopVRM();
}

function vrmSwitchExpression(emotion) {
  if (vrmModule && vrmStarted) vrmModule.setVRMExpression(emotion);
}

/* ---- voice recording ---- */

var audioCtx = null;
var mediaStream = null;
var scriptNode = null;
var pcmChunks = [];
var SAMPLE_RATE = 16000;

function pcmToWavBlob(pcm, rate) {
  var totalLen = 0;
  for (var i = 0; i < pcm.length; i++) totalLen += pcm[i].length;
  var flat = new Float32Array(totalLen);
  var off = 0;
  for (var i = 0; i < pcm.length; i++) {
    flat.set(pcm[i], off);
    off += pcm[i].length;
  }

  var buffer = new ArrayBuffer(44 + totalLen * 2);
  var view = new DataView(buffer);

  function wstr(off, s) {
    for (var i = 0; i < s.length; i++) view.setUint8(off + i, s.charCodeAt(i));
  }

  wstr(0, "RIFF");
  view.setUint32(4, 36 + totalLen * 2, true);
  wstr(8, "WAVE");
  wstr(12, "fmt ");
  view.setUint32(16, 16, true);
  view.setUint16(20, 1, true);
  view.setUint16(22, 1, true);
  view.setUint32(24, rate, true);
  view.setUint32(28, rate * 2, true);
  view.setUint16(32, 2, true);
  view.setUint16(34, 16, true);
  wstr(36, "data");
  view.setUint32(40, totalLen * 2, true);

  for (var i = 0; i < totalLen; i++) {
    var s = Math.max(-32768, Math.min(32767, Math.round(flat[i] * 32767)));
    view.setInt16(44 + i * 2, s, true);
  }

  console.log("[audio-debug] WAV samples=" + totalLen + " sampleRate=" + rate + " duration=" + (totalLen / rate).toFixed(2) + "s bytes=" + (44 + totalLen * 2));
  return new Blob([buffer], { type: "audio/wav" });
}

async function toggleRecording() {
  if (audioCtx && audioCtx.state !== "closed") {
    scriptNode.disconnect();
    mediaStream.getTracks().forEach(function (t) { t.stop(); });
    audioCtx.close();
    audioCtx = null;
    var blob = pcmToWavBlob(pcmChunks, SAMPLE_RATE);
    var reader = new FileReader();
    reader.onload = function () { sendMessage(reader.result); };
    reader.readAsDataURL(blob);
    el.micBtn.classList.remove("recording");
  } else {
    try {
      mediaStream = await navigator.mediaDevices.getUserMedia({ audio: true });
      audioCtx = new AudioContext({ sampleRate: SAMPLE_RATE });
      var source = audioCtx.createMediaStreamSource(mediaStream);
      scriptNode = audioCtx.createScriptProcessor(4096, 1, 1);
      pcmChunks = [];
      scriptNode.onaudioprocess = function (e) {
        var input = e.inputBuffer.getChannelData(0);
        var buf = new Float32Array(input.length);
        buf.set(input);
        pcmChunks.push(buf);
      };
      source.connect(scriptNode);
      scriptNode.connect(audioCtx.destination);
      el.micBtn.classList.add("recording");
    } catch (err) {
      console.warn("Microphone access denied:", err);
      showError("无法访问麦克风，请确认浏览器已授予录音权限");
    }
  }
}

/* ---- DOM refs ---- */
var el = {
  bg: document.getElementById("background"),
  spriteContainer: document.getElementById("sprite-container"),
  vrmContainer: document.getElementById("vrm-container"),
  spriteSingle: document.getElementById("sprite-single"),
  spriteFaceA: document.getElementById("sprite-face-a"),
  spriteFaceB: document.getElementById("sprite-face-b"),
  dialogText: document.getElementById("dialog-text"),
  characterName: document.getElementById("character-name"),
  userInput: document.getElementById("user-input"),
  sendBtn: document.getElementById("send-btn"),
  ttsAudio: document.getElementById("tts-audio"),
  historyPanel: document.getElementById("history-panel"),
  historyList: document.getElementById("history-list"),
  micBtn: document.getElementById("mic-btn"),
};

/* ---- API helpers ---- */

function apiGet(endpoint, params) {
  if (window.AstrBotPluginPage && window.AstrBotPluginPage.apiGet) {
    return window.AstrBotPluginPage.apiGet(endpoint, params);
  }
  var url = API_BASE + "/" + endpoint;
  if (params) {
    url += "?" + new URLSearchParams(params).toString();
  }
  return fetch(url, { credentials: "include" }).then(function (r) {
    if (!r.ok) throw new Error(endpoint + " returned " + r.status);
    return r.json();
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
  }).then(function (r) {
    if (!r.ok) throw new Error(endpoint + " returned " + r.status);
    return r.json();
  });
}

function assetUrl(filename) {
  if (!filename) return "";
  if (_assetCache[filename]) return _assetCache[filename];
  return "/api/plug/astrbot_plugin_galgame_web/assets/file?name=" + encodeURIComponent(filename);
}

/* ---- init ---- */

function restoreLastMessage() {
  if (!sessionId) return;
  apiGet("history", { session_id: sessionId }).then(function(data) {
    var msgs = data.messages || [];
    for (var i = msgs.length - 1; i >= 0; i--) {
      if (msgs[i].role === "assistant") {
        el.dialogText.textContent = msgs[i].content;
        var cursor = document.createElement("span");
        cursor.className = "cursor";
        el.dialogText.appendChild(cursor);
        return;
      }
    }
  }).catch(function(e) {
    console.warn("restoreLastMessage failed:", e);
  });
}

function getUrlSessionId() {
  var m = location.search.match(/[?&]sid=([a-f0-9]+)/i);
  return m ? m[1] : "";
}

function toggleSessionPanel() {
  var panel = document.getElementById("session-panel");
  if (panel.classList.contains("active")) {
    panel.classList.remove("active");
    return;
  }
  loadSessionPanel();
}

function switchToSession(sid) {
  toggleSessionPanel();
  initSession(sid).then(function(resp) {
    if (!resp) return;
    sessionId = resp.session_id;
    setLocal("galgame_session_id", sessionId);
    if (resp.current_emotion) { currentEmotion = resp.current_emotion; }
    finishInit(true);
  });
}

function startNewSession() {
  toggleSessionPanel();
  removeLocal("galgame_session_id");
  apiPost("session/init", { resume_id: "" }).then(function(resp) {
    if (!resp || !resp.session_id) return;
    sessionId = resp.session_id;
    setLocal("galgame_session_id", sessionId);
    finishInit(true);
  });
}

async function loadSessionPanel() {
  var listEl = document.getElementById("session-list");
  listEl.innerHTML = '<div class="session-loading">正在查找历史对话...</div>';
  document.getElementById("session-panel").classList.add("active");

  var sessions;
  try {
    var data = await apiGet("session/list");
    sessions = data.sessions || [];
  } catch (err) {
    console.warn("Failed to list sessions:", err);
    sessions = [];
  }

  listEl.innerHTML = "";
  if (!sessions.length) {
    listEl.innerHTML = '<div class="session-loading">暂无历史对话</div>';
    return;
  }

  for (var i = 0; i < sessions.length; i++) {
    var s = sessions[i];
    var d = new Date(s.created_at * 1000);
    var dateStr = d.getFullYear() + "-" +
      String(d.getMonth() + 1).padStart(2, "0") + "-" +
      String(d.getDate()).padStart(2, "0") + " " +
      String(d.getHours()).padStart(2, "0") + ":" +
      String(d.getMinutes()).padStart(2, "0");
    var preview = s.last_message || "(暂无对话)";
    var item = document.createElement("div");
    item.className = "session-item";
    item.onclick = (function(sid) {
      return function() { switchToSession(sid); };
    })(s.session_id);
    item.innerHTML =
      '<div class="session-item-time">' + dateStr + '</div>' +
      '<div class="session-item-preview">' + preview + '</div>' +
      '<span class="session-item-count">' + s.message_count + ' 条消息</span>';

    var delBtn = document.createElement("button");
    delBtn.className = "session-item-del";
    delBtn.title = "删除此对话";
    delBtn.innerHTML = '<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><line x1="18" y1="6" x2="6" y2="18"/><line x1="6" y1="6" x2="18" y2="18"/></svg>';
    delBtn.onclick = (function(sid, el) {
      return async function(e) {
        e.stopPropagation();
        if (!confirm("确认删除此对话？")) return;
        try {
          await apiPost("session/delete", { session_id: sid });
          if (sid === sessionId) {
  removeLocal("galgame_session_id");
            location.href = location.pathname;
          } else {
            el.remove();
          }
        } catch(e2) {
          console.warn("Delete session failed:", e2);
        }
      };
    })(s.session_id, item);
    item.appendChild(delBtn);

    listEl.appendChild(item);
  }
}

async function initSession(resumeId) {
  var resp;
  try {
    resp = await apiPost("session/init", { resume_id: resumeId || "" });
  } catch (err) {
    console.error("Failed to init session:", err);
    el.dialogText.textContent = "初始化失败(" + (err.message || err) + ")，请刷新页面。";
    return null;
  }
  if (!resp || !resp.session_id) {
    console.error("session/init returned:", resp);
    el.dialogText.textContent = "会话初始化失败，请刷新页面。";
    return null;
  }
  return resp;
}

function finishInit(isResuming) {
  if (!sessionId) return;
  setupInput();
  setupRapidDetection();
  applySprites();
  document.getElementById("dialog-box").addEventListener("click", skipTypewriter);
  if (spriteMode === "vrm") {
    import("./vrm.js").then(function(m) { vrmModule = m; startVRMRender(); });
  }
  if (isResuming) {
    restoreLastMessage();
  }
}

function init() {
  var cachedBg = getLocal("galgame_bg") || "";
  if (cachedBg) {
    el.bg.style.backgroundImage = "url(" + assetUrl(cachedBg) + ")";
  }

  apiGet("config").then(function(config) {
    applyConfig(config);
    return preloadAssets(config);
  }).catch(function(err) {
    console.warn("Failed to load config, using defaults:", err);
    applyConfig({});
  }).then(function() {
    applyBackground();

    var urlSid = getUrlSessionId();
    var savedId = urlSid || getLocal("galgame_session_id") || "";

    return initSession(savedId).then(function(resp) {
      if (!resp) return;
      sessionId = resp.session_id;
      setLocal("galgame_session_id", sessionId);
      if (resp.current_emotion) {
        currentEmotion = resp.current_emotion;
      }
      finishInit(true);
    });
  });
}

function applyConfig(cfg) {
  spriteMode = cfg.sprite_mode || "single";
  rapidThreshold = cfg.rapid_click_threshold || 5;
  rapidWindowMs = (cfg.rapid_window_seconds || 3) * 1000;
  ttsProvider = cfg.tts_provider || "";
  expressions = cfg.expressions || {};
  expressionsBlink = cfg.expressions_blink || {};
  layers = cfg.layers || {};
  vrmModelPath = cfg.vrm_model || "";
  if (!vrmModelPath) vrmModelPath = "./assets/model.vrm";
  characterName = cfg.character_name || "小星";
  backgroundFile = cfg.background || "";
  if (backgroundFile) setLocal("galgame_bg", backgroundFile);
  historyAvatar = cfg.history_avatar || "";
  el.characterName.textContent = characterName;
  document.documentElement.style.setProperty("--sprite-scale", cfg.sprite_scale || 1);
  document.documentElement.style.setProperty("--sprite-bottom", cfg.sprite_bottom != null ? cfg.sprite_bottom : 28);
  document.documentElement.style.setProperty("--sprite-left", cfg.sprite_left != null ? cfg.sprite_left : 50);
  typewriterSpeed = cfg.typewriter_speed || 60;
  historyLimit = cfg.history_limit || 40;

  var webPort = cfg.web_port || 6186;
  var webEnabled = cfg.web_enabled !== false;
  var baseUrl = "http://localhost:" + webPort;
  var setLink = document.getElementById("settings-link");
  if (setLink) {
    if (webEnabled && webPort > 0) setLink.href = baseUrl + "/settings.html";
    else setLink.style.display = "none";
  }
  var favLink = document.getElementById("favorites-link");
  if (favLink) {
    if (webEnabled && webPort > 0) favLink.href = baseUrl + "/favorites.html";
    else favLink.style.display = "none";
  }

  applyBgmAndVolume(cfg);
}

function preloadAssets(cfg) {
  var names = [];
  var exps = cfg.expressions || {};
  for (var k in exps) { if (exps[k]) names.push(exps[k]); }
  if (cfg.background) names.push(cfg.background);
  if (cfg.history_avatar) names.push(cfg.history_avatar);
  if (!names.length) return Promise.resolve();
  return apiPost("assets/batch", { names: names }).then(function(resp) {
    (resp.files || []).forEach(function(f) { _assetCache[f.name] = f.data; });
  }).catch(function(e) {
    console.warn("preloadAssets failed:", e);
  });
}

function applyBgmAndVolume(cfg) {
  var bgmFile = cfg.bgm_file || "";
  var bgmVol = cfg.bgm_volume != null ? cfg.bgm_volume : 0.5;
  var voiceVol = cfg.voice_volume != null ? cfg.voice_volume : 1.0;

  voiceVolume = voiceVol;
  bgmVolume = bgmVol;

  var ttsAudio = document.getElementById("tts-audio");
  var bgmAudio = document.getElementById("bgm-audio");
  if (ttsAudio) ttsAudio.volume = voiceVol;
  if (bgmAudio) {
    bgmAudio.volume = bgmVol;
    if (bgmFile) {
      bgmAudio.src = "./bgm/" + encodeURIComponent(bgmFile);
      startBgmOnInteraction(bgmAudio);
    }
  }
}

function startBgmOnInteraction(bgmAudio) {
  if (bgmStarted) return;
  function tryPlay() {
    if (bgmStarted) return;
    bgmStarted = true;
    document.removeEventListener("click", tryPlay);
    document.removeEventListener("keydown", tryPlay);
    bgmAudio.play().catch(function(e) { console.warn("BGM autoplay blocked:", e); });
  }
  document.addEventListener("click", tryPlay, { once: true });
  document.addEventListener("keydown", tryPlay, { once: true });
}

function applyBackground() {
  if (backgroundFile) {
    el.bg.style.backgroundImage = "url(" + assetUrl(backgroundFile) + ")";
    analyzeBgColor();
  }
}

function analyzeBgColor() {
  var img = new Image();
  img.crossOrigin = "anonymous";
  img.onload = function () {
    var canvas = document.createElement("canvas");
    var size = 80;
    canvas.width = size;
    canvas.height = size;
    var ctx = canvas.getContext("2d");
    ctx.drawImage(img, 0, 0, size, size);
    var data = ctx.getImageData(0, 0, size, size).data;

    var r = 0, g = 0, b = 0, count = 0;
    for (var i = 0; i < data.length; i += 16) {
      r += data[i];
      g += data[i + 1];
      b += data[i + 2];
      count++;
    }
    r = Math.round(r / count);
    g = Math.round(g / count);
    b = Math.round(b / count);

    // Convert to HSL, shift hue towards warm if too cool
    var hsl = rgbToHsl(r, g, b);
    var hue = hsl[0];
    // Push cool blues/greens towards warm amber/gold
    if (hue > 180 && hue < 300) hue = (hue + 80) % 360;
    var sat = Math.min(hsl[1] * 1.3, 0.55);
    applyHistoryPalette(hue, sat);
  };
  img.src = assetUrl(backgroundFile);
}

function rgbToHsl(r, g, b) {
  r /= 255; g /= 255; b /= 255;
  var max = Math.max(r, g, b), min = Math.min(r, g, b);
  var h, s, l = (max + min) / 2;
  if (max === min) { h = s = 0; }
  else {
    var d = max - min;
    s = l > 0.5 ? d / (2 - max - min) : d / (max + min);
    switch (max) {
      case r: h = ((g - b) / d + (g < b ? 6 : 0)) / 6; break;
      case g: h = ((b - r) / d + 2) / 6; break;
      case b: h = ((r - g) / d + 4) / 6; break;
    }
  }
  return [h * 360, s, l];
}

function hslToRgba(h, s, l, a) {
  h /= 360;
  var r, g, b;
  if (s === 0) { r = g = b = l; }
  else {
    var q = l < 0.5 ? l * (1 + s) : l + s - l * s;
    var p = 2 * l - q;
    r = hue2rgb(p, q, h + 1/3);
    g = hue2rgb(p, q, h);
    b = hue2rgb(p, q, h - 1/3);
  }
  return "rgba(" + Math.round(r*255) + "," + Math.round(g*255) + "," + Math.round(b*255) + "," + a + ")";
}
function hue2rgb(p, q, t) {
  if (t < 0) t += 1; if (t > 1) t -= 1;
  if (t < 1/6) return p + (q - p) * 6 * t;
  if (t < 1/2) return q;
  if (t < 2/3) return p + (q - p) * (2/3 - t) * 6;
  return p;
}

function applyHistoryPalette(hue, sat) {
  var root = document.documentElement.style;

  root.setProperty("--history-bg", hslToRgba(hue, sat * 0.35, 0.22, 0.92));
  root.setProperty("--history-border", hslToRgba(hue, sat * 0.5, 0.32, 0.18));
  root.setProperty("--history-title", hslToRgba(hue, sat * 0.12, 0.88, 0.88));
  root.setProperty("--history-close", hslToRgba(hue, sat * 0.08, 0.72, 0.55));
  root.setProperty("--history-close-hover", hslToRgba(hue, sat * 0.12, 0.88, 0.90));
  root.setProperty("--history-header-border", hslToRgba(hue, sat * 0.2, 0.28, 0.12));
  root.setProperty("--history-scrollbar", hslToRgba(hue, sat * 0.25, 0.38, 0.15));
  root.setProperty("--history-shadow", hslToRgba(hue, sat * 0.3, 0.12, 0.05));

  root.setProperty("--history-ai-tag", hslToRgba(hue, sat * 0.45, 0.78, 1));
  root.setProperty("--history-user-tag", hslToRgba(hue, sat * 0.18, 0.72, 1));

  root.setProperty("--history-ai-bubble-bg", hslToRgba(hue, sat * 0.35, 0.28, 0.22));
  root.setProperty("--history-ai-bubble-border", hslToRgba(hue, sat * 0.4, 0.34, 0.35));
  root.setProperty("--history-ai-bubble-text", hslToRgba(hue, sat * 0.1, 0.90, 1));

  root.setProperty("--history-user-bubble-bg", hslToRgba(hue, sat * 0.22, 0.24, 0.18));
  root.setProperty("--history-user-bubble-border", hslToRgba(hue, sat * 0.28, 0.30, 0.30));
  root.setProperty("--history-user-bubble-text", hslToRgba(hue, sat * 0.08, 0.85, 1));

  root.setProperty("--history-overlay", hslToRgba(hue, sat * 0.15, 0.18, 0.65));
  root.setProperty("--history-overlay-bg", "linear-gradient(" + hslToRgba(hue, sat * 0.18, 0.22, 0.68) + "," + hslToRgba(hue, sat * 0.15, 0.16, 0.65) + "), var(--history-bg-img)");
}

function safeImg(el, src) {
  if (src) { el.src = src; el.style.display = ""; }
  else { el.src = ""; el.style.display = "none"; }
}

function applySprites() {
  if (spriteMode === "vrm") {
    el.spriteContainer.classList.add("active");
    el.spriteSingle.classList.remove("active");
    if (!vrmStarted) startVRMRender();
  } else {
    stopVRMRender();
    el.spriteContainer.classList.remove("active");
    el.spriteSingle.classList.add("active");
    activeFace = "a";
    el.spriteFaceB.classList.add("hidden");
    var initSrc = assetUrl(expressions[currentEmotion] || expressions["neutral"]);
    if (initSrc) el.spriteFaceA.src = initSrc;
    el.spriteFaceA.classList.remove("hidden");
  }
}

/* ---- expression ---- */

function loadExpressionToSingle(emotion) {
  var src = assetUrl(expressions[emotion] || expressions["neutral"]);
  if (!src) return;
  var hiddenFace = activeFace === "a" ? el.spriteFaceB : el.spriteFaceA;
  var visibleFace = activeFace === "a" ? el.spriteFaceA : el.spriteFaceB;
  var img = new Image();
  img.onload = function () {
    hiddenFace.src = src;
    hiddenFace.classList.remove("hidden");
    visibleFace.classList.add("hidden");
    activeFace = activeFace === "a" ? "b" : "a";
  };
  img.src = src;
}

function switchExpression(emotion) {
  if (!emotion || emotion === currentEmotion) return;
  currentEmotion = emotion;
  if (spriteMode === "vrm") {
    vrmSwitchExpression(emotion);
  } else {
    loadExpressionToSingle(emotion);
  }
}

/* ---- typewriter ---- */

function typewriterAppend(text, emotionMap) {
  clearExpressionTimers();
  var elText = el.dialogText;
  elText.classList.remove("text-reveal");
  if (typewriterTimer) {
    clearTimeout(typewriterTimer);
    typewriterTimer = null;
  }

  emotionMap = emotionMap || {};
  var emotionPositions = Object.keys(emotionMap).map(Number).sort(function(a,b){return a-b;});

  typewriterFullText = text;
  typewriterLastEmotion = emotionPositions.length ? emotionMap[emotionPositions[emotionPositions.length - 1]] : currentEmotion;
  var i = 0;
  function tick() {
    if (i < text.length) {
      i++;
      elText.textContent = text.substring(0, i);
      while (emotionPositions.length && emotionPositions[0] < i) {
        var pos = emotionPositions.shift();
        switchExpression(emotionMap[pos]);
      }
      typewriterTimer = setTimeout(tick, typewriterSpeed);
    } else {
      typewriterTimer = null;
      while (emotionPositions.length) {
        switchExpression(emotionMap[emotionPositions.shift()]);
      }
      var cursor = document.createElement("span");
      cursor.className = "cursor";
      elText.appendChild(cursor);
    }
  }
  tick();
}

/* ---- skip typewriter (click to fast-forward) ---- */

function skipTypewriter(e) {
  if (!typewriterTimer) return;
  if (e && e.target.closest("button")) return;
  clearTimeout(typewriterTimer);
  typewriterTimer = null;
  clearExpressionTimers();
  el.dialogText.textContent = typewriterFullText;
  el.dialogText.classList.add("text-reveal");
  setTimeout(function() { el.dialogText.classList.remove("text-reveal"); }, 200);
  switchExpression(typewriterLastEmotion || currentEmotion);
  var cursor = document.createElement("span");
  cursor.className = "cursor";
  el.dialogText.appendChild(cursor);
}

/* ---- replay ---- */

function replayLastResponse() {
  if (!lastReplyData) return;
  if (typewriterTimer) clearTimeout(typewriterTimer);
  switchExpression(currentEmotion);
  var emotionList = [];
  for (var key in lastReplyData.emotionMap) {
    emotionList.push([lastReplyData.emotionMap[key], parseInt(key)]);
  }
  if (lastReplyData.audio && emotionList.length) {
    typewriterAppend(lastReplyData.text, {});
    var audio = playTTSAudio(lastReplyData.audio, lastReplyData.audioMime);
    if (audio) {
      audio.onloadedmetadata = function() {
        scheduleExpressionTimers(emotionList, lastReplyData.text.length, audio.duration);
      };
      audio.onended = function() { clearExpressionTimers(); };
      audio.onerror = function() { clearExpressionTimers(); };
    }
  } else {
    typewriterAppend(lastReplyData.text, lastReplyData.emotionMap);
    if (lastReplyData.audio) {
      playTTSAudio(lastReplyData.audio, lastReplyData.audioMime);
    }
  }
}

/* ---- favorites ---- */

async function favoriteCurrent() {
  if (!lastReplyData || !lastReplyData.audio_file) return;
  try {
    await apiPost("favorites/add", {
      text: lastReplyData.text,
      audio_file: lastReplyData.audio_file,
      audio_mime: lastReplyData.audioMime,
    });
    var btn = document.getElementById("favorite-btn");
    btn.classList.add("favorited");
    setTimeout(function() { btn.classList.remove("favorited"); }, 600);
  } catch(e) {
    console.warn("Favorite add failed:", e);
  }
}

/* ---- TTS audio ---- */

function playTTSAudio(base64data, mime) {
  if (!base64data) return null;

  var audio = el.ttsAudio;
  var mimeType = mime || "audio/wav";
  audio.src = "data:" + mimeType + ";base64," + base64data;

  audio.onplay = function () {
    isAudioPlaying = true;
  };
  audio.onended = function () {
    isAudioPlaying = false;
  };
  audio.onerror = function () {
    isAudioPlaying = false;
  };

  audio.volume = voiceVolume;
  audio.play().catch(function (e) {
    console.warn("Audio play failed:", e);
  });
  return audio;
}

/* ---- response lifecycle ---- */

function finishResponse() {
  var elText = el.dialogText;
  var cur = elText.querySelector(".cursor");
  if (cur) cur.remove();
  enableInput();
  el.userInput.focus();
}

function showError(msg) {
  el.dialogText.textContent = msg;
  enableInput();
}

function disableInput() {
  el.userInput.disabled = true;
  el.sendBtn.disabled = true;
  el.micBtn.disabled = true;
}

function enableInput() {
  el.userInput.disabled = false;
  el.sendBtn.disabled = false;
  el.micBtn.disabled = false;
  el.userInput.focus();
}

/* ---- input handling ---- */

function setupInput() {
  el.sendBtn.addEventListener("click", function () { sendMessage(); });
  el.micBtn.addEventListener("click", toggleRecording);
  el.userInput.addEventListener("keydown", function (e) {
    if (e.key === "Enter") {
      e.preventDefault();
      sendMessage();
    }
  });
}

async function sendMessage(audioData) {
  var text = el.userInput.value.trim();
  if ((!text && !audioData) || !sessionId) return;

  el.userInput.value = "";
  disableInput();

  var body = { session_id: sessionId, text: text };
  if (audioData) body.audio_data = audioData;

  try {
    var resp = await apiPost("send", body);
    if (resp.reply) {
      var emotionMap = {};
      var emotionList = resp.emotions || [];
      emotionList.forEach(function(e) { emotionMap[e[1]] = e[0]; });
      lastReplyData = { text: resp.reply, emotionMap: emotionMap, audio: resp.audio || "", audioMime: resp.audio_mime || "audio/wav", audio_file: resp.audio_file || "" };
      document.getElementById("replay-btn").classList.add("active");
      if (resp.audio_file) {
        document.getElementById("favorite-btn").classList.add("active");
      } else {
        document.getElementById("favorite-btn").classList.remove("active");
      }
      if (resp.audio && emotionList.length) {
        typewriterAppend(resp.reply, {});
        finishResponse();
        var audio = playTTSAudio(resp.audio, resp.audio_mime || "audio/wav");
        audio.onloadedmetadata = function() {
          scheduleExpressionTimers(emotionList, resp.reply.length, audio.duration);
        };
        audio.onended = function() { clearExpressionTimers(); };
        audio.onerror = function() { clearExpressionTimers(); };
      } else {
        typewriterAppend(resp.reply, emotionMap);
        finishResponse();
        if (resp.audio) {
          playTTSAudio(resp.audio, resp.audio_mime || "audio/wav");
        }
      }
    } else if (resp.error) {
      showError(resp.error);
    } else {
      finishResponse();
    }
  } catch (err) {
    console.error("Send failed:", err);
    showError("发送失败，请重试。");
  }
}

async function toggleHistory() {
  var panel = el.historyPanel;
  if (panel.classList.contains("active")) {
    panel.classList.remove("active");
    return;
  }

  if (!sessionId) return;

  var overlay = document.getElementById("history-overlay");
  if (backgroundFile) {
    overlay.style.setProperty("--history-bg-img", "url(" + assetUrl(backgroundFile) + ")");
    overlay.classList.add("has-bg");
  } else {
    overlay.style.removeProperty("--history-bg-img");
    overlay.classList.remove("has-bg");
  }

  try {
    var data = await apiGet("history", { session_id: sessionId });
    var messages = data.messages || [];
    if (messages.length > historyLimit) {
      messages = messages.slice(messages.length - historyLimit);
    }
    var list = el.historyList;
    list.innerHTML = "";

    for (var i = 0; i < messages.length; i++) {
      var msg = messages[i];
      var isUser = msg.role === "user";

      var row = document.createElement("div");
      row.className = "history-msg " + (isUser ? "user" : "assistant");

      var tag = document.createElement("div");
      tag.className = "msg-tag";
      tag.textContent = isUser ? "你" : characterName;
      row.appendChild(tag);

      var bubble = document.createElement("div");
      bubble.className = "msg-bubble";
      bubble.textContent = msg.content;

      var msgRow = document.createElement("div");
      msgRow.className = "msg-row";
      if (!isUser && historyAvatar) {
        var avatar = document.createElement("img");
        avatar.className = "history-avatar";
        avatar.src = assetUrl(historyAvatar);
        msgRow.appendChild(avatar);
      }
      msgRow.appendChild(bubble);

      if (!isUser && msg.audio_file) {
        var playBtn = document.createElement("button");
        playBtn.className = "msg-play-btn";
        playBtn.title = "播放语音";
        playBtn.innerHTML = '<svg width="14" height="14" viewBox="0 0 24 24" fill="currentColor"><polygon points="5,3 19,12 5,21"/></svg>';
        playBtn.onclick = (function(file) {
          return function() {
            apiGet("audio/data", { name: file }).then(function(resp) {
              var audio = new Audio("data:" + resp.mime + ";base64," + resp.audio);
              audio.play().catch(function(e) { console.warn("History audio play failed:", e); });
            }).catch(function(e) { console.warn("History audio load failed:", e); });
          };
        })(msg.audio_file);
        msgRow.appendChild(playBtn);

        var favBtn = document.createElement("button");
        favBtn.className = "msg-fav-btn";
        favBtn.title = "收藏语音";
        favBtn.innerHTML = '<svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M20.84 4.61a5.5 5.5 0 0 0-7.78 0L12 5.67l-1.06-1.06a5.5 5.5 0 0 0-7.78 7.78l1.06 1.06L12 21.23l7.78-7.78 1.06-1.06a5.5 5.5 0 0 0 0-7.78z"/></svg>';
        favBtn.onclick = (function(m) {
          return async function() {
            try {
              await apiPost("favorites/add", {
                text: m.content,
                audio_file: m.audio_file,
                audio_mime: m.audio_mime || "audio/wav",
              });
              favBtn.style.color = "#ef4444";
            } catch(e) { console.warn("Favorite add failed:", e); }
          };
        })(msg);
        msgRow.appendChild(favBtn);
      }

      row.appendChild(msgRow);

      list.appendChild(row);
    }

    list.scrollTop = list.scrollHeight;
    panel.classList.add("active");
  } catch (err) {
    console.error("Failed to load history:", err);
  }
}

/* ---- rapid click / keyboard detection ---- */

function setupRapidDetection() {
  var clickTimestamps = [];
  var keyTimestamps = [];

  document.addEventListener("click", function (e) {
    if (el.sendBtn.contains(e.target) || e.target === el.userInput) return;
    if (document.getElementById("dialog-box").contains(e.target)) return;
    clickTimestamps = trackTimestamps(clickTimestamps);
    keyTimestamps = [];
  });

  document.addEventListener("keydown", function (e) {
    if (e.target === el.userInput) return;
    keyTimestamps = trackTimestamps(keyTimestamps);
    clickTimestamps = [];
  });

  function trackTimestamps(ts) {
    var now = Date.now();
    ts.push(now);
    ts = ts.filter(function (t) { return now - t < rapidWindowMs; });
    if (ts.length >= rapidThreshold) {
      notifyRapidAction(ts.length);
      return [];
    }
    return ts;
  }
}

async function notifyRapidAction(count) {
  if (!sessionId) return;
  try {
    await apiPost("rapid_action", {
      session_id: sessionId,
      count: count,
    });
    if (!typewriterTimer) {
      disableInput();
      var resp = await apiPost("send", { session_id: sessionId, text: "" });
      if (resp.reply) {
        var emotionMap = {};
        var emotionList = resp.emotions || [];
        emotionList.forEach(function(e) { emotionMap[e[1]] = e[0]; });
        lastReplyData = { text: resp.reply, emotionMap: emotionMap, audio: resp.audio || "", audioMime: resp.audio_mime || "audio/wav", audio_file: resp.audio_file || "" };
        document.getElementById("replay-btn").classList.add("active");
      if (resp.audio_file) {
        document.getElementById("favorite-btn").classList.add("active");
      } else {
        document.getElementById("favorite-btn").classList.remove("active");
      }
        if (resp.audio && emotionList.length) {
          typewriterAppend(resp.reply, {});
          finishResponse();
          var audio = playTTSAudio(resp.audio, resp.audio_mime || "audio/wav");
          if (audio) {
            audio.onloadedmetadata = function() {
              scheduleExpressionTimers(emotionList, resp.reply.length, audio.duration);
            };
            audio.onended = function() { clearExpressionTimers(); };
            audio.onerror = function() { clearExpressionTimers(); };
          }
        } else {
          typewriterAppend(resp.reply, emotionMap);
          finishResponse();
          if (resp.audio) playTTSAudio(resp.audio, resp.audio_mime || "audio/wav");
        }
      }
    }
  } catch (err) {
    console.warn("Rapid action failed:", err);
  }
}

/* ---- boot ---- */

if (window.AstrBotPluginPage) {
  init();
} else {
  var _bgPoll = setInterval(function () {
    if (window.AstrBotPluginPage) {
      clearInterval(_bgPoll);
      init();
    }
  }, 100);
  setTimeout(function () { clearInterval(_bgPoll); }, 10000);
}

window.addEventListener("beforeunload", function () {
  stopVRMRender();
  if (typewriterTimer) clearTimeout(typewriterTimer);
});

document.addEventListener("visibilitychange", function () {
  if (document.hidden) stopVRMRender();
  else if (spriteMode === "vrm" && !vrmStarted) {
    startVRMRender();
  }
});
