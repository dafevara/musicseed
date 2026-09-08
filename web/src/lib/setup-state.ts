import type { DiscoveryResponse, DiscoveryResult, LibraryStatus } from "./types";

export type SetupStep = "detect" | "review" | "importing" | "enriching" | "done";

export function resolveSetupStep(d: DiscoveryResponse, status: LibraryStatus | null): SetupStep {
  const incomplete = d.result.first_run.import_incomplete
    || (status?.import_coverage && !status.import_coverage.ever_succeeded);
  if (status && status.track_count > 0 && !incomplete) return "done";
  if (d.result.can_import || d.result.plex_server.ok || d.result.musicseed_db.exists) return "review";
  return "detect";
}

/** Refresh both state sources after jobs/recovery; never reuse a stale first-run flag. */
export async function refreshSetupState(
  discover: () => Promise<DiscoveryResponse>,
  libraryStatus: () => Promise<LibraryStatus>,
) {
  const discovery = await discover();
  const status = discovery.result.musicseed_db.exists
    ? await libraryStatus().catch(() => null)
    : null;
  return { discovery, status, step: resolveSetupStep(discovery, status) };
}

/** An SSH probe's display path is not a local path or a reusable SSH target. */
export function discoveredLocalPlexPath(result: DiscoveryResult): string {
  const selected = result.plex_library_db.selected;
  return selected && selected.source !== "ssh" ? selected.path : "";
}
