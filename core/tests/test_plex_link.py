"""Tests for services.plex_link — the plex.tv PIN sign-in flow (no real network)."""

from __future__ import annotations

import httpx
import musicseed.config as config_module
import pytest
from musicseed.config import Config, get_config, save_config, set_config
from musicseed.exceptions import ConfigurationError
from musicseed.services import plex_link
from musicseed.services.plex_link import (
    PlexLinkError,
    poll_plex_link,
    require_plex_token,
    start_plex_link,
    unlink_plex,
    wait_for_plex_link,
)

SECRET_TOKEN = "plex-account-token-xyz"

USER_PAYLOAD = {
    "id": 42,
    "username": "dafevara",
    "title": "Dafevara",
    "email": "dafevara@example.com",
}

RESOURCES_XML = """\
<MediaContainer size="1">
  <Device name="Caladan" product="Plex Media Server" productVersion="1.43.3.10828"
      clientIdentifier="3309a4b35976865b17593c74cb3f5b447c520cbf" provides="server">
    <Connection protocol="http" address="192.168.139.3" port="32400" local="1"/>
    <Connection protocol="http" address="100.73.64.125" port="32400" local="0"/>
  </Device>
</MediaContainer>
"""

@pytest.fixture(autouse=True)
def isolated_config(tmp_path, monkeypatch: pytest.MonkeyPatch):
    """Never read or write the developer's real config while linking."""
    monkeypatch.setenv("HOME", str(tmp_path))
    config_module._config = None
    config_module._config_path = None
    set_config(
        Config.model_validate({"database": {"path": str(tmp_path / "musicseed.db")}})
    )
    yield
    config_module._config = None
    config_module._config_path = None


def _stub_plex_tv(
    monkeypatch: pytest.MonkeyPatch,
    *,
    pin_payload: dict | None = None,
    pin_status: int = 200,
    user_status: int = 200,
    resources_xml: str = RESOURCES_XML,
    unreachable_hosts: set[str] | None = None,
    post_calls: list[dict] | None = None,
    get_calls: list[str] | None = None,
) -> None:
    """Patch the shared httpx module used by both plex_link and plex_discovery.

    ``unreachable_hosts`` models the real complaint this guards against: a Plex
    server advertises addresses that do not answer from this machine.
    """

    def _response(status: int, url: str, **kwargs) -> httpx.Response:
        # raise_for_status() needs the originating request on the response.
        return httpx.Response(status, request=httpx.Request("GET", url), **kwargs)

    def fake_post(url, **kwargs):
        if post_calls is not None:
            post_calls.append({"url": url, **kwargs})
        return _response(
            200, url, json=pin_payload or {"id": 7, "code": "ABCD", "expiresIn": 900}
        )

    def fake_get(url, **kwargs):
        if get_calls is not None:
            get_calls.append(url)
        if "/api/v2/pins/" in url:
            if pin_status != 200:
                return _response(pin_status, url, json={})
            return _response(200, url, json=pin_payload or {"authToken": None})
        if "/api/v2/user" in url:
            if user_status != 200:
                return _response(user_status, url, json={})
            return _response(200, url, json=USER_PAYLOAD)
        if url.endswith("/identity"):
            host = url.split("//", 1)[1].split(":", 1)[0]
            if unreachable_hosts and host in unreachable_hosts:
                raise httpx.ConnectError(f"no route to {host}")
            return _response(200, url, json={})
        if "api/resources" in url:
            return _response(200, url, text=resources_xml)
        raise AssertionError(f"unexpected URL {url}")

    monkeypatch.setattr(plex_link.httpx, "post", fake_post)
    monkeypatch.setattr(plex_link.httpx, "get", fake_get)


def _config_file_text() -> str:
    path = config_module.get_config_path()
    assert path is not None
    return path.read_text(encoding="utf-8")


def test_start_link_forward_builds_auth_url_and_persists_identifier(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[dict] = []
    _stub_plex_tv(
        monkeypatch,
        pin_payload={"id": 7, "code": "8lzjqnq8lye02n52jq3fqxf8e", "expiresIn": 1800},
        post_calls=calls,
    )

    start = start_plex_link(
        handoff="forward", forward_url="http://localhost:8080/setup"
    )

    assert calls[0]["params"] == {"strong": "true"}
    identifier = calls[0]["headers"]["X-Plex-Client-Identifier"]
    assert len(identifier) == 32
    assert calls[0]["headers"]["X-Plex-Product"] == "MusicSeed"

    # Plex reads the parameters from the URL fragment.
    assert start.auth_url.startswith("https://app.plex.tv/auth#?")
    assert f"clientID={identifier}" in start.auth_url
    assert "code=8lzjqnq8lye02n52jq3fqxf8e" in start.auth_url
    assert "forwardUrl=http%3A%2F%2Flocalhost%3A8080%2Fsetup" in start.auth_url
    assert start.link_url == "https://plex.tv/link"
    assert start.expires_in == 1800

    # The identifier survives the process, and re-linking reuses it.
    assert get_config().plex.client_identifier == identifier
    start_plex_link(handoff="forward")
    assert calls[1]["headers"]["X-Plex-Client-Identifier"] == identifier


def test_start_link_link_handoff_uses_short_pin(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[dict] = []
    _stub_plex_tv(monkeypatch, post_calls=calls)

    start = start_plex_link(handoff="link")

    assert calls[0]["params"] == {}
    assert start.handoff == "link"
    assert start.code == "ABCD"
    assert start.expires_in == 900


def test_start_link_reports_unreachable_plex_tv(monkeypatch: pytest.MonkeyPatch) -> None:
    def _raise(*_args, **_kwargs):
        raise httpx.ConnectError("offline")

    monkeypatch.setattr(plex_link.httpx, "post", _raise)
    with pytest.raises(PlexLinkError, match="Could not reach plex.tv"):
        start_plex_link()


def test_start_link_rejects_missing_pin(monkeypatch: pytest.MonkeyPatch) -> None:
    _stub_plex_tv(monkeypatch, pin_payload={"id": None, "code": None})
    with pytest.raises(PlexLinkError, match="usable sign-in code"):
        start_plex_link()


def test_poll_is_pending_until_claimed(monkeypatch: pytest.MonkeyPatch) -> None:
    _stub_plex_tv(monkeypatch, pin_payload={"authToken": None})

    result = poll_plex_link(7)

    assert result.linked is False
    assert result.pending is True
    assert result.expired is False
    assert get_config().plex.token == ""


def test_poll_reports_expired_pin(monkeypatch: pytest.MonkeyPatch) -> None:
    _stub_plex_tv(monkeypatch, pin_status=404)

    result = poll_plex_link(7)

    assert result.expired is True
    assert result.linked is False


@pytest.mark.parametrize("status", [429, 503])
def test_poll_rides_out_transient_plex_tv_errors(
    monkeypatch: pytest.MonkeyPatch, status: int
) -> None:
    """A brief plex.tv outage must not throw away a PIN the user is approving."""
    _stub_plex_tv(monkeypatch, pin_status=status)

    result = poll_plex_link(7)

    assert result.pending is True
    assert result.expired is False


def test_poll_links_account_and_saves_credentials(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _stub_plex_tv(monkeypatch, pin_payload={"authToken": SECRET_TOKEN})

    result = poll_plex_link(7)

    assert result.linked is True
    assert result.token_saved is True
    assert result.account is not None
    assert result.account.title == "Dafevara"
    assert result.servers and result.servers[0].name == "Caladan"
    # The shipped localhost default is replaced by the account's server.
    assert result.url_saved == "http://192.168.139.3:32400"
    assert get_config().plex.token == SECRET_TOKEN
    assert get_config().plex.url == "http://192.168.139.3:32400"
    assert SECRET_TOKEN in _config_file_text()


def test_poll_never_saves_an_address_that_does_not_answer(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Regression: the sign-in used to pick Plex's own LAN address blindly.

    A server on another network advertises addresses only reachable there, so a
    "local" flag is not proof. Nothing is saved unless something answered.
    """
    _stub_plex_tv(
        monkeypatch,
        pin_payload={"authToken": SECRET_TOKEN},
        unreachable_hosts={"192.168.139.3", "100.73.64.125"},
    )

    result = poll_plex_link(7)

    assert result.linked is True
    assert result.token_saved is True  # the token is still worth keeping
    assert result.url_saved is None
    assert get_config().plex.url == "http://localhost:32400"


def test_poll_prefers_an_address_that_answers(monkeypatch: pytest.MonkeyPatch) -> None:
    """The rank-best address wins only if it answers; otherwise use a working one."""
    _stub_plex_tv(
        monkeypatch,
        pin_payload={"authToken": SECRET_TOKEN},
        unreachable_hosts={"192.168.139.3"},
    )

    result = poll_plex_link(7)

    assert result.url_saved == "http://100.73.64.125:32400"
    assert get_config().plex.url == "http://100.73.64.125:32400"


def test_poll_keeps_an_explicit_server_url(monkeypatch: pytest.MonkeyPatch) -> None:
    cfg = get_config().model_copy(deep=True)
    cfg.plex.url = "https://media.example.com:32400"
    set_config(cfg)
    _stub_plex_tv(monkeypatch, pin_payload={"authToken": SECRET_TOKEN})

    result = poll_plex_link(7)

    assert result.token_saved is True
    assert result.url_saved is None
    assert get_config().plex.url == "https://media.example.com:32400"
    assert get_config().plex.token == SECRET_TOKEN


def test_poll_refuses_to_save_a_rejected_token(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _stub_plex_tv(
        monkeypatch, pin_payload={"authToken": SECRET_TOKEN}, user_status=401
    )

    with pytest.raises(PlexLinkError, match="token was rejected"):
        poll_plex_link(7)

    assert get_config().plex.token == ""


def test_poll_can_validate_without_saving(monkeypatch: pytest.MonkeyPatch) -> None:
    _stub_plex_tv(monkeypatch, pin_payload={"authToken": SECRET_TOKEN})

    result = poll_plex_link(7, save=False)

    assert result.linked is True
    assert result.token_saved is False
    assert get_config().plex.token == ""


def test_poll_does_not_pick_between_multiple_servers(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    two_servers = RESOURCES_XML.replace(
        "</MediaContainer>",
        '  <Device name="Other" product="Plex Media Server" clientIdentifier="other"'
        ' provides="server"><Connection protocol="http" address="nas.local"'
        ' port="32400" local="1"/></Device>\n</MediaContainer>',
    )
    _stub_plex_tv(
        monkeypatch,
        pin_payload={"authToken": SECRET_TOKEN},
        resources_xml=two_servers,
    )

    result = poll_plex_link(7)

    assert result.token_saved is True  # the token still lands
    assert result.url_saved is None  # but MusicSeed does not guess the server
    assert get_config().plex.url == "http://localhost:32400"


def test_wait_for_link_stops_once_claimed(monkeypatch: pytest.MonkeyPatch) -> None:
    results = iter(
        [
            plex_link.PlexLinkResult(linked=False, pending=True),
            plex_link.PlexLinkResult(linked=True, token_saved=True),
        ]
    )
    monkeypatch.setattr(plex_link, "poll_plex_link", lambda *_a, **_kw: next(results))

    slept: list[float] = []
    result = wait_for_plex_link(7, sleep=slept.append)

    assert result.linked is True
    assert slept == [2.0]


def test_wait_for_link_gives_up_at_timeout(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        plex_link,
        "poll_plex_link",
        lambda *_a, **_kw: plex_link.PlexLinkResult(linked=False, pending=True),
    )
    result = wait_for_plex_link(7, timeout=0.0, sleep=lambda _s: None)
    assert result.pending is True


def test_unlink_clears_token_but_keeps_identifier() -> None:
    cfg = get_config().model_copy(deep=True)
    cfg.plex.token = SECRET_TOKEN
    cfg.plex.client_identifier = "abc123"
    set_config(cfg)

    assert unlink_plex() is True
    assert get_config().plex.token == ""
    assert get_config().plex.client_identifier == "abc123"
    assert unlink_plex() is False


def test_require_plex_token_points_at_the_two_real_fixes() -> None:
    with pytest.raises(ConfigurationError) as excinfo:
        require_plex_token()

    message = str(excinfo.value)
    assert "Sign in with Plex" in message
    assert "musicseed-cli plex-login" in message
    # The old wording leaked a raw config key at end users.
    assert "config file" not in message


def test_require_plex_token_returns_configured_token() -> None:
    cfg = get_config().model_copy(deep=True)
    cfg.plex.token = SECRET_TOKEN
    set_config(cfg)
    assert require_plex_token() == SECRET_TOKEN


def test_require_plex_token_reloads_a_stale_process_config(tmp_path) -> None:
    # A long-running MCP server cached config before the link happened.
    linked = Config.model_validate({"database": {"path": str(tmp_path / "m.db")}})
    linked.plex.token = SECRET_TOKEN
    path = tmp_path / "config.yaml"
    save_config(linked, path)

    stale = linked.model_copy(deep=True)
    stale.plex.token = ""
    set_config(stale)

    assert require_plex_token(stale) == SECRET_TOKEN


def test_plex_client_refuses_remote_cleartext_without_opt_in() -> None:
    cfg = get_config().model_copy(deep=True)
    cfg.plex.token = SECRET_TOKEN
    cfg.plex.url = "http://plex.example.com:32400"
    set_config(cfg)

    with pytest.raises(ConfigurationError) as excinfo:
        plex_link.plex_client(cfg)

    message = str(excinfo.value)
    assert "cleartext" in message
    assert "plex.allow_cleartext_remote" in message


def test_plex_client_allows_remote_cleartext_when_opted_in() -> None:
    cfg = get_config().model_copy(deep=True)
    cfg.plex.token = SECRET_TOKEN
    cfg.plex.url = "http://plex.example.com:32400"
    cfg.plex.allow_cleartext_remote = True
    set_config(cfg)

    client = plex_link.plex_client(cfg)
    assert client is not None


def test_plex_client_allows_local_http_without_opt_in() -> None:
    cfg = get_config().model_copy(deep=True)
    cfg.plex.token = SECRET_TOKEN
    cfg.plex.url = "http://192.168.1.5:32400"
    set_config(cfg)

    assert plex_link.plex_client(cfg) is not None
