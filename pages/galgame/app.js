const bridge = window.AstrBotPluginPage;

let sessionId = null;
let currentEmotion = "neutral";
let spriteMode = "single";
let ttsProvider = "";
let rapidThreshold = 5;
let rapidWindowMs = 3000;
let expressions = {};
let layers = {};
let characterName = "小星";
let backgroundFile = "";

let typewriterTimer = null;
let mouthTimer = null;
let isAudioPlaying = false;

const spriteCache = {};

const PLUGIN_NAME = "astrbot_plugin_galgame_web";

/* ---- DOM refs ---- */
const el = {
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

/* ---- util ---- */
function assetUrl(filename) {
  if (!filename) return "";
  if (spriteCache[filename]) return spriteCache[filename];
  return "./assets/" + filename;
}

function collectFileNames() {
  const names = [];
  const add = function (v) { if (v && names.indexOf(v) === -1) names.push(v); };

  for (var k in expressions) { add(expressions[k]); }
  for (var k in layers) { add(layers[k]); }
  add(backgroundFile);

  return names;
}

async function loadAssets() {
  const names = collectFileNames();
  if (names.length === 0) return;

  try {
    const resp = await bridge.apiPost("assets/batch", { names: names });
    const files = resp.files || [];
    for (var i = 0; i < files.length; i++) {
      spriteCache[files[i].name] = files[i].data;
    }
  } catch (e) {
    console.warn("Failed to load assets:", e);
  }
}

/* ---- init ---- */
async function init() {
  try {
    if (!bridge || !bridge.ready) {
      el.dialogText.textContent = "Bridge 未加载，请刷新页面。";
      return;
    }
    await bridge.ready();
  } catch (err) {
    console.error("Bridge ready failed:", err);
    el.dialogText.textContent = "Bridge 初始化失败，请刷新页面。";
    return;
  }

  try {
    const config = await bridge.apiGet("config");
    applyConfig(config);
  } catch (err) {
    console.warn("Failed to load config, using defaults:", err);
    applyConfig({});
  }

  await loadAssets();
  applyBackground();

  let savedId = "";
  try { savedId = localStorage.getItem("galgame_session_id") || ""; } catch (_) { /* sandboxed iframe */ }
  try {
    const resp = await bridge.apiPost("session/init", { resume_id: savedId });
    if (!resp || !resp.session_id) {
      console.error("session/init returned:", resp);
      el.dialogText.textContent = "会话初始化失败(无session_id)，请刷新页面。";
    } else {
      sessionId = resp.session_id;
      try { localStorage.setItem("galgame_session_id", sessionId); } catch (_) { /* sandboxed iframe */ }
      subscribeSSE();
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
  const src = assetUrl(expressions[emotion] || expressions["neutral"]);
  if (!src) return;
  const img = new Image();
  img.onload = function () {
    el.layerHead.src = src;
    el.layerHead.classList.remove("switching");
  };
  el.layerHead.classList.add("switching");
  img.src = src;
}

function loadExpressionToSingle(emotion) {
  const src = assetUrl(expressions[emotion] || expressions["neutral"]);
  if (!src) return;
  const img = new Image();
  img.onload = function () {
    el.spriteSingleImg.src = src;
    el.spriteSingleImg.classList.remove("switching");
  };
  el.spriteSingleImg.classList.add("switching");
  img.src = src;
}

/* ---- SSE ---- */

let sseSubId = null;
let sseRetries = 0;
const SSE_MAX_RETRIES = 5;

async function subscribeSSE() {
  if (sseSubId) {
    await bridge.unsubscribeSSE(sseSubId);
  }
  sseSubId = await bridge.subscribeSSE(
    "stream",
    {
      onMessage(event) {
        sseRetries = 0;
        const msg = event.parsed;
        if (!msg) return;
        switch (msg.type) {
          case "emotion":
            switchExpression(msg.value);
            break;
          case "text":
            typewriterAppend(msg.value);
            break;
          case "audio":
            playTTSAudio(msg.value);
            break;
          case "end":
            finishResponse();
            break;
          case "error":
            showError(msg.message);
            break;
        }
      },
      onError() {
        console.warn("SSE connection error, will retry...");
        sseRetries++;
        if (sseRetries <= SSE_MAX_RETRIES) {
          setTimeout(subscribeSSE, 3000);
        } else {
          el.dialogText.textContent = "连接已断开，请刷新页面。";
        }
      },
    },
    { session_id: sessionId },
  );
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
  const elText = el.dialogText;
  if (typewriterTimer) {
    var cur = elText.querySelector(".cursor");
    if (cur) cur.remove();
    clearTimeout(typewriterTimer);
    typewriterTimer = null;
  }

  const baseText = elText.textContent.replace(/█$/, "");
  let i = 0;
  function tick() {
    if (i < text.length) {
      i++;
      elText.textContent = baseText + text.substring(0, i);
      typewriterTimer = setTimeout(tick, 60);
    } else {
      typewriterTimer = null;
      const cursor = document.createElement("span");
      cursor.className = "cursor";
      elText.appendChild(cursor);
    }
  }
  tick();
}

/* ---- TTS audio ---- */

function playTTSAudio(base64data) {
  if (!base64data) return;

  const audio = el.ttsAudio;
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

  let open = true;
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
  const elText = el.dialogText;
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
  const text = el.userInput.value.trim();
  if (!text || !sessionId) return;

  el.userInput.value = "";
  disableInput();

  try {
    await bridge.apiPost("send", {
      session_id: sessionId,
      text: text,
    });
  } catch (err) {
    console.error("Send failed:", err);
    showError("发送失败，请重试。");
  }
}

/* ---- rapid click / keyboard detection ---- */

function setupRapidDetection() {
  let clickTimestamps = [];
  let keyTimestamps = [];

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
    const now = Date.now();
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
    await bridge.apiPost("rapid_action", {
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
