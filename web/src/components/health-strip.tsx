"use client";

import { useEffect, useState } from "react";
import { api } from "@/lib/api";
import type { DashboardSnapshot, JobSummary, PlexServerCheck } from "@/lib/types";

interface SonicStatus {
  total_tracks: number;
  analyzed_tracks: number;
  unanalyzed_albums: Array<{ title: string | null; artist: string | null; unanalyzed_count: number }>;
}

function fmt(n: number | string): string {
  const v = typeof n === "string" ? parseInt(n, 10) || 0 : n;
  return v.toLocaleString();
}

function pct(covered: number | string, total: number | string): number {
  const c = typeof covered === "string" ? parseInt(covered, 10) || 0 : covered;
  const t = typeof total === "string" ? parseInt(total, 10) || 0 : total;
  return t > 0 ? Math.round((c / t) * 100) : 0;
}

function num(v: number | string): number {
  return typeof v === "string" ? parseInt(v, 10) || 0 : v;
}

function CoverageBar({
  label,
  covered,
  total,
  zeroHint,
  action,
  activeJob,
}: {
  label: string;
  covered: number | string;
  total: number | string;
  zeroHint: string;
  action?: { label: string; disabled?: boolean; onClick: () => void; busy?: boolean };
  activeJob?: JobSummary | null;
}) {
  const c = num(covered);
  const t = num(total);
  const barPct = t > 0 ? Math.round((c / t) * 100) : 0;

  return (
    <div>
      <div className="flex justify-between items-baseline text-xs">
        <span>{label}</span>
        <span className="text-[var(--muted)]">
          {activeJob ? (
            <span className="text-[var(--status-running)]">
              {activeJob.progress_current > 0
                ? `${fmt(activeJob.progress_current)} of ${fmt(activeJob.progress_total)}`
                : "running…"}
            </span>
          ) : (
            `${fmt(covered)} of ${fmt(t)}`
          )}
        </span>
      </div>
      <div className="progress-bar mt-0.5">
        <div
          className="fill"
          style={{ width: `${activeJob && activeJob.progress_total > 0
            ? Math.round((num(activeJob.progress_current) / num(activeJob.progress_total)) * 100)
            : barPct}%` }}
        />
      </div>
      {activeJob ? (
        <p className="mt-0.5 mb-0 text-[0.7rem] text-[var(--status-running)]">
          {activeJob.checkpoint || "Enriching…"}
        </p>
      ) : c === 0 ? (
        <div className="mt-0.5 flex items-baseline gap-2">
          <span className="text-[0.7rem] text-[var(--muted)]">{zeroHint}</span>
          {action && (
            <button
              className="text-[0.7rem] font-medium bg-transparent border-0 p-0 text-[var(--brand)] cursor-pointer hover:underline"
              onClick={action.onClick}
              disabled={action.disabled || action.busy}
            >
              {action.busy ? "Starting…" : action.label}
            </button>
          )}
        </div>
      ) : barPct < 100 && action ? (
        <div className="mt-0.5">
          <button
            className="text-[0.7rem] font-medium bg-transparent border-0 p-0 text-[var(--brand)] cursor-pointer hover:underline"
            onClick={action.onClick}
            disabled={action.disabled || action.busy}
          >
            {action.busy ? "Starting…" : action.label}
          </button>
        </div>
      ) : null}
    </div>
  );
}

export function HealthStrip({
  snapshot,
  activeJobs,
  onEnrich,
  onSonicRefresh,
  plexServer,
}: {
  snapshot: DashboardSnapshot;
  activeJobs: JobSummary[];
  onEnrich: () => void;
  onSonicRefresh: () => void | Promise<void>;
  plexServer?: PlexServerCheck | null;
}) {
  const { library: lib, discovery } = snapshot;
  const plex = plexServer ?? discovery.plex_server;
  const tracks = lib.track_count;
  const enrichment = lib.enrichment;

  const enrichJob = activeJobs.find((j) => j.kind === "enrich" && (j.state === "running" || j.state === "pending"));
  const importJob = activeJobs.find((j) => j.kind === "import" && (j.state === "running" || j.state === "pending"));
  const importCov = lib.import_coverage;
  const [sonicStatus, setSonicStatus] = useState<SonicStatus | null>(null);
  const [enriching, setEnriching] = useState(false);
  const [refreshing, setRefreshing] = useState(false);
  const [confirmRefresh, setConfirmRefresh] = useState(false);

  async function doRefresh() {
    setRefreshing(true);
    setConfirmRefresh(false);
    await onSonicRefresh();
    setRefreshing(false);
  }

  useEffect(() => {
    api.get<{ total_tracks: number; analyzed_tracks: number; unanalyzed_albums: SonicStatus["unanalyzed_albums"] }>("/sonic/status")
      .then(setSonicStatus)
      .catch(() => {});
  }, []);

  const spotifyAttempted = num(enrichment.spotify_attempted);
  const lbAttempted = num(enrichment.listenbrainz_attempted);
  const spotifyCovered = num(enrichment.tracks_with_spotify);
  const lbCovered = num(enrichment.tracks_with_listenbrainz);

  const spotifyHint = spotifyAttempted > 0
    ? "No Spotify matches found. Try again or check credentials."
    : "Not yet enriched. Run enrichment to match tracks on Spotify.";

  const lbHint = lbAttempted > 0
    ? "No ListenBrainz data. Tracks may lack recording MBIDs."
    : "Not yet queried. Requires tracks with MusicBrainz recording IDs.";

  const sonicHint = sonicStatus
    ? `${fmt(sonicStatus.unanalyzed_albums.length)} albums pending analysis`
    : "Sonic analysis not yet available";

  return (
    <>
    <div className="grid grid-cols-[repeat(auto-fit,minmax(15rem,1fr))] gap-px bg-[var(--border)] border border-[var(--border)] rounded-lg overflow-hidden">
      {/* Plex */}
      <div className="min-w-0 p-3.5 bg-[var(--panel)]">
        <p className="mt-0 mb-1.5 text-xs font-semibold tracking-wider uppercase text-[var(--muted)]">
          Plex
        </p>
        {plex.ok ? (
          <>
            <p className="m-0 text-sm">
              <span className="badge badge-ok">ok</span>{" "}
              Plex {plex.server_version}
            </p>
            <p className="mt-1 mb-0 text-sm text-[var(--muted)] break-words">
              Library &ldquo;{plex.library}&rdquo; &middot; token{" "}
              {plex.token_configured ? "configured" : "not set"}
            </p>
          </>
        ) : (
          <>
            <p className="m-0 text-sm">
              <span className="badge badge-problem">needs attention</span>
            </p>
            <p className="mt-1 mb-0 text-sm text-[var(--muted)]">
              {plex.detail || "Plex is not reachable."}{" "}
              <a href="/settings" className="text-[var(--brand)] underline">
                Configure
              </a>
              .
            </p>
          </>
        )}
      </div>

      {/* Library stats */}
      <div className="min-w-0 p-3.5 bg-[var(--panel)]">
        <p className="mt-0 mb-1.5 text-xs font-semibold tracking-wider uppercase text-[var(--muted)]">
          Library
        </p>
        <div className="flex flex-wrap gap-x-4 gap-y-1">
          <div className="text-sm text-[var(--muted)]">
            <strong className="block text-lg text-[var(--fg)]">{fmt(tracks)}</strong> tracks
          </div>
          <div className="text-sm text-[var(--muted)]">
            <strong className="block text-lg text-[var(--fg)]">{fmt(lib.album_count)}</strong> albums
          </div>
          <div className="text-sm text-[var(--muted)]">
            <strong className="block text-lg text-[var(--fg)]">{fmt(lib.artist_count)}</strong> artists
          </div>
          <div className="text-sm text-[var(--muted)]">
            <strong className="block text-lg text-[var(--fg)]">{fmt(lib.play_count)}</strong> plays
          </div>
        </div>
      </div>

      {/* Coverage */}
      <div className="min-w-0 p-3.5 bg-[var(--panel)]">
        <p className="mt-0 mb-1.5 text-xs font-semibold tracking-wider uppercase text-[var(--muted)]">
          Coverage
        </p>
        <div className="grid gap-2">
          {importCov && (
            <CoverageBar
              label="Plex import"
              covered={importCov.tracks.local}
              total={importCov.tracks.plex}
              zeroHint="Library not imported yet."
              activeJob={importJob}
            />
          )}
          <CoverageBar
            label="Spotify"
            covered={enrichment.tracks_with_spotify}
            total={tracks}
            zeroHint={spotifyHint}
            activeJob={enrichJob}
            action={enrichJob ? undefined : {
              label: spotifyCovered > 0 ? "Resume enrichment" : "Enrich",
              busy: enriching,
              onClick: () => { setEnriching(true); onEnrich(); },
            }}
          />
          <CoverageBar
            label="ListenBrainz"
            covered={enrichment.tracks_with_listenbrainz}
            total={tracks}
            zeroHint={lbHint}
            action={{
              label: lbCovered > 0 ? "Resume" : "Enrich",
              busy: enriching,
              onClick: () => { setEnriching(true); onEnrich(); },
            }}
          />
          <CoverageBar
            label="Sonic"
            covered={sonicStatus ? sonicStatus.analyzed_tracks : enrichment.tracks_with_sonic}
            total={sonicStatus ? sonicStatus.total_tracks : tracks}
            zeroHint={sonicHint}
            action={{
              label: "Refresh analysis",
              busy: refreshing,
              onClick: () => setConfirmRefresh(true),
            }}
          />
        </div>
      </div>
    </div>

    {confirmRefresh && (
      <div className="flash flash-warn mt-3">
        <p className="m-0 mb-2">
          Refreshing sonic analysis starts Plex&apos;s MusicAnalysis Butler task, which
          processes the server&apos;s <strong>entire pending backlog</strong> — not just recent
          additions — and can keep running after MusicSeed returns. This may take a long time
          and run in the background on your Plex server.
        </p>
        <div className="flex gap-2">
          <button className="btn btn-primary" onClick={doRefresh} disabled={refreshing}>
            {refreshing ? "Starting…" : "Confirm refresh"}
          </button>
          <button className="btn btn-secondary" onClick={() => setConfirmRefresh(false)}>
            Cancel
          </button>
        </div>
      </div>
    )}
    </>
  );
}
