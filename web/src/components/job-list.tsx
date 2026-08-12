"use client";

import { useEffect, useRef, useState } from "react";
import { api } from "@/lib/api";
import type { JobSummary } from "@/lib/types";

function relativeTime(iso: string | null): string {
  if (!iso) return "";
  const diff = (Date.now() - new Date(iso + "Z").getTime()) / 1000;
  if (diff < 5) return "just now";
  if (diff < 60) return `${Math.floor(diff)}s ago`;
  if (diff < 3600) return `${Math.floor(diff / 60)}m ago`;
  if (diff < 86400) return `${Math.floor(diff / 3600)}h ago`;
  return `${Math.floor(diff / 86400)}d ago`;
}

function formatETA(seconds: number): string {
  if (seconds <= 0) return "";
  if (seconds < 60) return `~${Math.ceil(seconds)}s`;
  if (seconds < 3600) {
    const m = Math.floor(seconds / 60);
    const s = Math.round(seconds % 60);
    return s > 0 ? `~${m}m ${s}s` : `~${m}m`;
  }
  const h = Math.floor(seconds / 3600);
  const m = Math.round((seconds % 3600) / 60);
  return m > 0 ? `~${h}h ${m}m` : `~${h}h`;
}

function parseResult(resultSummary: string | null): Record<string, number> | null {
  if (!resultSummary) return null;
  try {
    return JSON.parse(resultSummary);
  } catch {
    return null;
  }
}

function formatResult(job: JobSummary): React.ReactNode {
  const result = parseResult(job.result_summary);
  if (!result) {
    if (job.checkpoint) return job.checkpoint;
    return null;
  }

  if (job.kind === "import") {
    const parts: string[] = [];
    if (result.tracks) parts.push(`${result.tracks.toLocaleString()} tracks`);
    if (result.artists) parts.push(`${result.artists.toLocaleString()} artists`);
    if (result.albums) parts.push(`${result.albums.toLocaleString()} albums`);
    if (result.play_history) parts.push(`${result.play_history.toLocaleString()} plays`);
    return parts.join(" · ");
  }

  if (job.kind === "enrich") {
    const parts: string[] = [];
    if (result.enriched !== undefined) parts.push(`${result.enriched.toLocaleString()} enriched`);
    if (result.total) parts.push(`of ${result.total.toLocaleString()} tracks`);
    if (result.errors) parts.push(`${result.errors} errors`);
    return parts.join(" · ");
  }

  return job.checkpoint;
}

function JobRow({
  job,
  polling,
  onDeleted,
}: {
  job: JobSummary;
  polling?: boolean;
  onDeleted?: (id: number) => void;
}) {
  const [state, setState] = useState(job.state);
  const [current, setCurrent] = useState(job.progress_current);
  const [total, setTotal] = useState(job.progress_total);
  const [checkpoint, setCheckpoint] = useState(job.checkpoint);
  const [error, setError] = useState(job.error_summary);
  const [resultSummary, setResultSummary] = useState(job.result_summary);
  const [completedAt, setCompletedAt] = useState(job.completed_at);
  const [eta, setEta] = useState("");
  const [deleting, setDeleting] = useState(false);

  const etaStart = useRef<{ time: number; current: number } | null>(null);

  const isTerminal = state === "succeeded" || state === "failed" || state === "canceled";
  const canDelete =
    state === "succeeded" ||
    state === "failed" ||
    state === "canceled" ||
    state === "interrupted";

  async function handleDelete() {
    setDeleting(true);
    try {
      await api.delete<{ deleted: boolean }>(`/jobs/${job.id}`);
      onDeleted?.(job.id);
    } catch {
      setDeleting(false);
    }
  }

  function updateProgress(j: JobSummary) {
    setState(j.state);
    setCurrent(j.progress_current);
    setTotal(j.progress_total);
    setCheckpoint(j.checkpoint);
    setError(j.error_summary);
    setResultSummary(j.result_summary);
    setCompletedAt(j.completed_at);

    if (j.state === "running" && j.progress_total > 0 && j.progress_current > 0) {
      const now = Date.now();
      if (!etaStart.current || etaStart.current.current >= j.progress_current) {
        etaStart.current = { time: now, current: j.progress_current };
        setEta("");
        return;
      }
      const elapsed = (now - etaStart.current.time) / 1000;
      const progressed = j.progress_current - etaStart.current.current;
      if (progressed > 0 && elapsed > 1) {
        const rate = progressed / elapsed;
        const remaining = (j.progress_total - j.progress_current) / rate;
        setEta(formatETA(remaining));
      }
    }
  }

  useEffect(() => {
    let cancelled = false;

    async function fetchOnce() {
      try {
        const j = await api.get<JobSummary>(`/jobs/${job.id}`);
        if (cancelled) return;
        updateProgress(j);
      } catch {
        // ignore
      }
    }

    fetchOnce();

    if (!polling || isTerminal) return;

    const iv = setInterval(async () => {
      try {
        const j = await api.get<JobSummary>(`/jobs/${job.id}`);
        if (cancelled) return;
        updateProgress(j);
        if (j.state === "succeeded" || j.state === "failed" || j.state === "canceled") {
          clearInterval(iv);
        }
      } catch {
        clearInterval(iv);
      }
    }, 2000);

    return () => {
      cancelled = true;
      clearInterval(iv);
    };
  }, [polling, job.id, job.state]);

  const pct = total > 0 ? Math.round((current / total) * 100) : 0;
  const jobResult = resultSummary || job.result_summary;
  const jobError = error || job.error_summary;

  const statusIcon = () => {
    switch (state) {
      case "succeeded": return <span className="activity-dot activity-dot-ok" />;
      case "failed":
      case "canceled": return <span className="activity-dot activity-dot-problem" />;
      default: return <span className="activity-dot activity-dot-running" />;
    }
  };

  const statusLabel = () => {
    switch (state) {
      case "succeeded": return "Completed";
      case "failed": return "Failed";
      case "canceled": return "Canceled";
      case "running": return "Running";
      case "pending": return "Pending";
      default: return state;
    }
  };

  const kindLabel = job.kind === "import" ? "Library sync" : "Enrichment";

  return (
    <div className="activity-row">
      {statusIcon()}
      <div className="activity-body">
        <div className="activity-header">
          <span className="activity-kind">{kindLabel}</span>
          <span className={`activity-status activity-status-${state}`}>
            {statusLabel()}
          </span>
          {(state === "running" || state === "pending") && (
            <span className="activity-checkpoint">{checkpoint}</span>
          )}
        </div>

        {state === "running" && total > 0 && (
          <div className="activity-progress">
            <div className="progress-bar">
              <div className="fill" style={{ width: `${pct}%` }} />
            </div>
            <span className="activity-progress-label">
              {current.toLocaleString()} / {total.toLocaleString()}
              {eta && <span className="activity-eta"> · {eta} left</span>}
            </span>
          </div>
        )}

        {isTerminal && (
          <div className="activity-result">
            {state === "succeeded" && formatResult({ ...job, state, checkpoint, result_summary: jobResult })}
            {state === "failed" && jobError && (
              <span className="text-[var(--status-problem)]">{jobError}</span>
            )}
            {state === "canceled" && "Canceled by user"}
          </div>
        )}

        <span className="activity-time">
          {isTerminal ? relativeTime(completedAt || job.completed_at) : relativeTime(job.started_at)}
        </span>
      </div>

      {canDelete && (
        <button
          type="button"
          className="activity-delete"
          title="Delete entry"
          aria-label={`Delete ${kindLabel} entry`}
          disabled={deleting}
          onClick={handleDelete}
        >
          {deleting ? "…" : "×"}
        </button>
      )}
    </div>
  );
}

export function JobList({
  jobs,
  recent,
  onDeleted,
}: {
  jobs: JobSummary[];
  recent: JobSummary[];
  onDeleted?: (id: number) => void;
}) {
  const hasJobs = jobs.length > 0 || recent.length > 0;

  return (
    <div className="activity-list">
      {!hasJobs && (
        <p className="muted text-sm">No recent activity.</p>
      )}

      {jobs.map((j) => (
        <JobRow key={j.id} job={j} polling onDeleted={onDeleted} />
      ))}

      {recent
        .filter((j) => !jobs.some((a) => a.id === j.id))
        .map((j) => (
          <JobRow key={j.id} job={j} onDeleted={onDeleted} />
        ))}
    </div>
  );
}
