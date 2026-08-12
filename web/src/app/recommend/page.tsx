"use client";

import { useState, useEffect, useCallback } from "react";
import { api } from "@/lib/api";
import type { TypeaheadTrack, RecommendResponse, RecommendationItem, ScoreBreakdown } from "@/lib/types";
import { SeedChips } from "@/components/seed-chips";
import { Typeahead } from "@/components/typeahead";
import { RecommendResults } from "@/components/recommend-results";

const WEIGHT_DEFAULTS: Record<string, number> = {
  sonic: 0.35,
  popularity: 0.15,
  style: 0.10,
  genre: 0.15,
  era: 0.10,
  novelty: 0.15,
};

const WEIGHT_LABELS: Record<string, string> = {
  sonic: "Sonic similarity",
  popularity: "Popularity match",
  style: "Style match",
  genre: "Genre match",
  era: "Era proximity",
  novelty: "Novelty / discovery",
};

const PRESETS: Record<string, Record<string, number>> = {
  balanced: { sonic: 0.35, popularity: 0.15, style: 0.10, genre: 0.15, era: 0.10, novelty: 0.15 },
  sonic: { sonic: 0.55, popularity: 0.10, style: 0.10, genre: 0.10, era: 0.05, novelty: 0.10 },
  discovery: { sonic: 0.15, popularity: 0.05, style: 0.10, genre: 0.10, era: 0.05, novelty: 0.55 },
  popular: { sonic: 0.15, popularity: 0.45, style: 0.10, genre: 0.15, era: 0.05, novelty: 0.10 },
};

export default function RecommendPage() {
  const [seeds, setSeeds] = useState<TypeaheadTrack[]>([]);
  const [seedIds, setSeedIds] = useState<number[]>([]);
  const [results, setResults] = useState<RecommendationItem[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);

  const [limit, setLimit] = useState(50);
  const [yearMin, setYearMin] = useState("");
  const [yearMax, setYearMax] = useState("");
  const [perArtist, setPerArtist] = useState(3);
  const [minScore, setMinScore] = useState("");

  const [weights, setWeights] = useState<Record<string, number>>({ ...WEIGHT_DEFAULTS });
  const [preset, setPreset] = useState("balanced");

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
    setWeights({ ...PRESETS[name] });
  }

  function setWeight(key: string, value: number) {
    setPreset("custom");
    setWeights((prev) => ({ ...prev, [key]: value }));
  }

  useEffect(() => {
    if (seedIds.length === 0) {
      setResults([]);
      setError(null);
      return;
    }

    const timer = setTimeout(async () => {
      setLoading(true);
      try {
        const body: Record<string, string | number> = {
          seed_ids: seedIds.join(","),
          limit,
          year_min: yearMin,
          year_max: yearMax,
          max_tracks_per_artist: perArtist,
          min_score: minScore,
        };
        for (const [k, v] of Object.entries(weights)) {
          body[`w_${k}`] = String(v);
        }
        const data = await api.post<RecommendResponse>("/recommend", body);
        setResults(data.recommendations);
        setError(null);
      } catch (e) {
        setError(String(e));
        setResults([]);
      } finally {
        setLoading(false);
      }
    }, 300);

    return () => clearTimeout(timer);
  }, [seedIds, limit, yearMin, yearMax, perArtist, minScore, weights]);

  return (
    <>
      <section className="panel">
        <h2 className="mt-0 text-lg font-semibold">Seed tracks</h2>
        <p className="muted text-sm">
          Search for tracks to use as seeds for recommendations.
        </p>

        <Typeahead seedIds={seedIds} onSelect={addSeed} />
        <SeedChips seeds={seeds} onRemove={removeSeed} />
      </section>

      <section className="panel">
        <h2 className="mt-0 mb-3 text-lg font-semibold">Scoring weights</h2>

        <div className="flex flex-wrap gap-2 mb-3">
          {Object.keys(PRESETS).map((name) => (
            <button
              key={name}
              className={`text-xs px-2.5 py-1 rounded-full border font-medium cursor-pointer transition-colors
                ${preset === name
                  ? "bg-[var(--brand)] text-white border-[var(--brand)]"
                  : "bg-transparent text-[var(--muted)] border-[var(--border)] hover:border-[var(--brand)] hover:text-[var(--fg)]"
                }`}
              onClick={() => setPresetWeights(name)}
            >
              {name.charAt(0).toUpperCase() + name.slice(1)}
            </button>
          ))}
        </div>

        <div className="grid gap-2.5 max-w-md">
          {(() => {
            const totalWeight = Object.values(weights).reduce((a, b) => a + b, 0) || 1;
            return Object.entries(WEIGHT_LABELS).map(([key, label]) => (
            <div key={key} className="flex items-center gap-3">
              <span className="text-sm text-[var(--muted)] w-32 flex-shrink-0">{label}</span>
              <input
                type="range"
                min={0}
                max={1}
                step={0.05}
                value={weights[key]}
                onChange={(e) => setWeight(key, parseFloat(e.target.value))}
                className="flex-1"
                style={{
                  accentColor: "var(--brand)",
                  height: 4,
                }}
              />
              <span className="text-xs text-[var(--muted)] w-8 text-right tabular-nums">
                {((weights[key] / totalWeight) * 100).toFixed(0)}%
              </span>
            </div>
          ));
          })()}
        </div>
      </section>

      <section className="panel">
        <h2 className="mt-0 text-lg font-semibold">Filters</h2>
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

      {loading && seedIds.length > 0 && (
        <p className="muted">Loading&hellip;</p>
      )}

      {!loading && seedIds.length > 0 && results.length === 0 && !error && (
        <p className="muted">
          No recommendations found. Try adjusting the filters or using different seed tracks.
        </p>
      )}

      <RecommendResults items={results} />
    </>
  );
}
