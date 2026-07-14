import re
from pathlib import Path

from galgame_web.web_handler import ALLOWED_API_ROUTES


ROOT = Path(__file__).resolve().parents[1]


def test_galgame_frontends_validate_messages_and_render_preview_as_text():
    for relative in ("pages/galgame/app.js", "galgame_web/galgame/app.js"):
        source = (ROOT / relative).read_text(encoding="utf-8")
        assert "event.origin !== window.location.origin" in source
        assert "previewEl.textContent = preview" in source
        assert 'msg.kind === "api-proxy"' not in source
        assert '"./assets/" + encodeURIComponent(filename)' in source
        assert "location.reload()" in source
        assert "el.userInput.value = text" in source
        assert "bgmStartPending" in source
        assert "if (_inputSetup) return" in source
        assert "if (_rapidSetup || !rapidClickEnabled) return" in source
        assert "_rapidActionPending" in source
        assert "_newSessionPending" in source
        assert "switchSeq !== _sessionSwitchSeq" in source
        assert "sessionId !== expectedSession" in source
        assert "resetConversationUi()" in source

    for relative in ("pages/galgame/index.html", "galgame_web/galgame/index.html"):
        source = (ROOT / relative).read_text(encoding="utf-8")
        assert 'maxlength="20000"' in source


def test_settings_frontends_do_not_build_bgm_actions_with_html_strings():
    for relative in ("pages/settings/app.js", "galgame_web/galgame/settings.html"):
        source = (ROOT / relative).read_text(encoding="utf-8")
        assert "nameEl.textContent = f.name" in source
        assert "selectBtn.addEventListener" in source
        assert "onclick='selectBgm" not in source
        assert "onclick='deleteBgm" not in source
        assert 'bgm_playing: _mainBgmPlaying' in source

    config_source = (ROOT / "api/config.py").read_text(encoding="utf-8")
    assert '"bgm_playing": prefs.get("bgm_playing", True)' in config_source


def test_settings_pages_support_batch_selection_and_drag_upload():
    dashboard_html = (ROOT / "pages/settings/index.html").read_text(encoding="utf-8")
    dashboard_js = (ROOT / "pages/settings/app.js").read_text(encoding="utf-8")
    standalone = (ROOT / "galgame_web/galgame/settings.html").read_text(
        encoding="utf-8"
    )

    for source in (dashboard_html, standalone):
        assert 'id="select-all"' in source
        assert 'id="drag-zone"' in source
        assert 'id="bulk-file-input"' in source
    for source in (dashboard_js, standalone):
        assert "function setupDragUpload()" in source
        assert 'apiPost("assets/upload"' in source
    assert "async function fetchAssetChunk(chunk)" in dashboard_js
    assert "fetchAssetChunk(chunk.slice(0, middle))" in dashboard_js


def test_external_webui_proxy_allowlist_covers_frontend_calls():
    sources = []
    for relative in (
        "galgame_web/galgame/app.js",
        "galgame_web/galgame/settings.html",
        "galgame_web/galgame/favorites.html",
    ):
        sources.append((ROOT / relative).read_text(encoding="utf-8"))
    combined = "\n".join(sources)

    get_endpoints = set(re.findall(r'apiGet\("([^"]+)"', combined))
    post_endpoints = set(re.findall(r'apiPost\("([^"]+)"', combined))
    post_endpoints.update(re.findall(r'_proxyApiPost\("([^"]+)"', combined))

    assert get_endpoints <= ALLOWED_API_ROUTES["GET"]
    assert post_endpoints <= ALLOWED_API_ROUTES["POST"]
