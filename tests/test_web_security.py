import time
from concurrent.futures import ThreadPoolExecutor

import pytest

from galgame_web.web_handler import (
    BoundedThreadingHTTPServer,
    GalgameWebHandler,
    MAX_LOGIN_FAILURES,
    PLUGIN_API_PREFIX,
    _canonical_plugin_api_path,
    _check_auth_token,
    _make_auth_token,
    resolve_web_bind_host,
)


@pytest.mark.parametrize(
    ("method", "endpoint"),
    [
        ("GET", "config"),
        ("GET", "history"),
        ("POST", "send"),
        ("POST", "assets/upload-key"),
    ],
)
def test_plugin_proxy_allows_only_declared_routes(method, endpoint):
    result = _canonical_plugin_api_path(
        f"{PLUGIN_API_PREFIX}{endpoint}?session_id=abc", method
    )
    assert result == (f"{PLUGIN_API_PREFIX}{endpoint}", "session_id=abc")


@pytest.mark.parametrize(
    ("method", "path"),
    [
        ("GET", "/api/v1/plugins"),
        ("GET", f"{PLUGIN_API_PREFIX}../../../api/v1/plugins"),
        ("GET", f"{PLUGIN_API_PREFIX}%2e%2e/%2e%2e/api/v1/plugins"),
        ("GET", f"{PLUGIN_API_PREFIX}%252e%252e/api/v1/plugins"),
        ("POST", f"{PLUGIN_API_PREFIX}config"),
        ("GET", f"{PLUGIN_API_PREFIX}send"),
        ("POST", "/api/plug/another_plugin/send"),
    ],
)
def test_plugin_proxy_rejects_escape_and_wrong_method(method, path):
    assert _canonical_plugin_api_path(path, method) is None


def test_no_password_forces_loopback_but_password_preserves_lan_access():
    assert resolve_web_bind_host("0.0.0.0", "") == "127.0.0.1"
    assert resolve_web_bind_host("192.168.1.20", "") == "127.0.0.1"
    assert resolve_web_bind_host("0.0.0.0", "secret") == "0.0.0.0"
    assert resolve_web_bind_host("127.0.0.1", "") == "127.0.0.1"


def test_auth_token_rejects_expired_and_future_timestamps(monkeypatch):
    now = int(time.time())
    monkeypatch.setattr("galgame_web.web_handler.time.time", lambda: now)

    assert _check_auth_token("secret", _make_auth_token("secret", now))
    assert not _check_auth_token("wrong", _make_auth_token("secret", now))
    assert not _check_auth_token("secret", _make_auth_token("secret", now - 86401))
    assert not _check_auth_token("secret", _make_auth_token("secret", now + 1))


def test_login_attempt_reservation_is_atomic():
    client_ip = "192.0.2.10"
    GalgameWebHandler._login_failures.pop(client_ip, None)
    try:
        with ThreadPoolExecutor(max_workers=16) as executor:
            results = list(
                executor.map(
                    lambda _: GalgameWebHandler._reserve_login_attempt(None, client_ip),
                    range(MAX_LOGIN_FAILURES * 3),
                )
            )
        assert sum(results) == MAX_LOGIN_FAILURES
    finally:
        GalgameWebHandler._login_failures.pop(client_ip, None)


def test_external_server_uses_a_bounded_worker_pool():
    server = BoundedThreadingHTTPServer(("127.0.0.1", 0), GalgameWebHandler, 2)
    try:
        assert server._worker_slots._initial_value == 2
    finally:
        server.server_close()
