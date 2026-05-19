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
  }
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
