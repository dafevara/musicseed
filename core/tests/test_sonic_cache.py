"""Sonic vector cache reloads when the Plex blobs database changes."""

import musicseed.sonic as sonic


class _FakeVectors:
    pass


def test_get_sonic_vectors_reloads_when_signature_changes(monkeypatch):
    sonic.reset_sonic_vectors()
    calls = {"n": 0}

    def fake_load(**kwargs):
        calls["n"] += 1
        return _FakeVectors()

    monkeypatch.setattr(sonic, "_blobs_signature", lambda p: ("sig-a",))
    monkeypatch.setattr(sonic, "load_sonic_vectors", fake_load)

    try:
        v1 = sonic.get_sonic_vectors()
        v2 = sonic.get_sonic_vectors()
        assert v1 is v2  # unchanged signature -> cached
        assert calls["n"] == 1

        monkeypatch.setattr(sonic, "_blobs_signature", lambda p: ("sig-b",))
        v3 = sonic.get_sonic_vectors()
        assert v3 is not v1  # changed signature -> reloaded
        assert calls["n"] == 2
    finally:
        sonic.reset_sonic_vectors()


def test_reset_sonic_vectors_drops_cache(monkeypatch):
    sonic.reset_sonic_vectors()
    calls = {"n": 0}

    def fake_load(**kwargs):
        calls["n"] += 1
        return _FakeVectors()

    monkeypatch.setattr(sonic, "_blobs_signature", lambda p: ("sig-a",))
    monkeypatch.setattr(sonic, "load_sonic_vectors", fake_load)

    try:
        sonic.get_sonic_vectors()
        sonic.reset_sonic_vectors()
        sonic.get_sonic_vectors()
        assert calls["n"] == 2
    finally:
        sonic.reset_sonic_vectors()
