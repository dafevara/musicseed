"use client";

import { Suspense, useEffect, useRef, useState } from "react";
import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { api } from "@/lib/api";
import { CalculationProgress } from "@/components/calculation-progress";
import { previewQuery, usePlaylistPreview } from "@/lib/use-playlist-preview";
import { browserPreviewStorage, readSavedPreview } from "@/lib/preview-job";
import { useSetupGate } from "@/lib/use-setup-gate";
import type { PopulateMethod, PopulatePreview, RecommendationItem } from "@/lib/types";
import { RecommendResults } from "@/components/recommend-results";
import { WeightControls } from "@/components/weight-controls";

export default function PopulatePlaylistPage() {
  return (
    <Suspense fallback={<div className="panel"><p className="muted">Loading…</p></div>}>
      <PopulatePlaylistPageInner />
    </Suspense>
  );
}

function PopulatePlaylistPageInner() {
  const gate = useSetupGate();
  const router = useRouter();
  const playlistId = useSearchParams().get("id") ?? "";

  const [preview, setPreview] = useState<PopulatePreview | null>(null);
  const [items, setItems] = useState<RecommendationItem[]>([]);
  const [weights, setWeights] = useState<Record<string, number>>({});
  const [preset, setPreset] = useState("balanced");
  const [method, setMethod] = useState<PopulateMethod>("average");
  const [presets, setPresets] = useState<Record<string, Record<string, number>>>({});
  const [initialized, setInitialized] = useState(false);
  const [restoredQuery, setRestoredQuery] = useState<string | null>(null);
  const [revision, setRevision] = useState(0);
  const [populating, setPopulating] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const removedIdsRef = useRef<Set<number>>(new Set());
  const calculation = usePlaylistPreview(initialized && playlistId && gate === "ready"
    ? { playlistId, query: restoredQuery ?? previewQuery(weights, method) } : null, revision);
  const loading = !initialized || (calculation.busy && !preview);
  const refreshing = calculation.busy && !!preview;

  useEffect(() => {
    if (!playlistId) {
      router.replace("/playlists");
    }
  }, [playlistId, router]);

  useEffect(() => {
    let active = true;
    setInitialized(false);
    setPreview(null);
    setItems([]);
    removedIdsRef.current.clear();
    const saved = readSavedPreview(browserPreviewStorage);
    const restored = saved?.playlistId === playlistId ? saved.query : null;
    api.get<Record<string, Record<string, number>>>("/recommend/presets")
      .then((data) => {
        if (!active) return;
        setPresets(data);
        const query = new URLSearchParams(restored ?? "");
        const nextWeights = { ...data.balanced };
        for (const key of Object.keys(nextWeights)) {
          const value = query.get(`w_${key}`);
          if (value !== null && Number.isFinite(Number(value))) nextWeights[key] = Number(value);
        }
        setWeights(nextWeights);
        setMethod(query.get("method") === "frequency" ? "frequency" : "average");
        setRestoredQuery(restored);
        if (restored) setPreset("custom");
      })
      .catch((e) => { if (active) setError(String(e).replace("Error: ", "")); })
      .finally(() => { if (active) setInitialized(true); });
    return () => { active = false; };
  }, [playlistId]);

  useEffect(() => {
    if (!calculation.result) return;
    setPreview(calculation.result);
    setItems(calculation.result.recommendations.filter((r) => !removedIdsRef.current.has(r.track_id)));
  }, [calculation.result]);

  function setPresetWeights(name: string) {
    if (populating) return;
    setRestoredQuery(null);
    setPreset(name);
    if (presets[name]) setWeights({ ...presets[name] });
  }

  async function handleConfirm() {
    const trackIds = items.map((r) => r.track_id);
    if (trackIds.length === 0 || !playlistId || !calculation.result || calculation.busy
      || preview !== calculation.result) return;
    setPopulating(true);
    setError(null);
    try {
      const result = await api.post<{
        playlist_name: string;
        added_count: number;
        playlist_track_count: number;
      }>(`/playlists/${encodeURIComponent(playlistId)}/populate`, {
        track_ids: trackIds.join(","),
      });
      calculation.forget();
      router.push(
        `/playlists?added=${result.added_count}&name=${encodeURIComponent(result.playlist_name)}`
      );
    } catch (e) {
      setError(String(e).replace("Error: ", ""));
      setPopulating(false);
    }
  }

  if (gate !== "ready") {
    return (
      <div className="panel">
        <p className="muted">Loading…</p>
      </div>
    );
  }

  return (
    <section className="panel">
      <p className="m-0 mb-3 text-sm">
        <Link href="/playlists" className="text-[var(--muted)] no-underline hover:text-[var(--fg)]">
          ← Playlists
        </Link>
      </p>
      <h2 className="mt-0 text-lg font-semibold">
        {preview ? `Populate “${preview.playlist_name}”` : "Populate playlist"}
      </h2>
      {preview && (
        <p className="text-sm muted">
          {preview.playlist_track_count} tracks currently, {items.length} recommended to add.
        </p>
      )}

      {(error || calculation.error) && (
        <div className="flash flash-error" role="alert">
          {error || calculation.error}
          {calculation.error && <button className="btn btn-secondary text-sm ml-3"
            onClick={() => setRevision((value) => value + 1)}>Retry calculation</button>}
        </div>
      )}

      <div className="mt-3 mb-4 p-3 border border-[var(--border)] rounded-lg bg-[var(--bg)]">
        <p className="text-sm font-semibold mb-2">Strategy</p>
        <div className="flex items-center gap-2 mb-4">
          <div className="inline-flex rounded-full border border-[var(--border)] p-0.5" role="group" aria-label="Populate strategy">
            {(["average", "frequency"] as const).map((value) => (
              <button
                key={value}
                type="button"
                disabled={populating}
                className={`text-xs px-3 py-1 rounded-full font-medium border-0 ${
                  method === value
                    ? "bg-[var(--brand)] text-white"
                    : "bg-transparent text-[var(--muted)]"
                } ${populating ? "opacity-60 cursor-wait" : "cursor-pointer"}`}
                onClick={() => { setRestoredQuery(null); setMethod(value); }}
              >
                {value === "average" ? "Average" : "Frequency"}
              </button>
            ))}
          </div>
        </div>
        <p className="text-sm font-semibold mb-2">Scoring weights</p>
        <WeightControls
          weights={weights}
          presets={presets}
          preset={preset}
          onPresetChange={setPresetWeights}
          onWeightChange={(key, value) => {
            if (populating) return;
            setRestoredQuery(null);
            setPreset("custom");
            setWeights((prev) => ({ ...prev, [key]: value }));
          }}
        />
      </div>

      {loading || refreshing ? (
        <CalculationProgress job={calculation.job} notice={calculation.notice}
          onCancel={() => { void calculation.cancel(); }} />
      ) : !calculation.result ? (
        <p className="text-sm text-[var(--muted)]">No recommendations ready yet.</p>
      ) : items.length === 0 ? (
        <p className="text-sm text-[var(--muted)]">No tracks selected — nothing to add.</p>
      ) : (
        <RecommendResults
          items={items}
          weights={preview?.weights}
          onRemove={(trackId) => {
            removedIdsRef.current.add(trackId);
            setItems((prev) => prev.filter((r) => r.track_id !== trackId));
          }}
        />
      )}

      <div className="flex flex-wrap gap-2 mt-4">
        <button
          className="btn btn-primary"
          onClick={handleConfirm}
          disabled={populating || loading || refreshing || !!calculation.error
            || !calculation.result || preview !== calculation.result || items.length === 0}
        >
          {populating ? "Adding…" : "Confirm & add"}
        </button>
        <button className="btn btn-secondary" disabled={populating}
          onClick={async () => {
            if (calculation.busy) await calculation.cancel();
            calculation.forget();
            router.push("/playlists");
          }}>
          Cancel
        </button>
      </div>
    </section>
  );
}
