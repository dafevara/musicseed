"""Unit tests for ``musicseed.clients.plex.client`` — mock httpx at the transport
level so no real Plex server is involved.

Coverage targets
    - Every public method of PlexClient
    - Error paths (ConnectError, HTTPStatusError, empty data)
    - Edge cases (XML fallback, missing fields, duplicate names)
    - New spec-aligned methods (search, metadata, etc.)
"""

from __future__ import annotations

import json as _json
from typing import Any

import httpx
import pytest
from musicseed.clients.plex import (
    HubEntry,
    LibrarySectionResult,
    MediaItem,
    Playlist,
    PlexAPIError,
    PlexClient,
)
from musicseed.clients.plex import client as plex_client

TOKEN = "test-token-abc"
BASE_URL = "http://localhost:32400"


# ---------------------------------------------------------------------------
# HTTP transport helpers
# ---------------------------------------------------------------------------
# We monkeypatch httpx.request at the module level so every _send/_get/_post/
# _put call flows through our mock.  Tests that need custom behaviour drop
# their own response factory via the ``mock_httpx`` fixture.


_MOCK_REQUEST = httpx.Request("GET", "http://localhost:32400/")


def _json_resp(data: dict[str, Any], status: int = 200) -> httpx.Response:
    return httpx.Response(status, json=data, request=_MOCK_REQUEST)


def _empty_200() -> httpx.Response:
    return httpx.Response(200, content=b"", request=_MOCK_REQUEST)


def _text_resp(content: str, content_type: str = "application/xml") -> httpx.Response:
    return httpx.Response(
        200, content=content.encode(),
        headers={"content-type": content_type},
        request=_MOCK_REQUEST,
    )


# ---------------------------------------------------------------------------


class TestInit:
    def test_strips_trailing_slash(self) -> None:
        c = PlexClient("http://localhost:32400/", TOKEN)
        assert c._base == "http://localhost:32400"

    def test_stores_token_in_header(self) -> None:
        c = PlexClient(BASE_URL, TOKEN)
        assert c._headers["X-Plex-Token"] == TOKEN

    def test_accept_header_is_json(self) -> None:
        c = PlexClient(BASE_URL, TOKEN)
        assert c._headers["Accept"] == "application/json"

    def test_default_timeout(self) -> None:
        c = PlexClient(BASE_URL, TOKEN)
        assert c._timeout == 15.0

    def test_custom_timeout(self) -> None:
        c = PlexClient(BASE_URL, TOKEN, timeout=60.0)
        assert c._timeout == 60.0


# ---------------------------------------------------------------------------
# _send / _get / _post / _put
# ---------------------------------------------------------------------------


class TestSend:
    def test_get_forwards_params(self, monkeypatch: pytest.MonkeyPatch) -> None:
        called: list[dict[str, Any]] = []

        def _fake(method, url, **kw):
            called.append({"method": method, "url": url, **kw})
            return _json_resp({"ok": True})

        monkeypatch.setattr(plex_client.httpx, "request", _fake)
        c = PlexClient(BASE_URL, TOKEN)
        c._get("/test", foo="bar")
        assert called[0]["method"] == "GET"
        assert called[0]["url"] == "http://localhost:32400/test"
        assert called[0]["params"] == {"foo": "bar"}

    def test_post_forwards_params(self, monkeypatch: pytest.MonkeyPatch) -> None:
        called: list[dict[str, Any]] = []

        def _fake(method, url, **kw):
            called.append(kw)
            return _json_resp({"ok": True})

        monkeypatch.setattr(plex_client.httpx, "request", _fake)
        c = PlexClient(BASE_URL, TOKEN)
        c._post("/playlists", title="Test")
        assert called[0]["params"] == {"title": "Test"}

    def test_put_with_body(self, monkeypatch: pytest.MonkeyPatch) -> None:
        def _fake(*a, **kw):
            return _json_resp({"updated": 1})

        monkeypatch.setattr(plex_client.httpx, "request", _fake)
        c = PlexClient(BASE_URL, TOKEN)
        result = c._put("/items/1", uri="server://x")
        assert result == {"updated": 1}

    def test_put_empty_body(self, monkeypatch: pytest.MonkeyPatch) -> None:
        def _fake(*a, **kw):
            return _empty_200()

        monkeypatch.setattr(plex_client.httpx, "request", _fake)
        c = PlexClient(BASE_URL, TOKEN)
        result = c._put("/items/1/analyze")
        assert result == {}

    def test_connect_error_wraps_to_plex_api_error(self, monkeypatch: pytest.MonkeyPatch) -> None:
        def _raise(*a, **kw):
            raise httpx.ConnectError("refused")

        monkeypatch.setattr(plex_client.httpx, "request", _raise)
        c = PlexClient(BASE_URL, TOKEN)
        with pytest.raises(PlexAPIError, match="Cannot reach Plex"):
            c._get("/")

    def test_http_401_raises_plex_api_error(self, monkeypatch: pytest.MonkeyPatch) -> None:
        def _fake(*a, **kw):
            r = httpx.Response(401, content=b"Unauthorized", request=_MOCK_REQUEST)
            r.raise_for_status()
            return r

        monkeypatch.setattr(plex_client.httpx, "request", _fake)
        c = PlexClient(BASE_URL, TOKEN)
        with pytest.raises(PlexAPIError, match="Plex returned HTTP 401"):
            c._get("/")


# ---------------------------------------------------------------------------
# check_connection
# ---------------------------------------------------------------------------


class TestCheckConnection:
    def test_ok(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(
            plex_client.httpx, "get",
            lambda *a, **k: _json_resp({"MediaContainer": {"version": "1.41.0"}}),
        )
        check = PlexClient(BASE_URL, TOKEN).check_connection()
        assert check.reachable
        assert check.authorized
        assert check.status_code == 200
        assert check.server_version == "1.41.0"
        assert check.error is None

    def test_unauthorized(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(
            plex_client.httpx, "get", lambda *a, **k: httpx.Response(401, request=_MOCK_REQUEST)
        )
        check = PlexClient(BASE_URL, "bad-tok").check_connection()
        assert check.reachable
        assert not check.authorized
        assert check.status_code == 401

    def test_unreachable_connect_error(self, monkeypatch: pytest.MonkeyPatch) -> None:
        def _raise(*a, **k):
            raise httpx.ConnectError("refused")

        monkeypatch.setattr(plex_client.httpx, "get", _raise)
        check = PlexClient(BASE_URL, TOKEN).check_connection()
        assert not check.reachable
        assert not check.authorized
        assert check.error is not None
        assert TOKEN not in check.error

    def test_unreachable_timeout(self, monkeypatch: pytest.MonkeyPatch) -> None:
        def _raise(*a, **k):
            raise httpx.TimeoutException("timed out")

        monkeypatch.setattr(plex_client.httpx, "get", _raise)
        check = PlexClient(BASE_URL, TOKEN).check_connection()
        assert not check.reachable
        assert "TimeoutException" in (check.error or "")

    def test_non_json_response_is_handled(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(
            plex_client.httpx, "get",
            lambda *a, **k: _text_resp("<MediaContainer/>"),
        )
        check = PlexClient(BASE_URL, TOKEN).check_connection()
        assert check.reachable
        assert check.server_version is None  # non-JSON → no version parse


# ---------------------------------------------------------------------------
# server endpoints
# ---------------------------------------------------------------------------


class TestMachineIdentifier:
    def test_extracts_machine_id(self, monkeypatch: pytest.MonkeyPatch) -> None:
        def _fake(*a, **kw):
            return _json_resp(
                {"MediaContainer": {"machineIdentifier": "deadbeef1234"}}
            )

        monkeypatch.setattr(plex_client.httpx, "request", _fake)
        c = PlexClient(BASE_URL, TOKEN)
        assert c.machine_identifier() == "deadbeef1234"


# ---------------------------------------------------------------------------
# library endpoints
# ---------------------------------------------------------------------------


class TestListLibrarySections:
    def test_parses_directory_items(self, monkeypatch: pytest.MonkeyPatch) -> None:
        def _fake(*a, **kw):
            return _json_resp({
                "MediaContainer": {
                    "Directory": [
                        {"key": "1", "title": "Music", "type": "artist"},
                        {"key": "2", "title": "Movies", "type": "movie"},
                    ]
                }
            })

        monkeypatch.setattr(plex_client.httpx, "request", _fake)
        c = PlexClient(BASE_URL, TOKEN)
        sections = c.list_library_sections()
        assert len(sections) == 2
        assert sections[0] == LibrarySectionResult(key="1", title="Music", type="artist")

    def test_empty_directory(self, monkeypatch: pytest.MonkeyPatch) -> None:
        def _fake(*a, **kw):
            return _json_resp({"MediaContainer": {}})

        monkeypatch.setattr(plex_client.httpx, "request", _fake)
        c = PlexClient(BASE_URL, TOKEN)
        assert c.list_library_sections() == []


# ---------------------------------------------------------------------------
# section tracks
# ---------------------------------------------------------------------------


def _track_dict(
    rating_key: str = "100",
    title: str = "Test Track",
    parent_rating_key: str = "10",
    parent_title: str = "Test Album",
    grandparent_title: str = "Test Artist",
    added_at: int = 1700000000,
    music_analysis_version: bool = False,
) -> dict:
    d: dict[str, Any] = {
        "ratingKey": rating_key,
        "title": title,
        "parentTitle": parent_title,
        "grandparentTitle": grandparent_title,
        "addedAt": added_at,
    }
    if parent_rating_key:
        d["parentRatingKey"] = parent_rating_key
    if music_analysis_version:
        d["musicAnalysisVersion"] = 1
    return d


class TestGetSectionTracks:
    def test_parses_tracks(self, monkeypatch: pytest.MonkeyPatch) -> None:
        def _fake(*a, **kw):
            return _json_resp({
                "MediaContainer": {
                    "Metadata": [
                        _track_dict("1", "Song A", "10", "Album", "Artist"),
                        _track_dict(
                            "2", "Song B", "10", "Album", "Artist",
                            music_analysis_version=True,
                        ),
                    ]
                }
            })

        monkeypatch.setattr(plex_client.httpx, "request", _fake)
        c = PlexClient(BASE_URL, TOKEN)
        tracks = c.get_section_tracks("1")
        assert len(tracks) == 2
        assert tracks[0].rating_key == "1"
        assert tracks[0].title == "Song A"
        assert tracks[0].parent_rating_key == "10"
        assert tracks[0].grandparent_title == "Artist"
        assert not tracks[0].has_sonic_analysis
        assert tracks[1].has_sonic_analysis

    def test_empty_section(self, monkeypatch: pytest.MonkeyPatch) -> None:
        def _fake(*a, **kw):
            return _json_resp({"MediaContainer": {}})

        monkeypatch.setattr(plex_client.httpx, "request", _fake)
        c = PlexClient(BASE_URL, TOKEN)
        assert c.get_section_tracks("1") == []

    def test_missing_parent_fields(self, monkeypatch: pytest.MonkeyPatch) -> None:
        def _fake(*a, **kw):
            return _json_resp({
                "MediaContainer": {
                    "Metadata": [
                        {"ratingKey": "99", "title": "Orphan", "addedAt": 1700000000}
                    ]
                }
            })

        monkeypatch.setattr(plex_client.httpx, "request", _fake)
        c = PlexClient(BASE_URL, TOKEN)
        t = c.get_section_tracks("1")[0]
        assert t.parent_rating_key is None
        assert t.parent_title is None
        assert t.grandparent_title is None


# ---------------------------------------------------------------------------
# album tracks  (uses _parse_media_item — same parser as get_section_tracks)
# ---------------------------------------------------------------------------


class TestGetAlbumTracks:
    def test_uses_correct_path(self, monkeypatch: pytest.MonkeyPatch) -> None:
        called: list[str] = []

        def _fake(method, url, **kw):
            called.append(url)
            return _json_resp({"MediaContainer": {"Metadata": [_track_dict("1")]}})

        monkeypatch.setattr(plex_client.httpx, "request", _fake)
        c = PlexClient(BASE_URL, TOKEN)
        c.get_album_tracks("42")
        assert called[0] == "http://localhost:32400/library/metadata/42/children"


# ---------------------------------------------------------------------------
# playlists
# ---------------------------------------------------------------------------


def _playlist_dict(rating_key: str = "1", title: str = "My Mix") -> dict:
    return {"ratingKey": rating_key, "title": title}


class TestFindPlaylist:
    def test_found_by_exact_name(self, monkeypatch: pytest.MonkeyPatch) -> None:
        def _fake(*a, **kw):
            return _json_resp({
                "MediaContainer": {
                    "Metadata": [
                        _playlist_dict("1", "Chill"),
                        _playlist_dict("2", "Workout"),
                    ]
                }
            })

        monkeypatch.setattr(plex_client.httpx, "request", _fake)
        c = PlexClient(BASE_URL, TOKEN)
        result = c.find_playlist("Chill")
        assert result is not None
        assert result.rating_key == "1"

    def test_not_found_returns_none(self, monkeypatch: pytest.MonkeyPatch) -> None:
        def _fake(*a, **kw):
            return _json_resp({"MediaContainer": {"Metadata": []}})

        monkeypatch.setattr(plex_client.httpx, "request", _fake)
        c = PlexClient(BASE_URL, TOKEN)
        assert c.find_playlist("Nope") is None

    def test_case_sensitive_and_returns_playlist(self, monkeypatch: pytest.MonkeyPatch) -> None:
        def _fake(*a, **kw):
            return _json_resp({
                "MediaContainer": {"Metadata": [
                    {"ratingKey": "1", "title": "chill"}
                ]}
            })

        monkeypatch.setattr(plex_client.httpx, "request", _fake)
        c = PlexClient(BASE_URL, TOKEN)
        assert c.find_playlist("Chill") is None
        result = c.find_playlist("chill")
        assert result is not None
        assert result.rating_key == "1"

    def test_passes_playlist_type_audio(self, monkeypatch: pytest.MonkeyPatch) -> None:
        called: dict[str, Any] = {}

        def _fake(method, url, **kw):
            called.update(kw)
            return _json_resp({"MediaContainer": {"Metadata": []}})

        monkeypatch.setattr(plex_client.httpx, "request", _fake)
        c = PlexClient(BASE_URL, TOKEN)
        c.find_playlist("x")
        assert called.get("params", {}).get("playlistType") == "audio"


class TestListPlaylists:
    def test_returns_playlist_results(self, monkeypatch: pytest.MonkeyPatch) -> None:
        def _fake(*a, **kw):
            return _json_resp({
                "MediaContainer": {
                    "Metadata": [
                        _playlist_dict("1", "A"),
                        _playlist_dict("2", "B"),
                    ]
                }
            })

        monkeypatch.setattr(plex_client.httpx, "request", _fake)
        c = PlexClient(BASE_URL, TOKEN)
        result = c.list_playlists()
        assert result == [
            Playlist(rating_key="1", title="A"),
            Playlist(rating_key="2", title="B"),
        ]


class TestGetPlaylistTracks:
    def test_returns_media_items(self, monkeypatch: pytest.MonkeyPatch) -> None:
        def _fake(*a, **kw):
            return _json_resp({
                "MediaContainer": {
                    "Metadata": [
                        {"ratingKey": "100", "title": "Track A"},
                        {"ratingKey": "200", "title": "Track B"},
                    ]
                }
            })

        monkeypatch.setattr(plex_client.httpx, "request", _fake)
        c = PlexClient(BASE_URL, TOKEN)
        items = c.get_playlist_tracks("1")
        assert len(items) == 2
        assert isinstance(items[0], MediaItem)
        assert items[0].rating_key == "100"
        assert items[0].title == "Track A"


class TestCreatePlaylist:
    def test_creates_and_returns_result(self, monkeypatch: pytest.MonkeyPatch) -> None:
        calls: list[dict[str, Any]] = []

        def _fake(method, url, **kw):
            calls.append({"method": method, "url": url, **kw})
            # machine_identifier call
            if method == "GET" and url.endswith("/") and "playlists" not in url:
                return _json_resp(
                    {"MediaContainer": {"machineIdentifier": "abc123"}}
                )
            if url.endswith("/playlists") and method == "POST":
                return _json_resp({
                    "MediaContainer": {
                        "Metadata": [{"ratingKey": "42", "title": "New Mix"}]
                    }
                })
            # find_playlist returns empty
            return _json_resp({"MediaContainer": {"Metadata": []}})

        monkeypatch.setattr(plex_client.httpx, "request", _fake)

        c = PlexClient(BASE_URL, TOKEN)
        result = c.create_playlist("New Mix", [100, 200])
        assert result == Playlist(rating_key="42", title="New Mix")

    def test_empty_ids_raises(self) -> None:
        # Need to mock machine_identifier and find_playlist first...
        # Actually the empty check happens before any HTTP call
        c = PlexClient(BASE_URL, TOKEN)
        with pytest.raises(PlexAPIError, match="none of the recommended tracks"):
            c.create_playlist("X", [])

    def test_duplicate_name_raises(self, monkeypatch: pytest.MonkeyPatch) -> None:
        def _fake(*a, **kw):
            return _json_resp({
                "MediaContainer": {
                    "Metadata": [{"ratingKey": "99", "title": "Existing"}]
                }
            })

        monkeypatch.setattr(plex_client.httpx, "request", _fake)
        c = PlexClient(BASE_URL, TOKEN)
        with pytest.raises(PlexAPIError, match="already exists"):
            c.create_playlist("Existing", [100])


class TestAddToPlaylist:
    def test_empty_ids_raises(self) -> None:
        c = PlexClient(BASE_URL, TOKEN)
        with pytest.raises(PlexAPIError, match="none of the recommended tracks"):
            c.add_to_playlist("1", [])

    def test_puts_with_metadata_uri(self, monkeypatch: pytest.MonkeyPatch) -> None:
        calls: list[dict[str, Any]] = []

        def _fake(method, url, **kw):
            calls.append({"method": method, "url": url, **kw})
            # machine_identifier call
            if method == "GET" and url.endswith("/") and "playlists" not in url:
                return _json_resp(
                    {"MediaContainer": {"machineIdentifier": "m1"}}
                )
            return _empty_200()

        monkeypatch.setattr(plex_client.httpx, "request", _fake)

        c = PlexClient(BASE_URL, TOKEN)
        c.add_to_playlist("1", [100, 200])

        put_call = [x for x in calls if x["method"] == "PUT"][0]
        assert put_call["url"] == "http://localhost:32400/playlists/1/items"
        assert "server://m1/" in put_call["params"]["uri"]


class TestDeletePlaylist:
    def test_sends_delete(self, monkeypatch: pytest.MonkeyPatch) -> None:
        calls: list[dict[str, Any]] = []

        def _fake(method, url, **kw):
            calls.append({"method": method, "url": url})
            return _empty_200()

        monkeypatch.setattr(plex_client.httpx, "request", _fake)
        c = PlexClient(BASE_URL, TOKEN)
        c.delete_playlist("99")
        assert calls[0] == {
            "method": "DELETE",
            "url": "http://localhost:32400/playlists/99",
        }


# ---------------------------------------------------------------------------
# metadata endpoints
# ---------------------------------------------------------------------------


class TestGetMetadata:
    def test_parses_media_item(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(
            plex_client.httpx, "request",
            lambda *a, **kw: _json_resp({
                "MediaContainer": {
                    "Metadata": [{
                        "ratingKey": "55",
                        "title": "Bohemian Rhapsody",
                        "type": "track",
                        "addedAt": 1700000000,
                        "duration": 355000,
                        "Genre": [{"tag": "Rock", "id": 1}],
                    }]
                }
            }),
        )
        c = PlexClient(BASE_URL, TOKEN)
        item = c.get_metadata("55")
        assert item is not None
        assert item.rating_key == "55"
        assert item.title == "Bohemian Rhapsody"
        assert item.type == "track"
        assert item.duration == 355000
        assert len(item.genres) == 1
        assert item.genres[0].tag == "Rock"

    def test_empty_returns_none(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(
            plex_client.httpx, "request",
            lambda *a, **kw: _json_resp({"MediaContainer": {}}),
        )
        c = PlexClient(BASE_URL, TOKEN)
        assert c.get_metadata("99") is None


class TestGetMetadataChildren:
    def test_returns_media_items(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(
            plex_client.httpx, "request",
            lambda *a, **kw: _json_resp({
                "MediaContainer": {
                    "Metadata": [
                        {"ratingKey": "1", "title": "Track 1", "type": "track"},
                        {"ratingKey": "2", "title": "Track 2", "type": "track"},
                    ]
                }
            }),
        )
        c = PlexClient(BASE_URL, TOKEN)
        items = c.get_metadata_children("10")
        assert len(items) == 2
        assert all(isinstance(it, MediaItem) for it in items)
        assert items[0].title == "Track 1"


class TestGetSimilar:
    def test_returns_media_items(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(
            plex_client.httpx, "request",
            lambda *a, **kw: _json_resp({
                "MediaContainer": {
                    "Metadata": [
                        {"ratingKey": "200", "title": "Similar Track", "type": "track"}
                    ]
                }
            }),
        )
        c = PlexClient(BASE_URL, TOKEN)
        items = c.get_similar("100")
        assert len(items) == 1
        assert items[0].title == "Similar Track"


# ---------------------------------------------------------------------------
# recently added
# ---------------------------------------------------------------------------


class TestGetRecentlyAdded:
    def test_all_recent(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(
            plex_client.httpx, "request",
            lambda *a, **kw: _json_resp({
                "MediaContainer": {
                    "Metadata": [
                        {"ratingKey": "1", "title": "New", "type": "track", "addedAt": 1700000000}
                    ]
                }
            }),
        )
        c = PlexClient(BASE_URL, TOKEN)
        items = c.get_recently_added()
        assert len(items) == 1
        assert items[0].title == "New"

    def test_section_scoped(self, monkeypatch: pytest.MonkeyPatch) -> None:
        called: list[str] = []

        def _fake(method, url, **kw):
            called.append(url)
            return _json_resp({"MediaContainer": {"Metadata": []}})

        monkeypatch.setattr(plex_client.httpx, "request", _fake)
        c = PlexClient(BASE_URL, TOKEN)
        c.get_recently_added(section_id="3")
        assert called[0].endswith("/library/sections/3/recentlyAdded")


# ---------------------------------------------------------------------------
# item maintenance
# ---------------------------------------------------------------------------


class TestAnalyzeItem:
    def test_hits_analyze_url(self, monkeypatch: pytest.MonkeyPatch) -> None:
        called: list[str] = []

        def _fake(method, url, **kw):
            called.append(url)
            return _empty_200()

        monkeypatch.setattr(plex_client.httpx, "request", _fake)
        PlexClient(BASE_URL, TOKEN).analyze_item("55")
        assert called[0].endswith("/library/metadata/55/analyze")


class TestRefreshItem:
    def test_hits_refresh_url(self, monkeypatch: pytest.MonkeyPatch) -> None:
        called: list[str] = []

        def _fake(method, url, **kw):
            called.append(url)
            return _empty_200()

        monkeypatch.setattr(plex_client.httpx, "request", _fake)
        PlexClient(BASE_URL, TOKEN).refresh_item("55")
        assert called[0].endswith("/library/metadata/55/refresh")


class TestRunButlerTask:
    def test_posts_to_butler(self, monkeypatch: pytest.MonkeyPatch) -> None:
        called: list[dict[str, str]] = []

        def _fake(method, url, **kw):
            called.append({"method": method, "url": url})
            return _empty_200()

        monkeypatch.setattr(plex_client.httpx, "request", _fake)
        PlexClient(BASE_URL, TOKEN).run_butler_task("MusicAnalysis")
        assert called[0] == {
            "method": "POST",
            "url": "http://localhost:32400/butler/MusicAnalysis",
        }


# ---------------------------------------------------------------------------
# activities
# ---------------------------------------------------------------------------


class TestGetActivities:
    def test_json_parsing(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(
            plex_client.httpx, "request",
            lambda *a, **kw: _text_resp(
                _json.dumps({
                    "MediaContainer": {
                        "Activity": [
                            {"type": "butler", "title": "MusicAnalysis",
                             "subtitle": "Processing", "progress": "42"}
                        ]
                    }
                }),
                content_type="application/json",
            ),
        )
        c = PlexClient(BASE_URL, TOKEN)
        result = c.get_activities()
        assert len(result) == 1
        assert result[0].type == "butler"
        assert result[0].progress == 42

    def test_xml_fallback(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(
            plex_client.httpx, "request",
            lambda *a, **kw: _text_resp(
                '<?xml version="1.0"?>'
                '<MediaContainer>'
                '<Activity type="butler" title="MusicAnalysis" '
                'subtitle="Processing" progress="75"/>'
                '</MediaContainer>',
                content_type="application/xml",
            ),
        )
        c = PlexClient(BASE_URL, TOKEN)
        result = c.get_activities()
        assert len(result) == 1
        assert result[0].type == "butler"
        assert result[0].title == "MusicAnalysis"
        assert result[0].progress == 75

    def test_xml_no_content_type_header(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(
            plex_client.httpx, "request",
            lambda *a, **kw: _text_resp(
                '<?xml version="1.0"?>'
                '<MediaContainer>'
                '<Activity type="butler" title="MA" subtitle="S" progress="10"/>'
                '</MediaContainer>',
                content_type="",  # Plex sometimes omits the header
            ),
        )
        c = PlexClient(BASE_URL, TOKEN)
        result = c.get_activities()
        assert len(result) == 1
        assert result[0].progress == 10

    def test_xml_parse_error_returns_empty(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(
            plex_client.httpx, "request",
            lambda *a, **kw: _text_resp("not xml at all <<<"),
        )
        c = PlexClient(BASE_URL, TOKEN)
        assert c.get_activities() == []

    def test_no_progress_field(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(
            plex_client.httpx, "request",
            lambda *a, **kw: _text_resp(
                _json.dumps({
                    "MediaContainer": {
                        "Activity": [
                            {"type": "scanning", "title": "Scan",
                             "subtitle": "Looking..."}
                        ]
                    }
                }),
                content_type="application/json",
            ),
        )
        c = PlexClient(BASE_URL, TOKEN)
        result = c.get_activities()
        assert result[0].progress is None

    def test_non_digit_progress(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(
            plex_client.httpx, "request",
            lambda *a, **kw: _text_resp(
                _json.dumps({
                    "MediaContainer": {
                        "Activity": [
                            {"type": "x", "title": "X", "subtitle": "",
                             "progress": "unknown"}
                        ]
                    }
                }),
                content_type="application/json",
            ),
        )
        c = PlexClient(BASE_URL, TOKEN)
        assert c.get_activities()[0].progress is None


# ---------------------------------------------------------------------------
# search endpoints (new, spec-aligned)
# ---------------------------------------------------------------------------


def _hub_dict() -> dict:
    return {
        "size": 1,
        "title1": "Tracks",
        "identifier": "track",
        "Hub": [
            {
                "key": "/library/metadata/100",
                "title": "Test Track",
                "type": "track",
                "hubIdentifier": "track.search",
                "context": "search",
                "size": 1,
                "Metadata": [
                    {"ratingKey": "100", "title": "Test Track", "type": "track"}
                ],
                "more": False,
            }
        ],
        "more": False,
    }


class TestSearchLibrary:
    def test_returns_hub_results(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(
            plex_client.httpx, "request",
            lambda *a, **kw: _json_resp(
                {"MediaContainer": {"Hub": [_hub_dict()]}}
            ),
        )
        c = PlexClient(BASE_URL, TOKEN)
        results = c.search_library("1", "test")
        assert len(results) == 1
        assert results[0].title == "Tracks"
        assert len(results[0].entries) == 1
        assert isinstance(results[0].entries[0], HubEntry)
        assert results[0].entries[0].items[0].title == "Test Track"

    def test_passes_query_param(self, monkeypatch: pytest.MonkeyPatch) -> None:
        called: dict[str, Any] = {}

        def _fake(method, url, **kw):
            called.update(kw)
            return _json_resp({"MediaContainer": {"Hub": []}})

        monkeypatch.setattr(plex_client.httpx, "request", _fake)
        PlexClient(BASE_URL, TOKEN).search_library("1", "bohemian")
        assert called.get("params", {}).get("query") == "bohemian"


class TestSearchAll:
    def test_passes_query_and_limit(self, monkeypatch: pytest.MonkeyPatch) -> None:
        called: dict[str, Any] = {}

        def _fake(method, url, **kw):
            called.update(kw)
            return _json_resp({"MediaContainer": {"Hub": []}})

        monkeypatch.setattr(plex_client.httpx, "request", _fake)
        PlexClient(BASE_URL, TOKEN).search_all("queen", limit=10)
        params = called.get("params", {})
        assert params.get("query") == "queen"
        assert params.get("limit") == 10


# ---------------------------------------------------------------------------
# metadata URI construction
# ---------------------------------------------------------------------------


class TestMetadataUri:
    def test_builds_server_uri(self, monkeypatch: pytest.MonkeyPatch) -> None:
        def _fake(method, url, **kw):
            if method == "GET" and url.endswith("/") and "playlists" not in url:
                return _json_resp(
                    {"MediaContainer": {"machineIdentifier": "abc123"}}
                )
            return _json_resp({"MediaContainer": {}})

        monkeypatch.setattr(plex_client.httpx, "request", _fake)
        c = PlexClient(BASE_URL, TOKEN)
        uri = c._metadata_uri([100, 200])
        assert uri == (
            "server://abc123/com.plexapp.plugins.library"
            "/library/metadata/100,200"
        )

    def test_single_id(self, monkeypatch: pytest.MonkeyPatch) -> None:
        def _fake(method, url, **kw):
            if method == "GET" and url.endswith("/") and "playlists" not in url:
                return _json_resp(
                    {"MediaContainer": {"machineIdentifier": "m1"}}
                )
            return _json_resp({"MediaContainer": {}})

        monkeypatch.setattr(plex_client.httpx, "request", _fake)
        c = PlexClient(BASE_URL, TOKEN)
        uri = c._metadata_uri([42])
        assert uri.endswith("/library/metadata/42")
