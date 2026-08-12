"use client";

import { useState } from "react";
import type { RecommendationItem, ScoreBreakdown } from "@/lib/types";

const DIMENSIONS: { key: keyof ScoreBreakdown; label: string; color: string }[] = [
  { key: "sonic", label: "Sonic", color: "#b57a00" },
  { key: "popularity", label: "Popularity", color: "#1e7a45" },
  { key: "style", label: "Style", color: "#6b4cb8" },
  { key: "genre", label: "Genre", color: "#1a5dc7" },
  { key: "era", label: "Era", color: "#b84592" },
  { key: "novelty", label: "Novelty", color: "#c7692a" },
];

function ScoreBar({ breakdown, weights }: { breakdown: ScoreBreakdown; weights?: Record<string, number> }) {
  // Each segment shows the signal's weighted contribution to the total, so the
  // segments sum to 100% of the total score (matching the scoring arithmetic:
  // total = sum(component * weight) / sum(weight)).
  const weighted = DIMENSIONS.map(({ key }) => {
    const component = breakdown[key] as number;
    const weight = weights && weights[key] !== undefined ? (weights[key] as number) : 1;
    return { key, component, weight, share: component * weight };
  });
  const denominator = weighted.reduce((sum, d) => sum + d.share, 0) || 1;

  return (
    <div className="w-full">
      <div className="flex h-1.5 rounded-sm overflow-hidden bg-[var(--border)]">
        {weighted.map(({ key, component, weight, share }) => {
          const pct = (share / denominator) * 100;
          return pct > 0 ? (
            <div
              key={key}
              className="h-full transition-all"
              style={{ width: `${pct}%`, backgroundColor: DIMENSIONS.find((d) => d.key === key)?.color }}
              title={`${key}: raw ${(component * 100).toFixed(0)}% · weight ${weight} · contribution ${pct.toFixed(0)}%`}
            />
          ) : null;
        })}
      </div>
    </div>
  );
}

export function RecommendResults({
  items,
  weights,
  onRemove,
}: {
  items: RecommendationItem[];
  weights?: Record<string, number>;
  onRemove?: (trackId: number) => void;
}) {
  if (!items.length) return null;

  return (
    <ol className="list-none m-0 p-0 grid gap-1">
      {items.map((rec) => {
        return (
          <li
            key={rec.track_id}
            className="grid gap-3 px-3 py-2.5 rounded-md odd:bg-[var(--bg)]"
          >
            <div className="flex items-start justify-between gap-2">
              <div className="flex flex-wrap items-baseline gap-x-1 min-w-0">
                <span className="font-semibold truncate">
                  {rec.artist || "Unknown Artist"}
                </span>
                <span className="text-[var(--muted)] flex-shrink-0">&mdash;</span>
                <span className="truncate">{rec.title}</span>
              </div>
              {onRemove && (
                <button
                  type="button"
                  className="activity-delete"
                  title="Remove from preview"
                  aria-label={`Remove ${rec.title}`}
                  onClick={() => onRemove(rec.track_id)}
                >
                  ×
                </button>
              )}
            </div>
            <div className="grid grid-cols-[1fr_3.5rem] items-center gap-4">
              <ScoreBar breakdown={rec.score} weights={weights} />
              <span className="text-sm text-[var(--muted)] text-right tabular-nums">
                {(rec.score.total * 100).toFixed(0)}%
              </span>
            </div>
          </li>
        );
      })}
    </ol>
  );
}
