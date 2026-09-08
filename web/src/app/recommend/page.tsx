"use client";

import { useState, useEffect, useCallback } from "react";
import Link from "next/link";
import { api } from "@/lib/api";
import { useSetupGate } from "@/lib/use-setup-gate";
import type {
  TypeaheadTrack,
  RecommendResponse,
  RecommendationItem,
  RecommendMethod,
  PlexPlaylist,
} from "@/lib/types";
import { SeedChips } from "@/components/seed-chips";
import { Typeahead } from "@/components/typeahead";
import { RecommendResults } from "@/components/recommend-results";
import { WeightControls } from "@/components/weight-controls";
import { PageHeader } from "@/components/page-header";

type Presets = Record<string, Record<string, number>>;

export default function RecommendPage() {
  const [seeds, setSeeds] = useState<TypeaheadTrack[]>([]);
  const [seedIds, setSeedIds] = useState<number[]>([]);
  const [items, setItems] = useState<RecommendationItem[]>([]);
  const [sonicCoverage, setSonicCoverage] = useState<{ candidates: number; with_vector: number } | null>(null);
  const [respWeights, setRespWeights] = useState<Record<string, number>>();
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);

  const [limit, setLimit] = useState(50);
  const [method, setMethod] = useState<RecommendMethod>("average");
  const [yearMin, setYearMin] = useState("");
  const [yearMax, setYearMax] = useState("");
  const [perArtist, setPerArtist] = useState(3);
  const [minScore, setMinScore] = useState("");

  const [presets, setPresets] = useState<Presets>({});
  const [weights, setWeights] = useState<Record<string, number>>({});
  const [preset, setPreset] = useState("balanced");

  // Save-to-Plex state
  const [playlists, setPlaylists] = useState<PlexPlaylist[]>([]);
  const [playlistName, setPlaylistName] = useState("");
  const [appendTarget, setAppendTarget] = useState("");
  const [creating, setCreating] = useState(false);
  const [appending, setAppending] = useState(false);
  const [saveError, setSaveError] = useState<string | null>(null);
  const [saveNotice, setSaveNotice] = useState<string | null>(null);

  const gate = useSetupGate();

  // Presets come from the API (single source of truth in core), not from
  // duplicated values here.
  useEffect(() => {
    api.get<Presets>("/recommend/presets")
      .then((data) => {
        setPresets(data);
        if (data.balanced) {
          setWeights({ ...data.balanced });
          setPreset("balanced");
        }
      })
      .catch(() => {});
  }, []);

  const loadPlaylists = useCallback(() => {
    api.get<PlexPlaylist[]>("/playlists")
      .then(setPlaylists)
      .catch(() => {});
  }, []);

  useEffect(() => {
    loadPlaylists();
  }, [loadPlaylists]);

  const addSeed = useCallback(
    (track: TypeaheadTrack) => {
      if (seedIds.includes(track.id)) return;
      setSeeds((prev) => [...prev, track]);
      setSeedIds((prev) => [...prev, track.id]);
    },
    [seedIds],
  );

  const removeSeed = useCallback((id: number) => {
    setSeeds((prev) => prev.filter((s) => s.id !== id));
    setSeedIds((prev) => prev.filter((i) => i !== id));
  }, []);

  function setPresetWeights(name: string) {
    setPreset(name);
    if (presets[name]) setWeights({ ...presets[name] });
  }

  function setWeight(key: string, value: number) {
    setPreset("custom");
    setWeights((prev) => ({ ...prev, [key]: value }));
  }

  useEffect(() => {
    if (seedIds.length === 0) {
      setItems([]);
      setError(null);
      return;
    }

    const timer = setTimeout(async () => {
      setLoading(true);
      try {
        const body: Record<string, string | number> = {
          seed_ids: seedIds.join(","),
          limit,
          method,
          year_min: yearMin,
          year_max: yearMax,
          max_tracks_per_artist: perArtist,
          min_score: minScore,
        };
        for (const [k, v] of Object.entries(weights)) {
          body[`w_${k}`] = String(v);
        }
        const data = await api.post<RecommendResponse>("/recommend", body);
        setItems(data.recommendations);
        setSonicCoverage(data.sonic_coverage ?? null);
        setRespWeights(data.weights);
        setError(null);
        setSaveError(null);
        setSaveNotice(null);
      } catch (e) {
        setError(String(e));
        setItems([]);
        setSonicCoverage(null);
      } finally {
        setLoading(false);
      }
    }, 300);

    return () => clearTimeout(timer);
  }, [seedIds, limit, method, yearMin, yearMax, perArtist, minScore, weights]);

  function removeItem(trackId: number) {
    setItems((prev) => prev.filter((r) => r.track_id !== trackId));
    setSaveError(null);
    setSaveNotice(null);
  }

  async function handleCreatePlaylist() {
    if (!playlistName.trim() || items.length === 0) return;
    setCreating(true);
    setSaveError(null);
    setSaveNotice(null);
    try {
      const result = await api.post<{
        name: string;
        track_count: number;
        seed_count: number;
        recommendation_count: number;
      }>("/playlists/create", {
        name: playlistName.trim(),
        seed_ids: seedIds.join(","),
        track_ids: items.map((r) => r.track_id).join(","),
      });
      setSaveNotice(
        `Created “${result.name}” with ${result.track_count} tracks ` +
          `(${result.seed_count} seeds + ${result.recommendation_count} recommendations).`,
      );
      setPlaylistName("");
      loadPlaylists();
    } catch (e) {
      setSaveError(String(e).replace("Error: ", ""));
    } finally {
      setCreating(false);
    }
  }

  async function handleAppendToPlaylist() {
    if (!appendTarget || items.length === 0) return;
    setAppending(true);
    setSaveError(null);
    setSaveNotice(null);
    try {
      const result = await api.post<{
        playlist_name: string;
        added_count: number;
      }>(
        `/playlists/${encodeURIComponent(appendTarget)}/populate`,
        { track_ids: items.map((r) => r.track_id).join(",") },
      );
      setSaveNotice(`Added ${result.added_count} tracks to “${result.playlist_name}”.`);
      setAppendTarget("");
      loadPlaylists();
    } catch (e) {
      setSaveError(String(e).replace("Error: ", ""));
    } finally {
      setAppending(false);
    }
  }

  if (gate !== "ready") {
    return (
      <div className="panel">
        <p className="muted">Loading…</p>
      </div>
    );
  }

  const selectedCount = items.length;

  return (
    <>
      <PageHeader
        eyebrow="Discover"
        title="Find your next favorite"
        description="Seed a vibe with a few tracks, tune the mix, and turn the results into a Plex playlist."
      />

      {/* Step 1 — seeds */}
      <section className="panel">
        <div className="flex items-center gap-2.5 mb-2">
          <span className="step-badge">1</span>
          <h2 className="mt-0 mb-0 text-lg font-semibold">Pick your seeds</h2>
        </div>
        <p className="muted text-sm">
          Search for a few tracks that share the vibe you want — 2 to 5 seeds usually works best.
        </p>

        <Typeahead seedIds={seedIds} onSelect={addSeed} />
        <SeedChips seeds={seeds} onRemove={removeSeed} />
      </section>

      {/* Step 2 — method + weights */}
      <section className="panel">
        <div className="flex items-center gap-2.5 mb-2">
          <span className="step-badge">2</span>
          <h2 className="mt-0 mb-0 text-lg font-semibold">Tune the mix</h2>
        </div>
        <p className="muted text-sm mb-4">
          Choose how your seeds combine, then set how strongly each signal counts.
        </p>

        <div className="mb-4">
          <p className="text-sm font-semibold mb-2">Method</p>
          <div
            className="inline-flex rounded-full border border-[var(--border)] p-0.5"
            role="group"
            aria-label="Recommendation method"
          >
            {(["average", "frequency"] as const).map((value) => (
              <button
                key={value}
                type="button"
                className={`text-xs px-3 py-1 rounded-full font-medium border-0 ${
                  method === value
                    ? "bg-[var(--brand)] text-white"
                    : "bg-transparent text-[var(--muted)]"
                } cursor-pointer`}
                onClick={() => setMethod(value)}
              >
                {value === "average" ? "Average" : "Frequency"}
              </button>
            ))}
          </div>
          <p className="muted text-xs m-0">
            {method === "average"
              ? "Scores every candidate against the seeds' combined profile in one pass."
              : "Scores each seed separately and ranks candidates by their average score across voting seeds."}
          </p>
        </div>

        <WeightControls
          weights={weights}
          presets={presets}
          preset={preset}
          onPresetChange={setPresetWeights}
          onWeightChange={setWeight}
        />
      </section>

      {/* Step 3 — filters */}
      <section className="panel">
        <div className="flex items-center gap-2.5 mb-2">
          <span className="step-badge">3</span>
          <h2 className="mt-0 mb-0 text-lg font-semibold">Narrow it down</h2>
        </div>
        <p className="muted text-sm mb-4">Optional filters to keep the results fresh and varied.</p>
        <div className="flex flex-wrap gap-x-6 gap-y-3">
          <label className="grid gap-0.5 text-sm text-[var(--muted)]">
            Limit
            <input
              type="number"
              value={limit}
              onChange={(e) => setLimit(Number(e.target.value))}
              min={1}
              max={200}
              className="w-20"
            />
          </label>
          <label className="grid gap-0.5 text-sm text-[var(--muted)]">
            Year from
            <input
              type="number"
              value={yearMin}
              onChange={(e) => setYearMin(e.target.value)}
              min={1900}
              max={2030}
              placeholder="any"
              className="w-20"
            />
          </label>
          <label className="grid gap-0.5 text-sm text-[var(--muted)]">
            Year to
            <input
              type="number"
              value={yearMax}
              onChange={(e) => setYearMax(e.target.value)}
              min={1900}
              max={2030}
              placeholder="any"
              className="w-20"
            />
          </label>
          <label className="grid gap-0.5 text-sm text-[var(--muted)]">
            Per artist
            <input
              type="number"
              value={perArtist}
              onChange={(e) => setPerArtist(Number(e.target.value))}
              min={1}
              max={20}
              className="w-20"
            />
          </label>
          <label className="grid gap-0.5 text-sm text-[var(--muted)]">
            Min score
            <input
              type="number"
              value={minScore}
              onChange={(e) => setMinScore(e.target.value)}
              min={0}
              max={1}
              step={0.01}
              placeholder="any"
              className="w-20"
            />
          </label>
        </div>
      </section>

      {error && <div className="flash flash-error">{error}</div>}

      {!seedIds.length && !error && (
        <p className="muted">Add one or more seed tracks above to get recommendations.</p>
      )}

      {loading && seedIds.length > 0 && <p className="muted">Fine-tuning&hellip;</p>}

      {!loading && seedIds.length > 0 && items.length === 0 && !error && (
        <p className="muted">
          No recommendations found. Try adjusting the filters or using different seed tracks.
        </p>
      )}

      {!loading && sonicCoverage && sonicCoverage.with_vector === 0 && (
        <div className="flash flash-warn">
          No candidate tracks have Plex sonic analysis yet, so the Sonic dimension is
          scoring neutrally. Run sonic analysis in Plex (or &ldquo;Refresh analysis&rdquo;
          on the dashboard) to enable it.
        </div>
      )}

      {/* Step 4 — results */}
      {!loading && items.length > 0 && (
        <section className="panel">
          <div className="flex items-center gap-2.5 mb-2">
            <span className="step-badge">4</span>
            <h2 className="mt-0 mb-0 text-lg font-semibold">Review your picks</h2>
            <span className="badge badge-running">{selectedCount}</span>
          </div>
          <p className="muted text-sm mb-4">
            {selectedCount} track{selectedCount === 1 ? "" : "s"} selected — click × on a track to
            drop it from the list.
          </p>

          <RecommendResults items={items} weights={respWeights} onRemove={removeItem} />
        </section>
      )}

      {/* Step 5 — save to Plex */}
      {!loading && items.length > 0 && (
        <section className="panel">
          <div className="flex items-center gap-2.5 mb-2">
            <span className="step-badge">5</span>
            <h2 className="mt-0 mb-0 text-lg font-semibold">Save to Plex</h2>
          </div>
          <p className="muted text-sm mb-4">
            Turn this selection into a playlist on your Plex server — start a new one or grow an
            existing one.
          </p>

          {saveNotice && (
            <div className="flash flash-ok">
              {saveNotice}{" "}
              <Link href="/playlists" className="underline">
                View playlists
              </Link>
            </div>
          )}
          {saveError && <div className="flash flash-error">{saveError}</div>}

          <div className="grid gap-3 lg:grid-cols-2">
            <div className="p-3 border border-[var(--border)] rounded-lg bg-[var(--bg)]">
              <p className="text-sm font-semibold mb-2">Create a new playlist</p>
              <p className="muted text-xs mb-3">
                Starts with your {seedIds.length} seed{seedIds.length === 1 ? "" : "s"}, then adds
                the {selectedCount} recommendation{selectedCount === 1 ? "" : "s"}.
              </p>
              <input
                type="text"
                value={playlistName}
                onChange={(e) => setPlaylistName(e.target.value)}
                onKeyDown={(e) => {
                  if (e.key === "Enter") void handleCreatePlaylist();
                }}
                placeholder="Playlist name, e.g. Golden hour soul"
                aria-label="New playlist name"
                className="w-full mb-2"
              />
              <button
                type="button"
                className="btn btn-primary w-full"
                onClick={() => void handleCreatePlaylist()}
                disabled={creating || !playlistName.trim()}
              >
                {creating ? "Creating…" : "Create a new playlist"}
              </button>
            </div>

            <div className="p-3 border border-[var(--border)] rounded-lg bg-[var(--bg)]">
              <p className="text-sm font-semibold mb-2">Append to playlist</p>
              <p className="muted text-xs mb-3">
                Adds the {selectedCount} recommendation{selectedCount === 1 ? "" : "s"} to an
                existing Plex playlist.
              </p>
              {playlists.length === 0 ? (
                <p className="muted text-xs m-0">
                  No Plex playlists found — create a new one first.
                </p>
              ) : (
                <>
                  <select
                    value={appendTarget}
                    onChange={(e) => setAppendTarget(e.target.value)}
                    aria-label="Existing playlist"
                    className="w-full mb-2"
                  >
                    <option value="">Choose a playlist…</option>
                    {playlists.map((p) => (
                      <option key={p.rating_key} value={p.rating_key}>
                        {p.name} ({p.track_count} track{p.track_count === 1 ? "" : "s"})
                      </option>
                    ))}
                  </select>
                  <button
                    type="button"
                    className="btn btn-secondary w-full"
                    onClick={() => void handleAppendToPlaylist()}
                    disabled={appending || !appendTarget}
                  >
                    {appending ? "Appending…" : "Append to playlist"}
                  </button>
                </>
              )}
            </div>
          </div>
        </section>
      )}
    </>
  );
}
