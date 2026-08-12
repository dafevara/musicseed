"use client";

import { useEffect, useRef, useState } from "react";
import { api } from "@/lib/api";
import { useSetupGate } from "@/lib/use-setup-gate";
import type { RecommendationItem, PopulatePreview, RecommendResponse, TypeaheadTrack } from "@/lib/types";
import { Typeahead } from "@/components/typeahead";
import { SeedChips } from "@/components/seed-chips";
import { RecommendResults } from "@/components/recommend-results";
import { WeightControls } from "@/components/weight-controls";

function weightsQuery(weights: Record<string, number>): string {
  return Object.entries(weights)
    .map(([k, v]) => `w_${k}=${v}`)
    .join("&");
}

interface PlexPlaylist {
  name: string;
  rating_key: string;
  track_count: number;
}

export default function PlaylistsPage() {
  const [playlists, setPlaylists] = useState<PlexPlaylist[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  // Create state
  const [showCreate, setShowCreate] = useState(false);
  const [newName, setNewName] = useState("");
  const [seeds, setSeeds] = useState<TypeaheadTrack[]>([]);
  const [seedIds, setSeedIds] = useState<number[]>([]);
  const [createPreview, setCreatePreview] = useState<RecommendationItem[] | null>(null);
  const [createWeights, setCreateWeights] = useState<Record<string, number>>();
  const [previewing, setPreviewing] = useState(false);
  const [creating, setCreating] = useState(false);
  const [createResult, setCreateResult] = useState<string | null>(null);

  // Populate state
  const [populatePreview, setPopulatePreview] = useState<PopulatePreview | null>(null);
  const [populateItems, setPopulateItems] = useState<RecommendationItem[]>([]);
  const [populating, setPopulating] = useState<string | null>(null);
  const [previewingPlaylist, setPreviewingPlaylist] = useState<string | null>(null);
  const [populateResult, setPopulateResult] = useState<string | null>(null);
  const [populateError, setPopulateError] = useState<string | null>(null);
  const [populateWeights, setPopulateWeights] = useState<Record<string, number>>({});
  const [populatePreset, setPopulatePreset] = useState("balanced");
  const [presets, setPresets] = useState<Record<string, Record<string, number>>>({});
  const [showAdvanced, setShowAdvanced] = useState(false);
  const removedPopulateIdsRef = useRef<Set<number>>(new Set());

  const gate = useSetupGate();

  useEffect(() => {
    api.get<PlexPlaylist[]>("/playlists")
      .then(setPlaylists)
      .catch((e) => {
        setError(String(e).replace("Error: ", "") || "Could not load playlists.");
      })
      .finally(() => setLoading(false));
  }, []);

  useEffect(() => {
    api.get<Record<string, Record<string, number>>>("/recommend/presets")
      .then((data) => {
        setPresets(data);
        if (data.balanced) setPopulateWeights({ ...data.balanced });
      })
      .catch(() => {});
  }, []);

  function addSeed(track: TypeaheadTrack) {
    if (seedIds.includes(track.id)) return;
    setSeeds((prev) => [...prev, track]);
    setSeedIds((prev) => [...prev, track.id]);
  }

  function removeSeed(id: number) {
    setSeeds((prev) => prev.filter((s) => s.id !== id));
    setSeedIds((prev) => prev.filter((i) => i !== id));
  }

  function resetCreate() {
    setShowCreate(false);
    setNewName("");
    setSeeds([]);
    setSeedIds([]);
    setCreatePreview(null);
  }

  async function handlePreviewCreate() {
    if (!newName.trim() || seedIds.length === 0) return;
    setPreviewing(true);
    setCreateResult(null);
    try {
      const data = await api.post<RecommendResponse>("/recommend", {
        seed_ids: seedIds.join(","),
        limit: 50,
      });
      setCreatePreview(data.recommendations);
      setCreateWeights(data.weights);
    } catch (e) {
      setCreatePreview(null);
      setCreateResult(`Error: ${String(e).replace("Error: ", "")}`);
    } finally {
      setPreviewing(false);
    }
  }

  async function handleConfirmCreate() {
    if (!newName.trim() || seedIds.length === 0) return;
    setCreating(true);
    setCreateResult(null);
    try {
      const result = await api.post<{
        name: string;
        track_count: number;
        seed_count: number;
        recommendation_count: number;
      }>("/playlists/create", {
        name: newName.trim(),
        seed_ids: seedIds.join(","),
        limit: 50,
      });
      setCreateResult(
        `Created "${result.name}" with ${result.track_count} tracks ` +
        `(${result.seed_count} seeds + ${result.recommendation_count} recommendations).`
      );
      resetCreate();
      const updated = await api.get<PlexPlaylist[]>("/playlists");
      setPlaylists(updated);
    } catch (e) {
      setCreateResult(`Error: ${String(e).replace("Error: ", "")}`);
    } finally {
      setCreating(false);
    }
  }

  async function handlePreviewPopulate(name: string) {
    setPopulatePreview(null);
    setPopulateItems([]);
    setPopulateResult(null);
    setPopulateError(null);
    setPreviewingPlaylist(name);
    setShowAdvanced(false);
    setPopulatePreset("balanced");
    if (presets.balanced) setPopulateWeights({ ...presets.balanced });
    removedPopulateIdsRef.current = new Set();
    try {
      const data = await api.get<PopulatePreview>(
        `/playlists/${encodeURIComponent(name)}/preview?limit=10`
      );
      setPopulatePreview(data);
      setPopulateItems(data.recommendations);
    } catch (e) {
      setPopulateError(String(e).replace("Error: ", ""));
    } finally {
      setPreviewingPlaylist(null);
    }
  }

  function removePopulateItem(trackId: number) {
    removedPopulateIdsRef.current.add(trackId);
    setPopulateItems((prev) => prev.filter((r) => r.track_id !== trackId));
  }

  function setPopulatePresetWeights(name: string) {
    setPopulatePreset(name);
    if (presets[name]) setPopulateWeights({ ...presets[name] });
  }

  function setPopulateWeight(key: string, value: number) {
    setPopulatePreset("custom");
    setPopulateWeights((prev) => ({ ...prev, [key]: value }));
  }

  // Recompute the preview (debounced) whenever the user changes weights in
  // the advanced panel.
  useEffect(() => {
    const name = populatePreview?.playlist_name;
    if (!showAdvanced || !name) return;

    const timer = setTimeout(async () => {
      try {
        const qs = weightsQuery(populateWeights);
        const data = await api.get<PopulatePreview>(
          `/playlists/${encodeURIComponent(name)}/preview?limit=10${qs ? `&${qs}` : ""}`
        );
        setPopulatePreview(data);
        setPopulateItems(
          data.recommendations.filter(
            (r) => !removedPopulateIdsRef.current.has(r.track_id)
          )
        );
      } catch (e) {
        setPopulateError(String(e).replace("Error: ", ""));
      }
    }, 300);

    return () => clearTimeout(timer);
  }, [populatePreview?.playlist_name, showAdvanced, populateWeights]);

  async function handleConfirmPopulate(name: string) {
    const trackIds = populateItems.map((r) => r.track_id);
    if (trackIds.length === 0) return;

    setPopulating(name);
    setPopulateResult(null);
    setPopulateError(null);
    try {
      const result = await api.post<{
        playlist_name: string;
        added_count: number;
        playlist_track_count: number;
      }>(`/playlists/${encodeURIComponent(name)}/populate`, {
        limit: 10,
        track_ids: trackIds.join(","),
      });
      setPopulateResult(
        `Added ${result.added_count} tracks to "${result.playlist_name}" ` +
        `(now ${result.playlist_track_count + result.added_count} tracks).`
      );
      setPopulatePreview(null);
      setPopulateItems([]);
      const updated = await api.get<PlexPlaylist[]>("/playlists");
      setPlaylists(updated);
    } catch (e) {
      setPopulateError(String(e).replace("Error: ", ""));
    } finally {
      setPopulating(null);
    }
  }

  if (gate !== "ready") {
    return (
      <div className="panel">
        <p className="muted">Loading…</p>
      </div>
    );
  }

  if (loading) {
    return (
      <div className="panel">
        <p className="muted">Loading playlists&hellip;</p>
      </div>
    );
  }

  return (
    <>
      <section className="panel">
        <div className="flex items-baseline justify-between flex-wrap gap-2">
          <h2 className="mt-0 text-lg font-semibold">Plex Playlists</h2>
          <button
            className="btn btn-primary"
            onClick={() => { setShowCreate(!showCreate); setCreatePreview(null); setCreateResult(null); }}
          >
            {showCreate ? "Cancel" : "New playlist"}
          </button>
        </div>

        {error && <div className="flash flash-error">{error}</div>}

        {createResult && (
          <div className={`flash ${createResult.startsWith("Error") ? "flash-error" : "flash-ok"}`}>
            {createResult}
          </div>
        )}

        {populateResult && (
          <div className="flash flash-ok mt-3">{populateResult}</div>
        )}
        {populateError && (
          <div className="flash flash-error mt-3">{populateError}</div>
        )}

        {showCreate && (
          <div className="mb-4 p-3 border border-[var(--border)] rounded-lg">
            <h3 className="mt-0 text-base font-semibold">Create from seeds</h3>
            <label className="grid gap-1 text-sm mb-3">
              Playlist name
              <input
                type="text"
                value={newName}
                onChange={(e) => setNewName(e.target.value)}
                placeholder="My MusicSeed playlist"
                className="max-w-xs"
              />
            </label>

            <p className="text-sm text-[var(--muted)] mb-2">
              Search for seed tracks (same as on the Recommend page):
            </p>
            <Typeahead seedIds={seedIds} onSelect={addSeed} />
            <SeedChips seeds={seeds} onRemove={removeSeed} />

            {createPreview && (
              <div className="mt-3 p-3 border border-[var(--border)] rounded-lg bg-[var(--bg)]">
                <p className="text-sm mb-1">
                  {createPreview.length} recommended tracks will be added to &ldquo;{newName.trim()}&rdquo;
                  alongside your {seedIds.length} seed{seedIds.length !== 1 ? "s" : ""}.
                </p>
                <RecommendResults items={createPreview} weights={createWeights} />
                <div className="flex gap-2 mt-3">
                  <button
                    className="btn btn-primary"
                    onClick={handleConfirmCreate}
                    disabled={creating}
                  >
                    {creating ? "Creating…" : "Confirm & create"}
                  </button>
                  <button
                    className="btn btn-secondary"
                    onClick={() => setCreatePreview(null)}
                    disabled={creating}
                  >
                    Back
                  </button>
                </div>
              </div>
            )}

            {!createPreview && (
              <button
                className="btn btn-primary mt-3"
                onClick={handlePreviewCreate}
                disabled={previewing || !newName.trim() || seedIds.length === 0}
              >
                {previewing ? "Previewing…" : "Preview"}
              </button>
            )}
          </div>
        )}

        {playlists.length === 0 && !error && (
          <p className="muted text-sm">
            No Plex playlists found. Create one above or use Plex to make one first.
          </p>
        )}

        {playlists.length > 0 && (
          <ul className="list-none m-0 p-0 grid gap-1 mt-3">
            {playlists.map((p) => {
              const isPreviewing = previewingPlaylist === p.name;
              const isPopulating = populating === p.name;
              const showPreview = populatePreview?.playlist_name === p.name;

              return (
                <li
                  key={p.rating_key}
                  className="px-3 py-2 rounded-md odd:bg-[var(--bg)]"
                >
                  <div className="flex items-center justify-between gap-4">
                    <div className="min-w-0">
                      <span className="font-medium truncate block">{p.name}</span>
                      <span className="text-xs text-[var(--muted)]">
                        {p.track_count} track{p.track_count !== 1 ? "s" : ""}
                      </span>
                    </div>
                    <button
                      className="btn btn-secondary text-sm px-3 py-1.5"
                      onClick={() => handlePreviewPopulate(p.name)}
                      disabled={isPopulating || isPreviewing}
                    >
                      {isPopulating ? "Adding…" : isPreviewing ? "Previewing…" : "Populate"}
                    </button>
                  </div>

                  {showPreview && (
                    <div className="mt-3 p-3 border border-[var(--border)] rounded-lg">
                      <h3 className="mt-0 text-base font-semibold">
                        Preview additions to &ldquo;{populatePreview.playlist_name}&rdquo;
                      </h3>
                      <p className="text-sm muted">
                        {populatePreview.playlist_track_count} tracks currently,{" "}
                        {populateItems.length} recommended to add.
                      </p>

                      {showAdvanced && (
                        <div className="mt-3 mb-3 p-3 border border-[var(--border)] rounded-lg bg-[var(--bg)]">
                          <p className="text-sm font-semibold mb-2">Scoring weights</p>
                          <WeightControls
                            weights={populateWeights}
                            presets={presets}
                            preset={populatePreset}
                            onPresetChange={setPopulatePresetWeights}
                            onWeightChange={setPopulateWeight}
                          />
                        </div>
                      )}

                      {populateItems.length === 0 ? (
                        <p className="text-sm text-[var(--muted)]">
                          No tracks selected — nothing to add.
                        </p>
                      ) : (
                        <RecommendResults
                          items={populateItems}
                          weights={populatePreview.weights}
                          onRemove={removePopulateItem}
                        />
                      )}
                      <div className="flex flex-wrap gap-2 mt-3">
                        <button
                          className="btn btn-primary"
                          onClick={() => handleConfirmPopulate(populatePreview.playlist_name)}
                          disabled={isPopulating || populateItems.length === 0}
                        >
                          {isPopulating ? "Adding…" : "Confirm & add"}
                        </button>
                        <button
                          className="btn btn-secondary"
                          onClick={() => {
                            setPopulatePreview(null);
                            setPopulateItems([]);
                            setShowAdvanced(false);
                          }}
                          disabled={isPopulating}
                        >
                          Cancel
                        </button>
                        <button
                          className="btn btn-secondary"
                          onClick={() => setShowAdvanced((v) => !v)}
                          disabled={isPopulating}
                        >
                          {showAdvanced ? "Hide weights" : "Advanced"}
                        </button>
                      </div>
                    </div>
                  )}
                </li>
              );
            })}
          </ul>
        )}
      </section>
    </>
  );
}
