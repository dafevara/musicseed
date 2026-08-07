"""Setup wizard tests: success, principal failure states, and token safety.

All discovery is faked — no real Plex, filesystem, or network access.
"""

from conftest import make_dashboard, make_discovery
from fastapi.testclient import TestClient
from musicseed.services.discovery import Reason
from musicseed_web.app import create_app
from musicseed_web.routes import home, setup

SECRET_TOKEN = "SECRET-TOKEN-123"

client = TestClient(create_app())


def _patch(monkeypatch, result, capture: dict | None = None):
    """Point both route modules' discover() at a canned result."""

    def fake_discover(**kwargs):
        if capture is not None:
            capture.update(kwargs)
        return result

    monkeypatch.setattr(home, "discover", fake_discover)
    monkeypatch.setattr(setup, "discover", fake_discover)


# ------------------------------------------------------------- routing


def test_fresh_install_is_routed_to_setup(monkeypatch) -> None:
    _patch(monkeypatch, make_discovery(db_exists=False, db_reason=Reason.PARENT_MISSING))
    response = client.get("/", follow_redirects=False)
    assert response.status_code == 303
    assert response.headers["location"] == "/setup"


def test_configured_install_renders_home(monkeypatch) -> None:
    _patch(monkeypatch, make_discovery())
    monkeypatch.setattr(home, "get_dashboard", lambda: make_dashboard())
    response = client.get("/")
    assert response.status_code == 200
    assert "Plex connection" in response.text


# ------------------------------------------------------------- wizard page


def test_setup_page_explains_and_defers_checks(monkeypatch) -> None:
    _patch(monkeypatch, make_discovery())
    response = client.get("/setup")
    assert response.status_code == 200
    assert "Checking your setup" in response.text
    assert 'hx-get="/setup/results"' in response.text  # discovery runs via HTMX on load
    assert "never modify anything" in response.text


def test_results_success_shows_review_with_masked_token(monkeypatch) -> None:
    _patch(monkeypatch, make_discovery())
    response = client.get("/setup/results")
    assert response.status_code == 200
    assert "Review your setup" in response.text
    assert "••••••••" in response.text  # masked, never the value
    assert "Fix and retry" not in response.text
    assert "Nothing has been changed yet" in response.text


# ------------------------------------------------------------- failure states


def test_results_unreachable_server(monkeypatch) -> None:
    _patch(monkeypatch, make_discovery(server_reason=Reason.UNREACHABLE))
    response = client.get("/setup/results")
    assert "Can't reach Plex" in response.text
    assert "Is Plex Media Server running?" in response.text
    assert "Fix and retry" in response.text
    assert "Review your setup" not in response.text


def test_results_missing_token(monkeypatch) -> None:
    _patch(monkeypatch, make_discovery(
        server_reason=Reason.MISSING_TOKEN, token_configured=False,
    ))
    response = client.get("/setup/results")
    assert "requires a token" in response.text
    assert 'type="password"' in response.text  # token field present for the fix


def test_results_unauthorized_token(monkeypatch) -> None:
    _patch(monkeypatch, make_discovery(server_reason=Reason.UNAUTHORIZED))
    response = client.get("/setup/results")
    assert "rejected the configured token" in response.text


def test_results_library_not_found(monkeypatch) -> None:
    _patch(monkeypatch, make_discovery(
        server_reason=Reason.LIBRARY_NOT_FOUND, library_found=False,
    ))
    response = client.get("/setup/results")
    assert "Server problem detail." in response.text
    assert 'name="plex_library"' in response.text


def test_results_missing_plex_database(monkeypatch) -> None:
    _patch(monkeypatch, make_discovery(
        library_db_ok=False, library_db_reason=Reason.NOT_FOUND,
    ))
    response = client.get("/setup/results")
    assert "No file found at the usual location" in response.text
    assert "Fix and retry" in response.text


def test_results_permission_problem(monkeypatch) -> None:
    _patch(monkeypatch, make_discovery(
        library_db_ok=False, library_db_reason=Reason.NOT_READABLE,
    ))
    response = client.get("/setup/results")
    assert "can't read it" in response.text
    assert "permissions" in response.text


def test_results_db_not_writable_blocks_wizard(monkeypatch) -> None:
    _patch(monkeypatch, make_discovery(db_reason=Reason.NOT_WRITABLE))
    response = client.get("/setup/results")
    assert "Database problem detail." in response.text
    assert "Review your setup" not in response.text


# ------------------------------------------------------------- manual retry


def test_manual_check_passes_overrides_without_token_echo(monkeypatch) -> None:
    capture: dict = {}
    _patch(monkeypatch, make_discovery(), capture)
    response = client.post("/setup/check", data={
        "plex_url": "http://other:32400",
        "plex_token": SECRET_TOKEN,
        "plex_library": "Jazz",
        "plex_db_path": "",
        "musicseed_db_path": "",
    })
    assert response.status_code == 200
    # overrides reached the core service; blanks were dropped
    assert capture["plex_url"] == "http://other:32400"
    assert capture["plex_token"] == SECRET_TOKEN
    assert capture["plex_library"] == "Jazz"
    assert "plex_db_path" not in capture
    # token is in the POST body, never in the URL or the rendered page
    assert SECRET_TOKEN not in response.text
    assert "SECRET" not in response.headers.get("hx-redirect", "")


def test_manual_check_keeps_nonsecret_values_sticky(monkeypatch) -> None:
    capture: dict = {}
    _patch(monkeypatch, make_discovery(server_reason=Reason.UNREACHABLE), capture)
    response = client.post("/setup/check", data={"plex_url": "http://other:32400"})
    assert 'value="http://other:32400"' in response.text  # url sticky
    assert 'name="plex_token" value=""' in response.text  # token never sticky


def test_empty_form_runs_plain_discovery(monkeypatch) -> None:
    capture: dict = {}
    _patch(monkeypatch, make_discovery(), capture)
    response = client.post("/setup/check", data={})
    assert response.status_code == 200
    assert capture == {}  # no overrides passed to the service


# ------------------------------------------------------------- database init


def test_init_db_sets_config_and_creates_database(monkeypatch) -> None:
    init_calls: list = []
    set_config_captured: list = []
    reset_calls: list = []

    monkeypatch.setattr(setup, "initialize_database", lambda: init_calls.append(True))
    monkeypatch.setattr(setup, "set_config", set_config_captured.append)
    monkeypatch.setattr(setup, "reset_engine", lambda: reset_calls.append(True))
    _patch(monkeypatch, make_discovery())

    response = client.post("/setup/init-db", data={
        "musicseed_db_path": "/tmp/fake/musicseed.db",
    })

    assert response.status_code == 200
    assert len(init_calls) == 1
    assert len(set_config_captured) == 1
    assert len(reset_calls) == 1
    assert "Database created" in response.text


def test_init_db_error_shows_failure_and_does_not_break_state(monkeypatch) -> None:
    _patch(monkeypatch, make_discovery())
    monkeypatch.setattr(
        setup, "initialize_database",
        lambda: (_ for _ in ()).throw(RuntimeError("disk is full")),
    )
    monkeypatch.setattr(setup, "set_config", lambda _: None)

    response = client.post("/setup/init-db", data={
        "musicseed_db_path": "/tmp/fake/musicseed.db",
    })

    assert response.status_code == 200
    assert "disk is full" in response.text
    assert "Fix and retry" not in response.text  # still on review, error displayed
    assert "Database created" not in response.text


def test_init_db_no_path_uses_existing_config(monkeypatch) -> None:
    init_calls: list = []
    monkeypatch.setattr(setup, "initialize_database", lambda: init_calls.append(True))
    monkeypatch.setattr(setup, "set_config", lambda _: None)
    monkeypatch.setattr(setup, "reset_engine", lambda: None)
    _patch(monkeypatch, make_discovery())

    response = client.post("/setup/init-db", data={})

    assert response.status_code == 200
    assert len(init_calls) == 1
    assert "Database created" in response.text
