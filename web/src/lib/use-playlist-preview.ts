"use client";

import { useEffect, useRef, useState } from "react";
import { api } from "./api";
import { browserPreviewStorage, PreviewRunner } from "./preview-job";
import type { PreviewInput } from "./preview-job";
import type { JobSummary, PopulatePreview } from "./types";

let sharedRunner: PreviewRunner | null = null;
function runner() {
  if (!sharedRunner) {
    const timed = (signal?: AbortSignal) => signal
      ? AbortSignal.any([signal, AbortSignal.timeout(10_000)]) : AbortSignal.timeout(10_000);
    sharedRunner = new PreviewRunner({
      start: (input, requestId) => api.post<{ job_id: number }>(
        `/playlists/${encodeURIComponent(input.playlistId)}/preview-jobs?${input.query}`,
        { request_id: requestId }, { signal: timed() },
      ),
      status: (id, signal) => api.get<JobSummary>(`/jobs/${id}`, { signal: timed(signal) }),
      result: (id, signal) => api.get<PopulatePreview>(`/playlists/preview-jobs/${id}/result`,
        { signal: timed(signal) }),
      cancel: (id) => api.post(`/jobs/${id}/cancel`, undefined, { signal: timed() }),
    }, browserPreviewStorage);
  }
  return sharedRunner;
}

export function previewQuery(weights: Record<string, number>, method: string): string {
  const query = new URLSearchParams({ limit: "40", method });
  for (const key of Object.keys(weights).sort()) query.set(`w_${key}`, String(weights[key]));
  return query.toString();
}

export function usePlaylistPreview(input: PreviewInput | null, revision = 0) {
  const key = input ? `${input.playlistId}?${input.query}#${revision}` : "";
  const [state, setState] = useState<{
    key: string; busy: boolean; result: PopulatePreview | null;
    job: JobSummary | null; notice: string; error: string | null;
  }>({ key: "", busy: false, result: null, job: null, notice: "", error: null });
  const controller = useRef<AbortController | null>(null);

  useEffect(() => {
    if (!input) return;
    const abort = new AbortController();
    controller.current = abort;
    setState({ key, busy: true, result: null, job: null, notice: "", error: null });
    const timer = setTimeout(() => {
      runner().run(input, {
        signal: abort.signal, fresh: revision > 0,
        onStatus: (job, notice = "") => {
          if (!abort.signal.aborted) setState((prev) => ({ ...prev, job, notice }));
        },
      }).then((result) => {
        if (!abort.signal.aborted) setState((prev) => ({ ...prev, result, busy: false }));
      }).catch((error) => {
        if (!abort.signal.aborted) setState((prev) => ({
          ...prev, busy: false, error: String(error).replace("Error: ", ""),
        }));
      });
    }, 300);
    return () => {
      clearTimeout(timer);
      abort.abort();
      if (controller.current === abort) controller.current = null;
    };
    // The key contains every input; object identity must not restart polling.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [key, revision]);

  async function cancel() {
    const owner = controller.current;
    if (!owner) return;
    owner.abort();
    setState((prev) => ({ ...prev, busy: true, notice: "Stopping calculation…" }));
    try {
      await runner().cancel();
      if (controller.current !== owner) return;
      setState((prev) => ({ ...prev, busy: false, result: null, error: "Calculation canceled. You can retry." }));
    } catch (error) {
      if (controller.current !== owner) return;
      setState((prev) => ({ ...prev, busy: false, error: String(error).replace("Error: ", "") }));
    }
  }

  return {
    ...state, busy: !!input && (state.key !== key || state.busy),
    result: state.key === key ? state.result : null,
    error: state.key === key ? state.error : null,
    cancel, forget: () => runner().forget(),
  };
}
