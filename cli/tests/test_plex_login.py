"""Tests for ``plex-login`` / ``plex-logout`` — no plex.tv calls, no real config."""

import musicseed.config as config_module
import pytest
from musicseed.config import Config, set_config
from musicseed.services import plex_link
from musicseed.services.plex_discovery import DiscoveredPlexServer
from musicseed.services.plex_link import (
    PlexAccountInfo,
    PlexLinkError,
    PlexLinkResult,
    PlexLinkStart,
)
from musicseed_cli.app import app
from typer.testing import CliRunner

runner = CliRunner()

ACCOUNT = PlexAccountInfo(id=42, username="dafevara", title="Dafevara")


@pytest.fixture(autouse=True)
def isolated_config(tmp_path, monkeypatch: pytest.MonkeyPatch):
    """Keep the commands away from the developer's real config and browser."""
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "data"))
    monkeypatch.setattr("webbrowser.open", lambda *_a, **_kw: True)
    config_module._config = None
    config_module._config_path = None
    set_config(
        Config.model_validate({"database": {"path": str(tmp_path / "musicseed.db")}})
    )
    yield
    config_module._config = None
    config_module._config_path = None


def _start(handoff: str = "link", code: str = "WXYZ", pin_id: int = 7) -> PlexLinkStart:
    return PlexLinkStart(
        pin_id=pin_id,
        code=code,
        handoff=handoff,  # type: ignore[arg-type]
        auth_url=f"https://app.plex.tv/auth#?clientID=abc&code={code}",
        link_url="https://plex.tv/link",
        expires_in=900,
    )


def test_help_lists_the_login_commands():
    result = runner.invoke(app, ["--help"])
    assert result.exit_code == 0
    assert "plex-login" in result.output
    assert "plex-logout" in result.output


def test_plex_login_prints_the_code_and_reports_success(monkeypatch):
    monkeypatch.setattr(plex_link, "start_plex_link", lambda **kw: _start(**kw))
    monkeypatch.setattr(
        plex_link,
        "wait_for_plex_link",
        lambda pin_id, timeout: PlexLinkResult(
            linked=True,
            token_saved=True,
            url_saved="http://192.168.1.7:32400",
            account=ACCOUNT,
            servers=[
                DiscoveredPlexServer(
                    name="Caladan", host="192.168.1.7", port=32400
                )
            ],
        ),
    )

    result = runner.invoke(app, ["plex-login"])

    assert result.exit_code == 0
    assert "WXYZ" in result.output
    assert "https://plex.tv/link" in result.output
    assert "Signed in as Dafevara" in result.output
    assert "http://192.168.1.7:32400" in result.output
    assert "Caladan" in result.output


def test_plex_login_open_uses_the_browser_handoff(monkeypatch):
    captured: dict = {}

    def fake_start(**kwargs):
        captured.update(kwargs)
        return _start(handoff="forward")

    monkeypatch.setattr(plex_link, "start_plex_link", fake_start)
    monkeypatch.setattr(
        plex_link,
        "wait_for_plex_link",
        lambda pin_id, timeout: PlexLinkResult(linked=True, token_saved=True),
    )

    result = runner.invoke(app, ["plex-login", "--open"])

    assert result.exit_code == 0
    assert captured["handoff"] == "forward"


def test_plex_login_waits_for_the_requested_timeout(monkeypatch):
    monkeypatch.setattr(plex_link, "start_plex_link", lambda **kw: _start(**kw))
    seen: dict = {}

    def fake_wait(pin_id, timeout):
        seen["timeout"] = timeout
        return PlexLinkResult(linked=True, token_saved=True)

    monkeypatch.setattr(plex_link, "wait_for_plex_link", fake_wait)

    assert runner.invoke(app, ["plex-login", "--timeout", "30"]).exit_code == 0
    assert seen["timeout"] == 30.0


def test_plex_login_reports_an_expired_code(monkeypatch):
    monkeypatch.setattr(plex_link, "start_plex_link", lambda **kw: _start(**kw))
    monkeypatch.setattr(
        plex_link,
        "wait_for_plex_link",
        lambda pin_id, timeout: PlexLinkResult(linked=False, expired=True),
    )

    result = runner.invoke(app, ["plex-login"])

    assert result.exit_code == 1
    assert "expired" in result.output


def test_plex_login_reports_a_timeout(monkeypatch):
    monkeypatch.setattr(plex_link, "start_plex_link", lambda **kw: _start(**kw))
    monkeypatch.setattr(
        plex_link,
        "wait_for_plex_link",
        lambda pin_id, timeout: PlexLinkResult(linked=False, pending=True),
    )

    result = runner.invoke(app, ["plex-login", "--timeout", "5"])

    assert result.exit_code == 1
    assert "Timed out after 5s" in result.output


def test_plex_login_reports_an_already_current_token(monkeypatch):
    monkeypatch.setattr(plex_link, "start_plex_link", lambda **kw: _start(**kw))
    monkeypatch.setattr(
        plex_link,
        "wait_for_plex_link",
        lambda pin_id, timeout: PlexLinkResult(linked=True, token_saved=False),
    )

    result = runner.invoke(app, ["plex-login"])

    assert result.exit_code == 0
    assert "already current" in result.output


def test_plex_login_reports_unreachable_plex_tv(monkeypatch):
    def _raise(**_kwargs):
        raise PlexLinkError("Could not reach plex.tv to start sign-in.")

    monkeypatch.setattr(plex_link, "start_plex_link", _raise)

    result = runner.invoke(app, ["plex-login"])

    assert result.exit_code == 1
    assert "Could not reach plex.tv" in result.output


def test_plex_logout_clears_the_stored_token(monkeypatch):
    monkeypatch.setattr(plex_link, "unlink_plex", lambda: True)

    result = runner.invoke(app, ["plex-logout"])

    assert result.exit_code == 0
    assert "Cleared the stored Plex token" in result.output
    assert "revoke it completely" in result.output


def test_plex_logout_when_nothing_is_stored(monkeypatch):
    monkeypatch.setattr(plex_link, "unlink_plex", lambda: False)

    result = runner.invoke(app, ["plex-logout"])

    assert result.exit_code == 0
    assert "No Plex token was stored" in result.output
