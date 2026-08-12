"use client";

import { useEffect, useState, useCallback } from "react";
import { useRouter } from "next/navigation";
import { api } from "@/lib/api";
import type { DashboardSnapshot, DiscoveryResponse, JobSummary, PlexServerCheck } from "@/lib/types";
import { HealthStrip } from "@/components/health-strip";
import { JobList } from "@/components/job-list";

export default function DashboardPage() {
  const router = useRouter();
  const [snapshot, setSnapshot] = useState<DashboardSnapshot | null>(null);
  const [plexServer, setPlexServer] = useState<PlexServerCheck | null>(null);
  const [loading, setLoading] = useState(true);
  const [syncing, setSyncing] = useState(false);

  const fetchSnapshot = useCallback(async () => {
    try {
      const data = await api.get<DashboardSnapshot>("/dashboard");
      setSnapshot(data);
    } catch {
      // silently retry — API may not be up yet
    } finally {
      setLoading(false);
    }
  }, []);

  const fetchPlex = useCallback(async () => {
    try {
      const d = await api.get<DiscoveryResponse>("/discovery");
      setPlexServer(d.result.plex_server);
    } catch {
      // ignore — snapshot fallback still renders
    }
  }, []);

  useEffect(() => {
    api.get<DiscoveryResponse>("/discovery").then((d) => {
      if (!d.result.musicseed_db.exists) {
        router.replace("/setup");
        return;
      }
      setPlexServer(d.result.plex_server);
      fetchSnapshot();
    }).catch(() => setLoading(false));
  }, [router, fetchSnapshot]);

  // Poll while jobs are active, skipping when the tab is hidden.
  useEffect(() => {
    if (!snapshot?.active_jobs.length) return;
    const tick = () => {
      if (document.visibilityState === "visible") fetchSnapshot();
    };
    const iv = setInterval(tick, 5000);
    return () => clearInterval(iv);
  }, [snapshot?.active_jobs.length, fetchSnapshot]);

  // Re-probe Plex occasionally (not on every poll) and on window focus.
  useEffect(() => {
    fetchPlex();
    const onVisible = () => {
      if (document.visibilityState === "visible") fetchPlex();
    };
    document.addEventListener("visibilitychange", onVisible);
    return () => document.removeEventListener("visibilitychange", onVisible);
  }, [fetchPlex]);

  async function handleSync() {
    setSyncing(true);
    try {
      await api.post<{ job_id: number }>("/library/import");
      await fetchSnapshot();
    } catch {
      // ignore
    } finally {
      setSyncing(false);
    }
  }

  async function handleEnrich() {
    try {
      await api.post<{ job_id: number }>("/enrichment/spotify");
      await fetchSnapshot();
    } catch {
      // ignore
    }
  }

  async function handleSonicRefresh() {
    try {
      await api.post("/sonic/refresh");
      await fetchSnapshot();
    } catch {
      // ignore
    }
  }

  if (loading) {
    return (
      <div className="panel">
        <p className="muted">Loading…</p>
      </div>
    );
  }

  if (!snapshot) {
    return (
      <div className="panel">
        <p className="muted">Could not reach the MusicSeed API.</p>
      </div>
    );
  }

  const hasActiveImport = snapshot.active_jobs.some((j) => j.kind === "import");

  return (
    <>
      <HealthStrip
        snapshot={snapshot}
        activeJobs={snapshot.active_jobs}
        onEnrich={handleEnrich}
        onSonicRefresh={handleSonicRefresh}
        plexServer={plexServer}
      />

      <section className="panel">
        <h2 className="mt-0 text-lg font-semibold">Activity</h2>

        <JobList jobs={snapshot.active_jobs} recent={snapshot.recent_jobs} />

        {snapshot.last_sync && (
          <p className="muted text-sm mt-3">
            Last sync: {snapshot.last_sync.completed_at || snapshot.last_sync.updated_at}
          </p>
        )}

        <div className="flex flex-wrap gap-2 mt-3">
          {snapshot.library.track_count > 0 && !hasActiveImport && (
            <button className="btn btn-primary" onClick={handleSync} disabled={syncing}>
              {syncing ? "Starting…" : "Sync library"}
            </button>
          )}
        </div>
      </section>
    </>
  );
}
