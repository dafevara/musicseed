import type { RecommendResponse } from "./types";

/** Build a write request only from the preview that was actually approved. */
export function playlistCreateBody(name: string, preview: RecommendResponse) {
  if (!name.trim() || !preview.seed_track_ids.length || !preview.recommendations.length) {
    throw new Error("A name and a nonempty approved preview are required.");
  }
  return {
    name: name.trim(),
    seed_ids: preview.seed_track_ids.join(","),
    track_ids: preview.recommendations.map((rec) => rec.track_id).join(","),
  };
}
