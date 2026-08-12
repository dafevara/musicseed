"use client";

import { useEffect, useState, useCallback } from "react";
import { api } from "@/lib/api";
import type { JobSummary } from "@/lib/types";

export function JobProgress({
  jobId,
  kind,
  onDone,
}: {
  jobId: number;
  kind: string;
  onDone: () => void;
}) {
  const [job, setJob] = useState<JobSummary | null>(null);

  const poll = useCallback(async () => {
    try {
      const j = await api.get<JobSummary>(`/jobs/${jobId}`);
      setJob(j);
      if (j.state === "succeeded" || j.state === "failed" || j.state === "canceled") {
        onDone();
      }
    } catch {
      // ignore
    }
  }, [jobId, onDone]);

  useEffect(() => {
    poll();
    const tick = () => {
      if (document.visibilityState === "visible") poll();
    };
    const iv = setInterval(tick, 2000);
    return () => clearInterval(iv);
  }, [poll]);

  if (!job) {
    return (
      <section className="panel">
        <p className="muted">Starting job&hellip;</p>
      </section>
    );
  }

  const pct =
    job.progress_total > 0
      ? Math.round((job.progress_current / job.progress_total) * 100)
      : 0;

  return (
    <section className="panel">
      <h2 className="mt-0 text-lg font-semibold capitalize">{kind}</h2>

      {job.state === "succeeded" && (
        <div className="flash flash-ok">Complete — {job.checkpoint || ""}</div>
      )}
      {job.state === "failed" && (
        <div className="flash flash-error">{job.error_summary || "Unknown error"}</div>
      )}
      {job.state === "canceled" && (
        <div className="flash flash-ok" style={{ background: "var(--bg)", borderColor: "var(--border)", color: "var(--muted)" }}>
          Canceled
        </div>
      )}

      {(job.state === "running" || job.state === "pending") && (
        <>
          <p className="text-sm">
            {job.checkpoint || "Working…"}
            {job.progress_total > 0 && (
              <span className="text-[var(--muted)] ml-1">
                ({job.progress_current} / {job.progress_total})
              </span>
            )}
          </p>
          {job.progress_total > 0 && (
            <div className="progress-bar mb-3">
              <div className="fill" style={{ width: `${pct}%` }} />
            </div>
          )}
          {job.state === "running" && (
            <form
              onSubmit={async (e) => {
                e.preventDefault();
                await api.post(`/jobs/${jobId}/cancel`);
              }}
            >
              <button type="submit" className="btn btn-danger">
                Cancel
              </button>
            </form>
          )}
        </>
      )}
    </section>
  );
}
