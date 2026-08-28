"""Coverage for the Meta re-point path in ``tools/repoint_webhook.py``.

Nothing here makes a real network call or reads the real ``.env``:
``REPO_ROOT`` is monkeypatched to a ``tmp_path`` for every test that touches
the filesystem, and ``urllib.request.urlopen`` / the module's own
``load_env``, ``graph_call``, ``tunnel_is_live`` and ``discover_tunnel_url``
are stubbed wherever ``main()`` would otherwise reach outward.
"""

from __future__ import annotations

import json
import urllib.error

import pytest

from tools import repoint_webhook as rw


# --- discover_tunnel_url -------------------------------------------------


def test_discover_tunnel_url_picks_the_last_match_in_the_newest_log(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(rw, "REPO_ROOT", tmp_path)
    tools_dir = tmp_path / "tools"
    tools_dir.mkdir()

    older = tools_dir / "cloudflared.out.log"
    older.write_text("connect https://old-one.trycloudflare.com now\n", encoding="utf-8")

    newer = tools_dir / "cloudflared.log"
    newer.write_text(
        "connect https://first.trycloudflare.com\n"
        "reconnected https://second.trycloudflare.com\n",
        encoding="utf-8",
    )

    # Make the mtime ordering explicit rather than relying on write order.
    older_time = 1_700_000_000
    newer_time = 1_700_000_100
    import os

    os.utime(older, (older_time, older_time))
    os.utime(newer, (newer_time, newer_time))

    assert rw.discover_tunnel_url() == "https://second.trycloudflare.com"


def test_discover_tunnel_url_skips_logs_with_no_match_even_if_newer(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(rw, "REPO_ROOT", tmp_path)
    tools_dir = tmp_path / "tools"
    tools_dir.mkdir()

    matching = tools_dir / "cloudflared.log"
    matching.write_text("https://matches.trycloudflare.com\n", encoding="utf-8")

    empty = tools_dir / "cloudflared.err.log"
    empty.write_text("no tunnel hostname in here\n", encoding="utf-8")

    import os

    os.utime(matching, (1_700_000_000, 1_700_000_000))
    os.utime(empty, (1_700_000_500, 1_700_000_500))  # newer, but nothing to find

    assert rw.discover_tunnel_url() == "https://matches.trycloudflare.com"


def test_discover_tunnel_url_returns_none_when_no_log_exists(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(rw, "REPO_ROOT", tmp_path)
    (tmp_path / "tools").mkdir()

    assert rw.discover_tunnel_url() is None


# --- tunnel_is_live --------------------------------------------------------


class _FakeResponse:
    def __init__(self, status: int) -> None:
        self.status = status

    def __enter__(self):
        return self

    def __exit__(self, *exc_info):
        return False


def test_tunnel_is_live_true_on_a_plain_200(monkeypatch) -> None:
    monkeypatch.setattr(rw.urllib.request, "urlopen", lambda request, timeout: _FakeResponse(200))

    live, detail = rw.tunnel_is_live("https://x.trycloudflare.com")

    assert live is True
    assert "200" in detail


def test_tunnel_is_live_true_on_an_http_error(monkeypatch) -> None:
    def _raise(request, timeout):
        raise urllib.error.HTTPError(request.full_url, 403, "Forbidden", hdrs=None, fp=None)

    monkeypatch.setattr(rw.urllib.request, "urlopen", _raise)

    live, detail = rw.tunnel_is_live("https://x.trycloudflare.com")

    assert live is True
    assert "403" in detail
    assert "reached the bus" in detail


def test_tunnel_is_live_false_on_a_connection_error(monkeypatch) -> None:
    def _raise(request, timeout):
        raise urllib.error.URLError("connection refused")

    monkeypatch.setattr(rw.urllib.request, "urlopen", _raise)

    live, detail = rw.tunnel_is_live("https://x.trycloudflare.com")

    assert live is False
    assert "URLError" in detail


def test_tunnel_is_live_false_on_a_timeout(monkeypatch) -> None:
    def _raise(request, timeout):
        raise TimeoutError("timed out")

    monkeypatch.setattr(rw.urllib.request, "urlopen", _raise)

    live, detail = rw.tunnel_is_live("https://x.trycloudflare.com")

    assert live is False
    assert "TimeoutError" in detail


# --- current_callback -------------------------------------------------


def test_current_callback_finds_the_whatsapp_business_account_entry(monkeypatch) -> None:
    payload = {
        "data": [
            {"object": "page", "callback_url": "https://wrong.example.com/webhook"},
            {"object": "whatsapp_business_account", "callback_url": "https://right.example.com/webhook"},
        ]
    }
    monkeypatch.setattr(rw, "graph_call", lambda path, params: payload)

    callback, raw = rw.current_callback("app-id", "app-token")

    assert callback == "https://right.example.com/webhook"
    assert raw == payload


def test_current_callback_returns_none_when_object_absent(monkeypatch) -> None:
    payload = {"data": [{"object": "page", "callback_url": "https://irrelevant.example.com"}]}
    monkeypatch.setattr(rw, "graph_call", lambda path, params: payload)

    callback, raw = rw.current_callback("app-id", "app-token")

    assert callback is None
    assert raw == payload


def test_current_callback_returns_none_when_no_data_key(monkeypatch) -> None:
    monkeypatch.setattr(rw, "graph_call", lambda path, params: {})

    callback, raw = rw.current_callback("app-id", "app-token")

    assert callback is None


# --- main() exit-code contract -----------------------------------------


def _base_env(**overrides: str) -> dict[str, str]:
    env = {
        "META_APP_ID": "123456",
        "META_APP_SECRET": "app-secret-value",
        "META_VERIFY_TOKEN": "synthetic-verify-token",
    }
    env.update(overrides)
    return env


def test_main_exits_1_when_env_values_are_missing(monkeypatch, capsys) -> None:
    monkeypatch.setattr(rw, "load_env", lambda: _base_env(META_APP_SECRET=""))
    monkeypatch.setattr(rw.sys, "argv", ["repoint_webhook.py"])

    code = rw.main()

    assert code == 1
    assert "META_APP_SECRET" in capsys.readouterr().err


def test_main_exits_3_when_reading_current_subscription_errors(monkeypatch) -> None:
    monkeypatch.setattr(rw, "load_env", lambda: _base_env())
    monkeypatch.setattr(rw, "current_callback", lambda app_id, token: (None, {"error": {"message": "bad token"}}))
    monkeypatch.setattr(rw.sys, "argv", ["repoint_webhook.py"])

    assert rw.main() == 3


def test_main_check_mode_exits_0_without_touching_the_tunnel(monkeypatch) -> None:
    monkeypatch.setattr(rw, "load_env", lambda: _base_env())
    monkeypatch.setattr(rw, "current_callback", lambda app_id, token: ("https://existing.example.com/webhook", {}))

    def _boom(*a, **k):
        raise AssertionError("--check must not probe the tunnel")

    monkeypatch.setattr(rw, "discover_tunnel_url", _boom)
    monkeypatch.setattr(rw, "tunnel_is_live", _boom)
    monkeypatch.setattr(rw.sys, "argv", ["repoint_webhook.py", "--check"])

    assert rw.main() == 0


def test_main_exits_1_when_no_tunnel_url_is_given_or_found(monkeypatch) -> None:
    monkeypatch.setattr(rw, "load_env", lambda: _base_env())
    monkeypatch.setattr(rw, "current_callback", lambda app_id, token: (None, {}))
    monkeypatch.setattr(rw, "discover_tunnel_url", lambda: None)
    monkeypatch.setattr(rw.sys, "argv", ["repoint_webhook.py"])

    code = rw.main()

    assert code == 1


def test_main_exits_2_when_the_tunnel_is_not_live(monkeypatch) -> None:
    monkeypatch.setattr(rw, "load_env", lambda: _base_env())
    monkeypatch.setattr(rw, "current_callback", lambda app_id, token: (None, {}))
    monkeypatch.setattr(rw, "tunnel_is_live", lambda base: (False, "URLError: refused"))
    monkeypatch.setattr(
        rw.sys, "argv", ["repoint_webhook.py", "--url", "https://dead.trycloudflare.com"]
    )

    code = rw.main()

    assert code == 2


def test_main_exits_0_when_already_pointed_at_the_target(monkeypatch) -> None:
    target = "https://live.trycloudflare.com/webhook"
    monkeypatch.setattr(rw, "load_env", lambda: _base_env())
    monkeypatch.setattr(rw, "current_callback", lambda app_id, token: (target, {}))
    monkeypatch.setattr(rw, "tunnel_is_live", lambda base: (True, "HTTP 200"))

    def _boom(*a, **k):
        raise AssertionError("must not re-subscribe when already correct")

    monkeypatch.setattr(rw, "graph_call", _boom)
    monkeypatch.setattr(
        rw.sys, "argv", ["repoint_webhook.py", "--url", "https://live.trycloudflare.com"]
    )

    assert rw.main() == 0


def test_main_exits_0_when_the_change_is_confirmed(monkeypatch) -> None:
    target = "https://new.trycloudflare.com/webhook"
    calls = {"current_callback": 0}

    def _current_callback(app_id, token):
        calls["current_callback"] += 1
        # First call (pre-change read): nothing subscribed yet.
        # Second call (post-change read-back): confirms the new target.
        if calls["current_callback"] == 1:
            return None, {}
        return target, {}

    monkeypatch.setattr(rw, "load_env", lambda: _base_env())
    monkeypatch.setattr(rw, "current_callback", _current_callback)
    monkeypatch.setattr(rw, "tunnel_is_live", lambda base: (True, "HTTP 200"))
    monkeypatch.setattr(rw, "graph_call", lambda path, params, method="GET": {"success": True})
    monkeypatch.setattr(
        rw.sys, "argv", ["repoint_webhook.py", "--url", "https://new.trycloudflare.com"]
    )

    assert rw.main() == 0


def test_main_exits_3_when_graph_rejects_the_post(monkeypatch) -> None:
    monkeypatch.setattr(rw, "load_env", lambda: _base_env())
    monkeypatch.setattr(rw, "current_callback", lambda app_id, token: (None, {}))
    monkeypatch.setattr(rw, "tunnel_is_live", lambda base: (True, "HTTP 200"))
    monkeypatch.setattr(
        rw, "graph_call", lambda path, params, method="GET": {"error": {"message": "invalid token", "code": 190}}
    )
    monkeypatch.setattr(
        rw.sys, "argv", ["repoint_webhook.py", "--url", "https://new.trycloudflare.com"]
    )

    code = rw.main()

    assert code == 3


def test_main_exits_3_when_the_read_back_does_not_confirm(monkeypatch) -> None:
    monkeypatch.setattr(rw, "load_env", lambda: _base_env())
    monkeypatch.setattr(rw, "current_callback", lambda app_id, token: (None, {}))
    monkeypatch.setattr(rw, "tunnel_is_live", lambda base: (True, "HTTP 200"))
    monkeypatch.setattr(rw, "graph_call", lambda path, params, method="GET": {"success": True})
    monkeypatch.setattr(
        rw.sys, "argv", ["repoint_webhook.py", "--url", "https://mismatch.trycloudflare.com"]
    )

    # current_callback is stubbed identically for both calls (pre- and
    # post-change), so the read-back never matches the target and main()
    # must report the Graph API outcome as unconfirmed.
    code = rw.main()

    assert code == 3
