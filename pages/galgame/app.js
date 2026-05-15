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

let typewriterTimer = null;
let mouthTimer = null;
let isAudioPlaying = false;

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
  return `./assets/${filename}`;
}

/* ---- init ---- */
async function init() {
  const context = await bridge.ready();

  try {
    const config = await bridge.apiGet("config");
    applyConfig(config);
  } catch (err) {
    console.warn("Failed to load config, using defaults:", err);
    applyConfig({});
  }

  try {
    const resp = await bridge.apiPost("session/init");
    sessionId = resp.session_id;
    subscribeSSE();
  } catch (err) {
    console.error("Failed to init session:", err);
    el.dialogText.textContent = "初始化失败，请刷新页面。";
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
  el.characterName.textContent = characterName;
  const bg = cfg.background || "";
  if (bg) {
    el.bg.style.backgroundImage = `url(${assetUrl(bg)})`;
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
  img.onload = () => {
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
  img.onload = () => {
    el.spriteSingleImg.src = src;
    el.spriteSingleImg.classList.remove("switching");
  };
  el.spriteSingleImg.classList.add("switching");
  img.src = src;
}

/* ---- SSE ---- */

let sseSubId = null;

async function subscribeSSE() {
  if (sseSubId) {
    await bridge.unsubscribeSSE(sseSubId);
  }
  sseSubId = await bridge.subscribeSSE(
    "stream",
    {
      onMessage(event) {
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
        setTimeout(subscribeSSE, 3000);
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
  const el = el.dialogText;
  if (typewriterTimer) {
    el.querySelector(".cursor")?.remove();
    el.textContent = el.textContent.replace(/█$/, "");
    clearTimeout(typewriterTimer);
    typewriterTimer = null;
  }

  let i = 0;
  function tick() {
    if (i < text.length) {
      el.textContent += text[i];
      i++;
      typewriterTimer = setTimeout(tick, 60);
    } else {
      typewriterTimer = null;
      const cursor = document.createElement("span");
      cursor.className = "cursor";
      el.appendChild(cursor);
    }
  }
  tick();
}

/* ---- TTS audio ---- */

function playTTSAudio(base64data) {
  if (!base64data) return;

  const audio = el.ttsAudio;
  audio.src = `data:audio/wav;base64,${base64data}`;

  audio.onplay = () => {
    isAudioPlaying = true;
    startMouthAnimation();
  };
  audio.onended = () => {
    isAudioPlaying = false;
    stopMouthAnimation();
  };
  audio.onerror = () => {
    isAudioPlaying = false;
    stopMouthAnimation();
  };

  audio.play().catch((e) => {
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
  mouthTimer = setInterval(() => {
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
  elText.querySelector(".cursor")?.remove();
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
  el.userInput.addEventListener("keydown", (e) => {
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

  document.addEventListener("click", (e) => {
    if (e.target === el.sendBtn || e.target === el.userInput) return;
    clickTimestamps = trackTimestamps(clickTimestamps);
    keyTimestamps = [];
  });

  document.addEventListener("keydown", (e) => {
    if (e.target === el.userInput) return;
    keyTimestamps = trackTimestamps(keyTimestamps);
    clickTimestamps = [];
  });

  function trackTimestamps(ts) {
    const now = Date.now();
    ts.push(now);
    ts = ts.filter((t) => now - t < rapidWindowMs);
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
