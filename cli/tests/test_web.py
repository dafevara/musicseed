"""Tests for the ``web`` command. No real server or browser is ever started."""

import socket
import webbrowser

import musicseed_web.server
from musicseed_cli.app import app
from typer.testing import CliRunner

runner = CliRunner()


def _fake_serve(calls: dict):
    """Stand-in for musicseed_web.server.serve: records args, fires on_started."""

    def fake(host: str, port: int, on_started=None) -> None:
        calls["serve"] = (host, port)
        if on_started is not None:
            on_started()  # simulate "server is ready"

    return fake


def test_help_lists_web_command() -> None:
    result = runner.invoke(app, ["--help"])
    assert result.exit_code == 0
    assert "web" in result.output


def test_starts_server_and_opens_browser_after_ready(monkeypatch) -> None:
    calls: dict = {}
    opened: list[str] = []
    monkeypatch.setattr(musicseed_web.server, "serve", _fake_serve(calls))
    monkeypatch.setattr(webbrowser, "open", opened.append)

    result = runner.invoke(app, ["web"])

    assert result.exit_code == 0
    assert calls["serve"] == ("127.0.0.1", 8788)
    assert opened == ["http://127.0.0.1:8788"]
    assert "Web UI stopped" in result.output


def test_no_open_prevents_browser_launch(monkeypatch) -> None:
    calls: dict = {}
    opened: list[str] = []
    monkeypatch.setattr(musicseed_web.server, "serve", _fake_serve(calls))
    monkeypatch.setattr(webbrowser, "open", opened.append)

    result = runner.invoke(app, ["web", "--no-open"])

    assert result.exit_code == 0
    assert "serve" in calls
    assert opened == []


def test_port_conflict_produces_actionable_error(monkeypatch) -> None:
    calls: dict = {}
    opened: list[str] = []
    monkeypatch.setattr(musicseed_web.server, "serve", _fake_serve(calls))
    monkeypatch.setattr(webbrowser, "open", opened.append)

    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as blocker:
        blocker.bind(("127.0.0.1", 0))
        blocker.listen(1)
        taken_port = blocker.getsockname()[1]

        result = runner.invoke(app, ["web", "--port", str(taken_port)])

    assert result.exit_code == 1
    assert "already in use" in result.output
    assert "--port" in result.output
    assert "serve" not in calls  # server never started
    assert opened == []  # browser never opened


def test_non_loopback_host_opens_localhost_url(monkeypatch) -> None:
    calls: dict = {}
    opened: list[str] = []
    monkeypatch.setattr(musicseed_web.server, "serve", _fake_serve(calls))
    monkeypatch.setattr(webbrowser, "open", opened.append)

    result = runner.invoke(app, ["web", "--host", "0.0.0.0"])

    assert result.exit_code == 0
    assert calls["serve"] == ("0.0.0.0", 8788)
    assert opened == ["http://localhost:8788"]
