"use client";

import { useEffect, useState } from "react";
import type { JobSummary } from "@/lib/types";

export function CalculationProgress({ job, notice, onCancel }: {
  job: JobSummary | null; notice?: string; onCancel: () => void;
}) {
  const [elapsed, setElapsed] = useState(0);
  useEffect(() => {
    const started = job?.started_at
      ? new Date(`${job.started_at.replace(/Z$/, "")}Z`).getTime() : Date.now();
    const update = () => setElapsed(Math.max(0, Math.floor((Date.now() - started) / 1000)));
    update();
    const timer = setInterval(update, 1000);
    return () => clearInterval(timer);
  }, [job?.started_at]);
  const percent = job && job.progress_total > 0
    ? Math.min(100, Math.floor(100 * job.progress_current / job.progress_total)) : null;
  return (
    <div className="rounded-lg border border-[var(--border)] p-4 my-3" aria-busy="true">
      <div className="flex items-center gap-3" role="status" aria-live="polite">
        <span aria-hidden="true" className="inline-block h-5 w-5 shrink-0 rounded-full border-2 border-[var(--border)] border-t-[var(--brand)] animate-spin motion-reduce:animate-none" />
        <div>
          <p className="m-0 font-medium">Calculating recommendations…</p>
          <p className="m-0 mt-1 text-sm muted">Your results will appear here as soon as they’re ready.</p>
          {notice && <p className="m-0 mt-1 text-sm muted">{notice}</p>}
        </div>
      </div>
      <p className="text-xs muted mt-3 mb-2" aria-hidden="true">
        {elapsed < 60 ? `${elapsed}s elapsed` : `${Math.floor(elapsed / 60)}m ${elapsed % 60}s elapsed`}
        {percent !== null && ` · ${percent}% checked`}
      </p>
      {percent !== null && (
        <div className="progress-bar mb-3" role="progressbar" aria-label="Library tracks checked"
          aria-valuemin={0} aria-valuemax={100} aria-valuenow={percent}>
          <div className="fill" style={{ width: `${percent}%` }} />
        </div>
      )}
      <button type="button" className="btn btn-secondary text-sm" onClick={onCancel}>
        Stop calculation
      </button>
    </div>
  );
}
