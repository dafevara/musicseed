"use client";

import type { RecommendationItem } from "@/lib/types";

function breakdownTitle(score: RecommendationItem["score"]): string {
  const lines = [
    `sonic ${(score.sonic * 100).toFixed(0)}%`,
    `popularity ${(score.popularity * 100).toFixed(0)}%`,
    `style ${(score.style * 100).toFixed(0)}%`,
    `genre ${(score.genre * 100).toFixed(0)}%`,
    `era ${(score.era * 100).toFixed(0)}%`,
    `novelty ${(score.novelty * 100).toFixed(0)}%`,
  ];
  const availability = score.availability ?? {};
  const missing = Object.keys(availability)
    .filter((k) => availability[k] === "neutral_missing")
    .sort();
  const skipped = Object.keys(availability)
    .filter((k) => availability[k] === "not_applicable")
    .sort();
  if (missing.length) lines.push(`missing: ${missing.join(", ")}`);
  if (skipped.length) lines.push(`not applicable: ${skipped.join(", ")}`);
  return lines.join("\n");
}

export function RecommendResults({
  items,
  onRemove,
}: {
  items: RecommendationItem[];
  weights?: Record<string, number>;
  onRemove?: (trackId: number) => void;
}) {
  if (!items.length) return null;

  return (
    <ol className="list-none m-0 p-0">
      {items.map((rec) => (
        <li
          key={rec.track_id}
          className="flex items-center gap-2 px-2 py-1 rounded-md odd:bg-[var(--bg)]"
        >
          <span className="min-w-0 flex-1 truncate text-sm">
            <span className="font-medium">{rec.artist || "Unknown Artist"}</span>
            <span className="text-[var(--muted)]"> — </span>
            <span>{rec.title}</span>
          </span>
          <span
            className="text-xs text-[var(--muted)] tabular-nums flex-shrink-0"
            title={breakdownTitle(rec.score)}
          >
            {(rec.score.total * 100).toFixed(0)}%
          </span>
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
        </li>
      ))}
    </ol>
  );
}
