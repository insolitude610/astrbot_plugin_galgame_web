var PLUGIN = "astrbot_plugin_galgame_web";
var API_BASE = "/api/plug/" + PLUGIN;
var currentFavAudio = null;
var voiceVolume = 1.0;

function apiGet(endpoint, params) {
  if (window.AstrBotPluginPage && window.AstrBotPluginPage.apiGet) {
    return window.AstrBotPluginPage.apiGet(endpoint, params);
  }
  var url = API_BASE + "/" + endpoint;
  if (params) { url += "?" + new URLSearchParams(params).toString(); }
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

function loadFavorites() {
  var loading = document.getElementById("loading");
  var list = document.getElementById("fav-list");
  var empty = document.getElementById("empty");
  loading.style.display = "block";
  list.innerHTML = "";
  empty.style.display = "none";

  apiGet("favorites/list").then(function(data) {
    var favs = data.favorites || [];
    if (!favs.length) {
      empty.style.display = "block";
      loading.style.display = "none";
      return;
    }

    for (var i = 0; i < favs.length; i++) {
      var f = favs[i];
      var d = new Date(f.saved_at * 1000);
      var dateStr = d.getFullYear() + "-" +
        String(d.getMonth() + 1).padStart(2, "0") + "-" +
        String(d.getDate()).padStart(2, "0") + " " +
        String(d.getHours()).padStart(2, "0") + ":" +
        String(d.getMinutes()).padStart(2, "0");

      var card = document.createElement("div");
      card.className = "fav-card";
      card.id = "fav-" + f.id;

      var dateEl = document.createElement("span");
      dateEl.className = "fav-date";
      dateEl.textContent = dateStr;
      card.appendChild(dateEl);

      var textEl = document.createElement("div");
      textEl.className = "fav-text";
      textEl.textContent = f.text;
      card.appendChild(textEl);

      var playBtn = document.createElement("button");
      playBtn.className = "btn btn-play";
      playBtn.textContent = "播放";
      playBtn.onclick = (function(file) {
        return function() {
            if (currentFavAudio) { currentFavAudio.pause(); currentFavAudio = null; }
            apiGet("audio/data", { name: file }).then(function(resp) {
              var audio = new Audio("data:" + resp.mime + ";base64," + resp.audio);
              audio.volume = voiceVolume;
              currentFavAudio = audio;
              audio.onended = audio.onerror = function() { currentFavAudio = null; };
              audio.play().catch(function(e) { console.warn("Play failed:", e); });
          }).catch(function(e) { console.warn("Audio load failed:", e); });
        };
      })(f.audio_file);
      card.appendChild(playBtn);

      var delBtn = document.createElement("button");
      delBtn.className = "btn btn-delete";
      delBtn.textContent = "取消收藏";
      delBtn.onclick = (function(id) {
        return function() {
          apiPost("favorites/delete", { id: id }).then(function() {
            document.getElementById("fav-" + id).remove();
            if (!document.querySelector(".fav-card")) {
              empty.style.display = "block";
            }
          }).catch(function(e) {
            alert("删除失败: " + e.message);
          });
        };
      })(f.id);
      card.appendChild(delBtn);

      list.appendChild(card);
    }
    loading.style.display = "none";
  }).catch(function(e) {
    list.innerHTML = '<div class="loading" style="color:rgba(220,150,140,.7);">加载失败: ' + e.message + '</div>';
    loading.style.display = "none";
  });
}

function loadBackground() {
  apiGet("config").then(function(cfg) {
    if (cfg.background) {
      document.getElementById("fav-bg").style.backgroundImage = "url(/api/plug/astrbot_plugin_galgame_web/assets/file?name=" + encodeURIComponent(cfg.background) + ")";
    }
    if (cfg.voice_volume != null) { voiceVolume = cfg.voice_volume; }
  }).catch(function() {});
}

if (window.AstrBotPluginPage) {
  loadBackground();
  loadFavorites();
} else {
  var _vPoll = setInterval(function() {
    if (window.AstrBotPluginPage) {
      clearInterval(_vPoll);
      loadBackground();
      loadFavorites();
    }
  }, 100);
  setTimeout(function() { clearInterval(_vPoll); }, 10000);
}
