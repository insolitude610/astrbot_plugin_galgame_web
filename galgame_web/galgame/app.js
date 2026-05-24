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
var isAudioPlaying = false;

/* ---- pixi mesh layered renderer ---- */
var pixiApp = null;
var pixiContainer = null;
var meshA = null, meshB = null;
var basePosA = null, basePosB = null;
var activeMesh = "a";
var crossfading = false;
var meshW = 0, meshH = 0;
var cols = 8, rows = 12;
var animTime = 0;
var blinkPhase = 0;
var blinkSide = "a";
var blinkTimer = null;
var blinkSchedulerId = null;
var currentExpr = "neutral";
var expressionsBlink = {};
var activeFace = "a";

function initPixiApp() {
  var container = document.getElementById("pixi-container");
  if (!container) return;
  pixiContainer = container;
  container.innerHTML = "";
  if (pixiApp) { pixiApp.destroy(true); pixiApp = null; }
  pixiApp = new PIXI.Application({
    width: container.offsetWidth || 500,
    height: container.offsetHeight || 700,
    backgroundAlpha: 0,
    antialias: true,
    resolution: window.devicePixelRatio || 1,
    autoDensity: true,
  });
  container.appendChild(pixiApp.view);
}

function positionPlane(plane) {
  var fitScale = Math.min(
    pixiApp.screen.width / plane.texture.width,
    pixiApp.screen.height / plane.texture.height
  );
  plane.scale.set(fitScale);
  plane.x = pixiApp.screen.width / 2;
  plane.y = pixiApp.screen.height;
  plane.pivot.set(plane.texture.width / 2, plane.texture.height);
}

function animateMeshes() {
  if (spriteMode !== "layered") return;
  var t = animTime;

  if (crossfading) {
    if (meshA) meshA.alpha = Math.max(0, meshA.alpha - 0.035);
    if (meshB) meshB.alpha = Math.min(1, meshB.alpha + 0.035);
    if (meshB && meshB.alpha >= 1) {
      crossfading = false;
      if (meshA) { pixiApp.stage.removeChild(meshA); meshA.destroy(); meshA = null; basePosA = null; }
      meshA = meshB; meshB = null;
      basePosA = basePosB; basePosB = null;
      meshA.alpha = 1;
      activeMesh = "a";
    }
  }

  if (meshA && basePosA) {
    animateMeshVertices(meshA, basePosA, t, activeMesh === "a" && blinkPhase > 1);
  }
  if (meshB && basePosB && crossfading) {
    animateMeshVertices(meshB, basePosB, t, false);
  }

  animTime += 0.016;
}

function animateMeshVertices(plane, base, time, blinkClosed) {
  var buffer = plane.geometry.getBuffer("aVertexPosition");
  var v = buffer.data;
  var vertsPerRow = cols + 1;
  var w = plane.texture.width, h = plane.texture.height;
  var halfW = w / 2, halfH = h / 2;
  var neckRow = Math.floor(rows * 0.35);
  var hairRows = Math.floor(rows * 0.3);

  for (var r = 0; r <= rows; r++) {
    var yNorm = r / rows;
    var yFromFeet = 1 - yNorm;
    var headFactor = r < neckRow ? 1 - r / neckRow : 0;

    for (var c = 0; c <= cols; c++) {
      var idx = (r * vertsPerRow + c) * 2;
      var bx = base[idx];
      var by = base[idx + 1];

      // breathing: chest expansion (Y=up, X=slight ribcage)
      var chest = Math.sin(time * 1.4) * (1 - Math.abs(yNorm - 0.35) * 1.5);
      chest = Math.max(0, chest);
      var breathY = chest * halfH * 0.02 * yFromFeet;
      var breathX = chest * halfW * 0.008 * yFromFeet;

      // hair sway: top 30% rows, quadratic fade
      var hairOff = 0;
      if (r < hairRows) {
        var hairFade = (hairRows - r) / hairRows;
        hairFade = hairFade * hairFade;
        hairOff = Math.sin(time * 2.5 + c * 0.6) * halfW * 0.025 * hairFade;
      }

      // head tilt: slight rotation-like X offset
      var tilt = Math.sin(time * 0.8 + 1.5) * halfW * 0.012 * headFactor;

      // blink: compress eye region Y
      var blinkCompress = 1;
      if (blinkClosed && r >= Math.floor(rows * 0.25) && r <= Math.floor(rows * 0.38)) {
        blinkCompress = 0.08;
      }

      v[idx] = bx + hairOff + breathX + tilt;
      v[idx + 1] = by * blinkCompress + breathY * blinkCompress;
    }
  }
  buffer.update();
}

function scheduleBlink() {
  if (spriteMode !== "layered") return;
  var delay = 3000 + Math.random() * 3000;
  blinkSchedulerId = setTimeout(function() {
    if (spriteMode !== "layered") return;
    blinkPhase = 1;
    blinkSide = activeMesh;
    blinkTimer = setTimeout(function() {
      blinkPhase = 2;
      blinkTimer = setTimeout(function() {
        blinkPhase = 0;
        scheduleBlink();
      }, 130);
    }, 50);
  }, delay);
}

function stopMeshRender() {
  crossfading = false;
  if (blinkSchedulerId) { clearTimeout(blinkSchedulerId); blinkSchedulerId = null; }
  if (blinkTimer) { clearTimeout(blinkTimer); blinkTimer = null; }
  blinkPhase = 0;
  if (pixiApp && pixiApp.ticker) pixiApp.ticker.remove(animateMeshes);
  if (pixiApp) { pixiApp.destroy(true); pixiApp = null; }
  if (pixiContainer) pixiContainer.innerHTML = "";
  meshA = null; meshB = null;
  basePosA = null; basePosB = null;
}

function startMeshRender(exprVal) {
  initPixiApp();
  if (!pixiApp) return;
  activeMesh = "a";
  crossfading = false;

  var texture = PIXI.Texture.from(assetUrl(exprVal));
  if (texture.baseTexture.valid) {
    _buildMesh(texture);
  } else {
    texture.baseTexture.once("loaded", function() { _buildMesh(texture); });
  }

  function _buildMesh(tex) {
    meshW = tex.width; meshH = tex.height;
    meshA = new PIXI.SimplePlane(tex, cols, rows);
    meshA.alpha = 1;
    pixiApp.stage.addChild(meshA);
    positionPlane(meshA);
    var buffer = meshA.geometry.getBuffer("aVertexPosition");
    basePosA = new Float32Array(buffer.data);
    pixiApp.ticker.add(animateMeshes);
    if (!blinkSchedulerId) scheduleBlink();
  }
}

function switchMeshExpression(emotion) {
  if (!pixiApp || !meshA) return;
  var exprVal = expressions[emotion] || expressions["neutral"];
  if (crossfading) {
    crossfading = false;
    if (meshB) { pixiApp.stage.removeChild(meshB); meshB.destroy(); meshB = null; basePosB = null; }
  }

  var texture = PIXI.Texture.from(assetUrl(exprVal));
  if (texture.baseTexture.valid) {
    _buildSwitchMesh(texture);
  } else {
    texture.baseTexture.once("loaded", function() { _buildSwitchMesh(texture); });
  }

  function _buildSwitchMesh(tex) {
    if (meshW !== tex.width || meshH !== tex.height) {
      meshW = tex.width; meshH = tex.height;
    }
    meshB = new PIXI.SimplePlane(tex, cols, rows);
    meshB.alpha = 0;
    pixiApp.stage.addChild(meshB);
    positionPlane(meshB);
    var buffer = meshB.geometry.getBuffer("aVertexPosition");
    basePosB = new Float32Array(buffer.data);
    crossfading = true;
    activeMesh = "b";
    if (blinkSchedulerId) { clearTimeout(blinkSchedulerId); blinkSchedulerId = null; }
    blinkPhase = 0;
    if (blinkTimer) { clearTimeout(blinkTimer); blinkTimer = null; }
    scheduleBlink();
  }
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
    var s = Math.max(-32768, Math.min(32767, flat[i]));
    view.setInt16(44 + i * 2, s, true);
  }

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
  var isResuming = false;
  try {
    var resp = await apiPost("session/init", { resume_id: savedId });
    if (!resp || !resp.session_id) {
      console.error("session/init returned:", resp);
      el.dialogText.textContent = "会话初始化失败(无session_id)，请刷新页面。";
    } else {
      sessionId = resp.session_id;
      localStorage.setItem("galgame_session_id", sessionId);
      if (resp.current_emotion) {
        currentEmotion = resp.current_emotion;
      }
      if (savedId === resp.session_id) {
        isResuming = true;
      }
    }
  } catch (err) {
    console.error("Failed to init session:", err);
    el.dialogText.textContent = "初始化失败(" + (err.message || err) + ")，请刷新页面。";
  }

  setupInput();
  setupRapidDetection();
  applySprites();
  if (isResuming) {
    restoreLastMessage();
  }
}

function applyConfig(cfg) {
  spriteMode = cfg.sprite_mode || "single";
  rapidThreshold = cfg.rapid_click_threshold || 5;
  rapidWindowMs = (cfg.rapid_window_seconds || 3) * 1000;
  ttsProvider = cfg.tts_provider || "";
  expressions = cfg.expressions || {};
  expressionsBlink = cfg.expressions_blink || {};
  layers = cfg.layers || {};
  characterName = cfg.character_name || "小星";
  backgroundFile = cfg.background || "";
  el.characterName.textContent = characterName;
  document.documentElement.style.setProperty("--sprite-scale", cfg.sprite_scale || 1);
  document.documentElement.style.setProperty("--sprite-bottom", cfg.sprite_bottom != null ? cfg.sprite_bottom : 28);
  document.documentElement.style.setProperty("--sprite-left", cfg.sprite_left != null ? cfg.sprite_left : 50);
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
  if (spriteMode === "layered") {
    el.spriteContainer.classList.add("active");
    el.spriteSingle.classList.remove("active");
    var exprVal = expressions[currentEmotion] || expressions["neutral"];
    currentExpr = currentEmotion;
    startMeshRender(exprVal);
  } else {
    stopMeshRender();
    el.spriteContainer.classList.remove("active");
    el.spriteSingle.classList.add("active");
    activeFace = "a";
    el.spriteFaceA.classList.remove("hidden");
    el.spriteFaceB.classList.add("hidden");
    loadExpressionToSingle(currentEmotion);
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
  if (spriteMode === "layered") {
    switchMeshExpression(emotion);
  } else {
    loadExpressionToSingle(emotion);
  }
}

/* ---- typewriter ---- */

function typewriterAppend(text, emotionMap) {
  var elText = el.dialogText;
  if (typewriterTimer) {
    clearTimeout(typewriterTimer);
    typewriterTimer = null;
  }

  emotionMap = emotionMap || {};
  var emotionPositions = Object.keys(emotionMap).map(Number).sort(function(a,b){return a-b;});

  elText.textContent = "";
  var i = 0;
  function tick() {
    if (i < text.length) {
      i++;
      elText.textContent = text.substring(0, i);
      // Check if we passed an emotion position
      while (emotionPositions.length && emotionPositions[0] < i) {
        var pos = emotionPositions.shift();
        switchExpression(emotionMap[pos]);
      }
      typewriterTimer = setTimeout(tick, 60);
    } else {
      typewriterTimer = null;
      // Apply any remaining emotions
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

/* ---- TTS audio ---- */

function playTTSAudio(base64data) {
  if (!base64data) return;

  var audio = el.ttsAudio;
  audio.src = "data:audio/wav;base64," + base64data;

  audio.onplay = function () {
    isAudioPlaying = true;
  };
  audio.onended = function () {
    isAudioPlaying = false;
  };
  audio.onerror = function () {
    isAudioPlaying = false;
  };

  audio.play().catch(function (e) {
    console.warn("Audio play failed:", e);
  });
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
      typewriterAppend(resp.reply, emotionMap);
      finishResponse();
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
  stopMeshRender();
  if (typewriterTimer) clearTimeout(typewriterTimer);
});

document.addEventListener("visibilitychange", function () {
  if (document.hidden) stopMeshRender();
  else if (spriteMode === "layered") {
    var exprVal = expressions[currentEmotion] || expressions["neutral"];
    startMeshRender(exprVal);
  }
});
