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

var typewriterTimer = null;
var mouthTimer = null;
var isAudioPlaying = false;

/* ---- DOM refs ---- */
var el = {
  bg: document.getElementById("background"),
  spriteContainer: document.getElementById("sprite-container"),
  spriteSingle: document.getElementById("sprite-single"),
  spriteSingleImg: document.getElementById("sprite-single-img"),
  layerBody: document.getElementById("layer-body"),
  layerHairBack: document.getElementById("layer-hair-back"),
  layerHead: document.getElementById("layer-head"),
  layerHairFront: document.getElementById("layer-hair-front"),
  layerMouth: document.getElementById("layer-mouth"),
  layerOrb: document.getElementById("layer-orb"),
  dialogText: document.getElementById("dialog-text"),
  characterName: document.getElementById("character-name"),
  userInput: document.getElementById("user-input"),
  sendBtn: document.getElementById("send-btn"),
  ttsAudio: document.getElementById("tts-audio"),
  historyPanel: document.getElementById("history-panel"),
  historyList: document.getElementById("history-list"),
};

/* ---- API helpers ---- */

function apiGet(endpoint, params) {
  var url = API_BASE + "/" + endpoint;
  if (params) {
    url += "?" + new URLSearchParams(params).toString();
  }
  return fetch(url).then(function (r) {
    if (!r.ok) throw new Error(endpoint + " returned " + r.status);
    return r.json();
  });
}

function apiPost(endpoint, body) {
  return fetch(API_BASE + "/" + endpoint, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  }).then(function (r) {
    if (!r.ok) throw new Error(endpoint + " returned " + r.status);
    return r.json();
  });
}

function assetUrl(filename) {
  if (!filename) return "";
  return "./assets/" + filename;
}

/* ---- init ---- */

async function init() {
  try {
    var config = await apiGet("config");
    applyConfig(config);
  } catch (err) {
    console.warn("Failed to load config, using defaults:", err);
    applyConfig({});
  }

  applyBackground();

  var savedId = localStorage.getItem("galgame_session_id") || "";
  try {
    var resp = await apiPost("session/init", { resume_id: savedId });
    if (!resp || !resp.session_id) {
      console.error("session/init returned:", resp);
      el.dialogText.textContent = "会话初始化失败(无session_id)，请刷新页面。";
    } else {
      sessionId = resp.session_id;
      localStorage.setItem("galgame_session_id", sessionId);
    }
  } catch (err) {
    console.error("Failed to init session:", err);
    el.dialogText.textContent = "初始化失败(" + (err.message || err) + ")，请刷新页面。";
  }

  setupInput();
  setupRapidDetection();
  applySprites();
}

function applyConfig(cfg) {
  spriteMode = cfg.sprite_mode || "single";
  rapidThreshold = cfg.rapid_click_threshold || 5;
  rapidWindowMs = (cfg.rapid_window_seconds || 3) * 1000;
  ttsProvider = cfg.tts_provider || "";
  expressions = cfg.expressions || {};
  layers = cfg.layers || {};
  characterName = cfg.character_name || "小星";
  backgroundFile = cfg.background || "";
  el.characterName.textContent = characterName;
  document.documentElement.style.setProperty("--sprite-scale", cfg.sprite_scale || 1);
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

function applySprites() {
  if (spriteMode === "layered") {
    el.spriteContainer.classList.add("active");
    el.spriteSingle.classList.remove("active");
    el.layerBody.src = assetUrl(layers.body);
    el.layerHairBack.src = assetUrl(layers.hair_back);
    el.layerHairFront.src = assetUrl(layers.hair_front);
    el.layerMouth.src = assetUrl(layers.mouth_closed);
    el.layerOrb.src = assetUrl(layers.orb);
    if (layers.mouth_open || layers.mouth_closed) {
      el.layerMouth.classList.add("visible");
    }
    loadExpressionToLayer(currentEmotion);
  } else {
    el.spriteContainer.classList.remove("active");
    el.spriteSingle.classList.add("active");
    loadExpressionToSingle(currentEmotion);
  }
}

function loadExpressionToLayer(emotion) {
  var src = assetUrl(expressions[emotion] || expressions["neutral"]);
  if (!src) return;
  var img = new Image();
  img.onload = function () {
    el.layerHead.src = src;
    el.layerHead.classList.remove("switching");
  };
  el.layerHead.classList.add("switching");
  img.src = src;
}

function loadExpressionToSingle(emotion) {
  var src = assetUrl(expressions[emotion] || expressions["neutral"]);
  if (!src) return;
  var img = new Image();
  img.onload = function () {
    el.spriteSingleImg.src = src;
    el.spriteSingleImg.classList.remove("switching");
  };
  el.spriteSingleImg.classList.add("switching");
  img.src = src;
}

/* ---- expression ---- */

function switchExpression(emotion) {
  if (!emotion || emotion === currentEmotion) return;
  currentEmotion = emotion;
  if (spriteMode === "layered") {
    loadExpressionToLayer(emotion);
  } else {
    loadExpressionToSingle(emotion);
  }
}

/* ---- typewriter ---- */

function typewriterAppend(text) {
  var elText = el.dialogText;
  if (typewriterTimer) {
    var cur = elText.querySelector(".cursor");
    if (cur) cur.remove();
    clearTimeout(typewriterTimer);
    typewriterTimer = null;
  }

  var baseText = elText.textContent.replace(/█$/, "");
  var i = 0;
  function tick() {
    if (i < text.length) {
      i++;
      elText.textContent = baseText + text.substring(0, i);
      typewriterTimer = setTimeout(tick, 60);
    } else {
      typewriterTimer = null;
      var cursor = document.createElement("span");
      cursor.className = "cursor";
      elText.appendChild(cursor);
    }
  }
  tick();
}

/* ---- TTS audio ---- */

function playTTSAudio(base64data) {
  if (!base64data) return;

  var audio = el.ttsAudio;
  audio.src = "data:audio/wav;base64," + base64data;

  audio.onplay = function () {
    isAudioPlaying = true;
    startMouthAnimation();
  };
  audio.onended = function () {
    isAudioPlaying = false;
    stopMouthAnimation();
  };
  audio.onerror = function () {
    isAudioPlaying = false;
    stopMouthAnimation();
  };

  audio.play().catch(function (e) {
    console.warn("Audio play failed:", e);
  });
}

/* ---- mouth animation ---- */

function startMouthAnimation() {
  if (spriteMode !== "layered") return;
  if (!layers.mouth_open || !layers.mouth_closed) return;

  var open = true;
  el.layerMouth.classList.add("speaking");
  el.layerMouth.classList.add("visible");
  mouthTimer = setInterval(function () {
    el.layerMouth.src = assetUrl(open ? layers.mouth_open : layers.mouth_closed);
    open = !open;
  }, 180);
}

function stopMouthAnimation() {
  if (mouthTimer) {
    clearInterval(mouthTimer);
    mouthTimer = null;
  }
  el.layerMouth.classList.remove("speaking");
  if (layers.mouth_closed) {
    el.layerMouth.src = assetUrl(layers.mouth_closed);
  }
}

/* ---- response lifecycle ---- */

function finishResponse() {
  stopMouthAnimation();
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
  el.dialogText.textContent = "";
}

function enableInput() {
  el.userInput.disabled = false;
  el.sendBtn.disabled = false;
  el.userInput.focus();
}

/* ---- input handling ---- */

function setupInput() {
  el.sendBtn.addEventListener("click", sendMessage);
  el.userInput.addEventListener("keydown", function (e) {
    if (e.key === "Enter") {
      e.preventDefault();
      sendMessage();
    }
  });
}

async function sendMessage() {
  var text = el.userInput.value.trim();
  if (!text || !sessionId) return;

  el.userInput.value = "";
  disableInput();

  try {
    var resp = await apiPost("send", {
      session_id: sessionId,
      text: text,
    });
    if (resp.reply) {
      switchExpression(resp.emotion || "neutral");
      typewriterAppend(resp.reply);
      finishResponse();
    } else if (resp.error) {
      showError(resp.error);
    }
  } catch (err) {
    console.error("Send failed:", err);
    showError("发送失败，请重试。");
  }
}

/* ---- history ---- */

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
      row.appendChild(bubble);

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
  } catch (err) {
    console.warn("Rapid action notify failed:", err);
  }
}

/* ---- boot ---- */

init();

window.addEventListener("beforeunload", function () {
  if (typewriterTimer) clearTimeout(typewriterTimer);
  if (mouthTimer) clearInterval(mouthTimer);
});
