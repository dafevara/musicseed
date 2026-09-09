import type { RecommendationItem } from "./types";

const SIGNALS = ["sonic", "popularity", "style", "genre", "era", "novelty"] as const;
const LABELS = {
  observed: "observed",
  neutral_missing: "neutral fallback: missing/unusable data",
  missing: "missing candidate tags; existing zero-score policy",
  not_applicable: "no seed basis",
  mixed: "mixed evidence across seed votes",
  unknown: "availability not supplied",
};

export function breakdownTitle(score: RecommendationItem["score"]): string {
  return SIGNALS.map((signal) => {
    const status = score.availability?.[signal] ?? "unknown";
    return `${signal} ${(score[signal] * 100).toFixed(0)}% — ${LABELS[status]}`;
  }).join("\n");
}
