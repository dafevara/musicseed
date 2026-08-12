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

function ScoreBar({ breakdown }: { breakdown: ScoreBreakdown }) {
  return (
    <div className="w-full">
      <div className="flex h-1.5 rounded-sm overflow-hidden bg-[var(--border)]">
        {DIMENSIONS.map(({ key, color }) => {
          const pct = breakdown.total > 0 ? (breakdown[key] as number) / breakdown.total * 100 : 0;
          return pct > 0 ? (
            <div
              key={key}
              className="h-full transition-all"
              style={{ width: `${pct}%`, backgroundColor: color }}
              title={`${key}: ${((breakdown[key] as number) * 100).toFixed(0)}%`}
            />
          ) : null;
        })}
      </div>
    </div>
  );
}

export function RecommendResults({ items }: { items: RecommendationItem[] }) {
  if (!items.length) return null;

  return (
    <ol className="list-none m-0 p-0 grid gap-1">
      {items.map((rec) => {
        const pct = Math.round(rec.score.total * 100);
        return (
          <li
            key={rec.track_id}
            className="grid gap-3 px-3 py-2.5 rounded-md odd:bg-[var(--bg)]"
          >
            <div className="flex flex-wrap items-baseline gap-x-1 min-w-0">
              <span className="font-semibold truncate">
                {rec.artist || "Unknown Artist"}
              </span>
              <span className="text-[var(--muted)] flex-shrink-0">&mdash;</span>
              <span className="truncate">{rec.title}</span>
            </div>
            <div className="grid grid-cols-[1fr_3.5rem] items-center gap-4">
              <ScoreBar breakdown={rec.score} />
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
