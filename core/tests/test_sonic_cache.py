"""The context's sonic-vector cache reloads when the Plex blobs DB changes."""

import musicseed.context as context_module
from musicseed.config import Config
from musicseed.context import MusicSeedContext


class _FakeVectors:
    pass


def test_sonic_vectors_cached_until_signature_changes(monkeypatch):
    ctx = MusicSeedContext(Config())
    calls = {"n": 0}

    def fake_load(**kwargs):
        calls["n"] += 1
        return _FakeVectors()

    monkeypatch.setattr(context_module, "blobs_signature", lambda p: ("sig-a",))
    monkeypatch.setattr(context_module, "load_sonic_vectors", fake_load)

    v1 = ctx.sonic_vectors
    v2 = ctx.sonic_vectors
    assert v1 is v2  # unchanged signature -> cached
    assert calls["n"] == 1

    monkeypatch.setattr(context_module, "blobs_signature", lambda p: ("sig-b",))
    v3 = ctx.sonic_vectors
    assert v3 is not v1  # changed signature -> reloaded
    assert calls["n"] == 2


def test_reset_sonic_vectors_drops_cache(monkeypatch):
    ctx = MusicSeedContext(Config())
    calls = {"n": 0}

    def fake_load(**kwargs):
        calls["n"] += 1
        return _FakeVectors()

    monkeypatch.setattr(context_module, "blobs_signature", lambda p: ("sig-a",))
    monkeypatch.setattr(context_module, "load_sonic_vectors", fake_load)

    ctx.sonic_vectors
    ctx.reset_sonic_vectors()
    ctx.sonic_vectors
    assert calls["n"] == 2


def test_get_sonic_vectors_delegates_to_default_context(monkeypatch):
    import musicseed.sonic as sonic
    from musicseed.context import reset_context, set_context

    ctx = MusicSeedContext(Config())
    monkeypatch.setattr(context_module, "blobs_signature", lambda p: ("sig-a",))
    monkeypatch.setattr(context_module, "load_sonic_vectors", lambda **kwargs: _FakeVectors())

    set_context(ctx)
    try:
        assert sonic.get_sonic_vectors() is ctx.sonic_vectors
    finally:
        reset_context()
