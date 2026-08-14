"use client";

import { Suspense, useEffect, useRef, useState } from "react";
import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { api } from "@/lib/api";
import { useSetupGate } from "@/lib/use-setup-gate";
import type { PopulateMethod, PopulatePreview, RecommendationItem } from "@/lib/types";
import { RecommendResults } from "@/components/recommend-results";
import { WeightControls } from "@/components/weight-controls";

function previewQuery(weights: Record<string, number>, method: PopulateMethod): string {
  const parts = [`method=${method}`];
  for (const [k, v] of Object.entries(weights)) {
    parts.push(`w_${k}=${v}`);
  }
  return parts.join("&");
}

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
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [populating, setPopulating] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const removedIdsRef = useRef<Set<number>>(new Set());
  const previewGenRef = useRef(0);
  const readyRef = useRef(false);

  useEffect(() => {
    if (!playlistId) {
      router.replace("/playlists");
    }
  }, [playlistId, router]);

  useEffect(() => {
    api.get<Record<string, Record<string, number>>>("/recommend/presets")
      .then((data) => {
        setPresets(data);
        if (data.balanced) setWeights({ ...data.balanced });
      })
      .catch(() => {});
  }, []);

  useEffect(() => {
    if (!playlistId) return;
    const gen = ++previewGenRef.current;
    setLoading(true);
    setError(null);
    api.get<PopulatePreview>(
      `/playlists/${encodeURIComponent(playlistId)}/preview?limit=40&method=average`
    )
      .then((data) => {
        if (previewGenRef.current !== gen) return;
        setPreview(data);
        setItems(data.recommendations);
        readyRef.current = true;
      })
      .catch((e) => {
        if (previewGenRef.current !== gen) return;
        setError(String(e).replace("Error: ", ""));
      })
      .finally(() => {
        if (previewGenRef.current === gen) setLoading(false);
      });
  }, [playlistId]);

  useEffect(() => {
    if (!playlistId || !readyRef.current) return;
    const gen = ++previewGenRef.current;
    setRefreshing(true);
    const timer = setTimeout(async () => {
      try {
        const qs = previewQuery(weights, method);
        const data = await api.get<PopulatePreview>(
          `/playlists/${encodeURIComponent(playlistId)}/preview?limit=40&${qs}`
        );
        if (previewGenRef.current !== gen) return;
        setPreview(data);
        setItems(
          data.recommendations.filter((r) => !removedIdsRef.current.has(r.track_id))
        );
      } catch (e) {
        if (previewGenRef.current !== gen) return;
        setError(String(e).replace("Error: ", ""));
      } finally {
        if (previewGenRef.current === gen) setRefreshing(false);
      }
    }, 300);
    return () => clearTimeout(timer);
  }, [playlistId, weights, method]);

  function setPresetWeights(name: string) {
    setPreset(name);
    if (presets[name]) setWeights({ ...presets[name] });
  }

  async function handleConfirm() {
    const trackIds = items.map((r) => r.track_id);
    if (trackIds.length === 0 || !playlistId) return;
    setPopulating(true);
    setError(null);
    try {
      const result = await api.post<{
        playlist_name: string;
        added_count: number;
        playlist_track_count: number;
      }>(`/playlists/${encodeURIComponent(playlistId)}/populate`, {
        limit: 40,
        method,
        track_ids: trackIds.join(","),
      });
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

      {error && <div className="flash flash-error">{error}</div>}

      <div className="mt-3 mb-4 p-3 border border-[var(--border)] rounded-lg bg-[var(--bg)]">
        <p className="text-sm font-semibold mb-2">Strategy</p>
        <div className="flex items-center gap-2 mb-4">
          <div className="inline-flex rounded-full border border-[var(--border)] p-0.5" role="group" aria-label="Populate strategy">
            {(["average", "frequency"] as const).map((value) => (
              <button
                key={value}
                type="button"
                disabled={refreshing || loading}
                className={`text-xs px-3 py-1 rounded-full font-medium border-0 ${
                  method === value
                    ? "bg-[var(--brand)] text-white"
                    : "bg-transparent text-[var(--muted)]"
                } ${refreshing || loading ? "opacity-60 cursor-wait" : "cursor-pointer"}`}
                onClick={() => setMethod(value)}
              >
                {value === "average" ? "Average" : "Frequency"}
              </button>
            ))}
          </div>
          {refreshing && (
            <span className="inline-flex items-center gap-1.5 text-xs text-[var(--muted)]" aria-live="polite">
              <span className="inline-block h-3.5 w-3.5 rounded-full border-2 border-[var(--border)] border-t-[var(--brand)] animate-spin" />
              Updating preview…
            </span>
          )}
        </div>
        <p className="text-sm font-semibold mb-2">Scoring weights</p>
        <WeightControls
          weights={weights}
          presets={presets}
          preset={preset}
          onPresetChange={setPresetWeights}
          onWeightChange={(key, value) => {
            setPreset("custom");
            setWeights((prev) => ({ ...prev, [key]: value }));
          }}
        />
      </div>

      {loading || refreshing ? (
        <p className="text-sm text-[var(--muted)] inline-flex items-center gap-2">
          <span className="inline-block h-3.5 w-3.5 rounded-full border-2 border-[var(--border)] border-t-[var(--brand)] animate-spin" />
          {loading ? "Loading preview…" : "Recalculating recommendations…"}
        </p>
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
          disabled={populating || loading || refreshing || items.length === 0}
        >
          {populating ? "Adding…" : "Confirm & add"}
        </button>
        <Link href="/playlists" className="btn btn-secondary no-underline">
          Cancel
        </Link>
      </div>
    </section>
  );
}
