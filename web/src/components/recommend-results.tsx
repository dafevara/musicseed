"use client";

import type { RecommendationItem } from "@/lib/types";
import { breakdownTitle } from "@/lib/score-explanation";

const SIGNALS = ["sonic", "popularity", "style", "genre", "era", "novelty"] as const;

const SIGNAL_COLORS: Record<(typeof SIGNALS)[number], string> = {
  sonic: "#f2b632",
  popularity: "#60a5fa",
  style: "#a78bfa",
  genre: "#34d399",
  era: "#f472b6",
  novelty: "#94a3b8",
};

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
    <ol className="list-none m-0 p-0 grid gap-2">
      {items.map((rec, index) => {
        const pct = Math.round(rec.score.total * 100);
        const meta = [
          rec.album,
          rec.year,
          rec.popularity != null ? `Popularity ${rec.popularity}` : null,
        ].filter(Boolean);
        const shares = SIGNALS.map(
          (signal) => (rec.score[signal] ?? 0) * (weights?.[signal] ?? 0),
        );
        const weighted = shares.reduce((sum, share) => sum + share, 0);
        return (
          <li key={rec.track_id} className="result-card flex items-start gap-3">
            <span className="result-rank" aria-hidden>
              {String(index + 1).padStart(2, "0")}
            </span>
            <div className="min-w-0 flex-1">
              <p className="m-0 text-sm truncate">
                <span className="font-semibold">{rec.title}</span>
                <span className="text-[var(--muted)]"> — {rec.artist || "Unknown Artist"}</span>
              </p>
              {meta.length > 0 && (
                <p className="m-0 text-xs text-[var(--muted)] truncate">{meta.join(" · ")}</p>
              )}
              {weighted > 0 && (
                <div className="signal-track" title={breakdownTitle(rec.score)}>
                  {SIGNALS.map((signal, i) => (
                    <span
                      key={signal}
                      className="signal-segment"
                      style={{
                        width: `${((shares[i] / weighted) * 100).toFixed(2)}%`,
                        background: SIGNAL_COLORS[signal],
                      }}
                    />
                  ))}
                </div>
              )}
            </div>
            <div className="flex-shrink-0 text-right">
              <div className="result-score">
                {pct}
                <span className="result-score-unit">%</span>
              </div>
              <div className="result-score-caption">match</div>
            </div>
            {onRemove && (
              <button
                type="button"
                className="activity-delete self-start"
                title="Remove from selection"
                aria-label={`Remove ${rec.title}`}
                onClick={() => onRemove(rec.track_id)}
              >
                ×
              </button>
            )}
          </li>
        );
      })}
    </ol>
  );
}
