"use client";

import type { RecommendationItem } from "@/lib/types";

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
          <span className="text-xs text-[var(--muted)] tabular-nums flex-shrink-0">
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
