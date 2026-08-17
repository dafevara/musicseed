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

function num(v: number | string): number {
  return typeof v === "string" ? parseInt(v, 10) || 0 : v;
}

function PlayIcon() {
  return (
    <svg width="12" height="12" viewBox="0 0 16 16" fill="currentColor" aria-hidden="true">
      <path d="M5 3.2v9.6l8.2-4.8L5 3.2z" />
    </svg>
  );
}

function RefreshIcon() {
  return (
    <svg width="12" height="12" viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.7" aria-hidden="true">
      <path d="M13.4 8A5.4 5.4 0 1 1 12 4.1" strokeLinecap="round" />
      <path d="M12.1 1.8v2.7H9.4" strokeLinecap="round" strokeLinejoin="round" />
    </svg>
  );
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
  action?: {
    label: string;
    icon?: "play" | "refresh";
    disabled?: boolean;
    onClick: () => void;
    busy?: boolean;
  };
  activeJob?: JobSummary | null;
}) {
  const c = num(covered);
  const t = num(total);
  const barPct = t > 0 ? Math.round((c / t) * 100) : 0;
  const showAction = !activeJob && action && (c === 0 || barPct < 100);
  const hint = activeJob
    ? (activeJob.checkpoint || "Enriching…")
    : c === 0
      ? zeroHint
      : null;

  return (
    <div className="grid gap-1.5 py-3 first:pt-0 last:pb-0">
      <div className="flex items-center justify-between gap-3">
        <div className="min-w-0">
          <p className="m-0 text-sm font-medium">{label}</p>
          <p className="m-0 text-xs text-[var(--muted)]">
            {activeJob ? (
              <span className="text-[var(--status-running)]">
                {activeJob.progress_current > 0
                  ? `${fmt(activeJob.progress_current)} of ${fmt(activeJob.progress_total)}`
                  : "running…"}
              </span>
            ) : (
              `${fmt(covered)} of ${fmt(t)}`
            )}
          </p>
        </div>
        {showAction && (
          <button
            type="button"
            className="btn btn-outline btn-sm shrink-0"
            onClick={action.onClick}
            disabled={action.disabled || action.busy}
          >
            {action.busy ? null : action.icon === "refresh" ? <RefreshIcon /> : <PlayIcon />}
            {action.busy ? "Starting…" : action.label}
          </button>
        )}
      </div>
      <div className="progress-bar">
        <div
          className="fill"
          style={{ width: `${activeJob && activeJob.progress_total > 0
            ? Math.round((num(activeJob.progress_current) / num(activeJob.progress_total)) * 100)
            : barPct}%` }}
        />
      </div>
      {hint && (
        <p className={`m-0 text-[0.75rem] ${activeJob ? "text-[var(--status-running)]" : "text-[var(--muted)]"}`}>
          {hint}
        </p>
      )}
    </div>
  );
}

export function HealthStrip({
  snapshot,
  activeJobs,
  onEnrich,
  onEnrichListenBrainz,
  onSonicRefresh,
  plexServer,
}: {
  snapshot: DashboardSnapshot;
  activeJobs: JobSummary[];
  onEnrich: () => void | Promise<void>;
  onEnrichListenBrainz: () => void | Promise<void>;
  onSonicRefresh: () => void | Promise<void>;
  plexServer?: PlexServerCheck | null;
}) {
  const { library: lib, discovery } = snapshot;
  const plex = plexServer ?? discovery.plex_server;
  const tracks = lib.track_count;
  const enrichment = lib.enrichment;

  const isActive = (j: JobSummary) => j.state === "running" || j.state === "pending";
  const spotifyEnrichJob = activeJobs.find((j) => j.kind === "enrich:spotify" && isActive(j));
  const lbEnrichJob = activeJobs.find((j) => j.kind === "enrich:listenbrainz" && isActive(j));
  const importJob = activeJobs.find((j) => j.kind === "import" && isActive(j));
  const importCov = lib.import_coverage;
  const [sonicStatus, setSonicStatus] = useState<SonicStatus | null>(null);
  const [enrichingSpotify, setEnrichingSpotify] = useState(false);
  const [enrichingLb, setEnrichingLb] = useState(false);
  const [refreshing, setRefreshing] = useState(false);
  const [confirmRefresh, setConfirmRefresh] = useState(false);

  async function doRefresh() {
    setRefreshing(true);
    setConfirmRefresh(false);
    await onSonicRefresh();
    setRefreshing(false);
  }

  async function doEnrich() {
    setEnrichingSpotify(true);
    try {
      await onEnrich();
    } finally {
      setEnrichingSpotify(false);
    }
  }

  async function doEnrichListenBrainz() {
    setEnrichingLb(true);
    try {
      await onEnrichListenBrainz();
    } finally {
      setEnrichingLb(false);
    }
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
      <section className="panel">
        <p className="mt-0 mb-2 text-xs font-semibold tracking-wider uppercase text-[var(--muted)]">
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
      </section>

      <section className="panel">
        <p className="mt-0 mb-2 text-xs font-semibold tracking-wider uppercase text-[var(--muted)]">
          Library
        </p>
        <div className="grid grid-cols-4 gap-4 max-sm:grid-cols-2">
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
      </section>

      <section className="panel">
        <p className="mt-0 mb-1 text-xs font-semibold tracking-wider uppercase text-[var(--muted)]">
          Coverage
        </p>
        <div className="grid divide-y divide-[var(--border)]">
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
            activeJob={spotifyEnrichJob}
            action={spotifyEnrichJob ? undefined : {
              label: spotifyCovered > 0 ? "Resume enrichment" : "Enrich",
              icon: "play",
              busy: enrichingSpotify,
              onClick: doEnrich,
            }}
          />
          <CoverageBar
            label="ListenBrainz"
            covered={enrichment.tracks_with_listenbrainz}
            total={tracks}
            zeroHint={lbHint}
            activeJob={lbEnrichJob}
            action={lbEnrichJob ? undefined : {
              label: lbCovered > 0 ? "Resume" : "Enrich",
              icon: "play",
              busy: enrichingLb,
              onClick: doEnrichListenBrainz,
            }}
          />
          <CoverageBar
            label="Sonic"
            covered={sonicStatus ? sonicStatus.analyzed_tracks : enrichment.tracks_with_sonic}
            total={sonicStatus ? sonicStatus.total_tracks : tracks}
            zeroHint={sonicHint}
            action={{
              label: "Refresh analysis",
              icon: "refresh",
              busy: refreshing,
              onClick: () => setConfirmRefresh(true),
            }}
          />
        </div>

        {confirmRefresh && (
          <div className="flash flash-warn mt-3 mb-0">
            <p className="m-0 mb-2">
              Refreshing sonic analysis starts Plex&apos;s MusicAnalysis Butler task, which
              processes the server&apos;s <strong>entire pending backlog</strong> — not just recent
              additions — and can keep running after MusicSeed returns. This may take a long time
              and run in the background on your Plex server.
            </p>
            <div className="flex gap-2">
              <button className="btn btn-primary btn-sm" onClick={doRefresh} disabled={refreshing}>
                {refreshing ? "Starting…" : "Confirm refresh"}
              </button>
              <button className="btn btn-secondary btn-sm" onClick={() => setConfirmRefresh(false)}>
                Cancel
              </button>
            </div>
          </div>
        )}
      </section>
    </>
  );
}
