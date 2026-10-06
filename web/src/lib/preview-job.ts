import type { JobSummary, PopulatePreview } from "./types";

export interface PreviewInput { playlistId: string; query: string }
export interface SavedPreview extends PreviewInput { requestId: string; jobId: number | null }
export interface PreviewClient {
  start(input: PreviewInput, requestId: string): Promise<{ job_id: number }>;
  status(jobId: number, signal?: AbortSignal): Promise<JobSummary>;
  result(jobId: number, signal?: AbortSignal): Promise<PopulatePreview>;
  cancel(jobId: number): Promise<unknown>;
}
export interface PreviewStorage {
  getItem(key: string): string | null;
  setItem(key: string, value: string): void;
  removeItem(key: string): void;
}
export const PREVIEW_STORAGE_KEY = "musicseed.playlist-preview";
const TERMINAL = new Set(["succeeded", "failed", "canceled", "interrupted"]);

export function newRequestId(): string {
  // getRandomValues also works when MusicSeed is served over HTTP on a home LAN.
  return Array.from(crypto.getRandomValues(new Uint8Array(16)),
    (value) => value.toString(16).padStart(2, "0")).join("");
}

export const browserPreviewStorage: PreviewStorage = {
  getItem: (key) => window.sessionStorage.getItem(key),
  setItem: (key, value) => window.sessionStorage.setItem(key, value),
  removeItem: (key) => window.sessionStorage.removeItem(key),
};

export function readSavedPreview(storage: PreviewStorage): SavedPreview | null {
  try {
    const value = JSON.parse(storage.getItem(PREVIEW_STORAGE_KEY) || "null");
    if (value && typeof value.playlistId === "string" && typeof value.query === "string"
      && typeof value.requestId === "string"
      && (value.jobId === null || (Number.isSafeInteger(value.jobId) && value.jobId > 0))) {
      return value;
    }
  } catch { /* Storage can be unavailable or contain an older format. */ }
  return null;
}

function hasStatus(error: unknown, status: number) {
  return !!error && typeof error === "object" && "status" in error && error.status === status;
}

export function abortableDelay(ms: number, signal?: AbortSignal): Promise<void> {
  return new Promise((resolve, reject) => {
    if (signal?.aborted) { reject(new DOMException("Aborted", "AbortError")); return; }
    const abort = () => {
      clearTimeout(timer);
      signal?.removeEventListener("abort", abort);
      reject(new DOMException("Aborted", "AbortError"));
    };
    const timer = setTimeout(() => {
      signal?.removeEventListener("abort", abort);
      resolve();
    }, ms);
    signal?.addEventListener("abort", abort, { once: true });
  });
}

/** Serialize replacements, retain job identity through refresh, and ignore canceled callers. */
export class PreviewRunner {
  private tail: Promise<unknown> = Promise.resolve();
  private saved: SavedPreview | null;
  private client: PreviewClient;
  private storage: PreviewStorage;
  private delay: typeof abortableDelay;
  private requestId: () => string;
  constructor(
    client: PreviewClient,
    storage: PreviewStorage,
    delay = abortableDelay,
    requestId = newRequestId,
  ) {
    this.client = client;
    this.storage = storage;
    this.delay = delay;
    this.requestId = requestId;
    this.saved = readSavedPreview(storage);
  }

  private save(value: SavedPreview | null) {
    this.saved = value;
    try {
      if (value) this.storage.setItem(PREVIEW_STORAGE_KEY, JSON.stringify(value));
      else this.storage.removeItem(PREVIEW_STORAGE_KEY);
    } catch { /* The in-memory record still prevents duplicate submissions. */ }
  }

  private enqueue<T>(work: () => Promise<T>): Promise<T> {
    const task = this.tail.then(work);
    this.tail = task.catch(() => {});
    return task;
  }

  cancel(): Promise<void> {
    return this.enqueue(async () => {
      if (this.saved) await this.stop(this.saved);
    });
  }

  forget(): void { this.save(null); }

  private async stop(record: SavedPreview, signal?: AbortSignal) {
    signal?.throwIfAborted();
    let id = record.jobId;
    if (id === null) {
      try { id = (await this.client.start(record, record.requestId)).job_id; }
      catch (error) {
        if (hasStatus(error, 409)) { this.save(null); return; }
        throw error;
      }
      this.save({ ...record, jobId: id });
    }
    try {
      const status = await this.client.status(id, signal);
      if (!TERMINAL.has(status.state)) {
        await this.client.cancel(id);
        while (!TERMINAL.has((await this.client.status(id, signal)).state)) {
          await this.delay(300, signal);
        }
      }
    } catch (error) { if (!hasStatus(error, 404)) throw error; }
    this.save(null);
  }

  run(input: PreviewInput, {
    signal, onStatus, fresh = false,
  }: {
    signal: AbortSignal;
    onStatus: (job: JobSummary | null, notice?: string) => void;
    fresh?: boolean;
  }): Promise<PopulatePreview> {
    return this.enqueue(async () => {
      signal.throwIfAborted();
      if (this.saved && (fresh || this.saved.playlistId !== input.playlistId
        || this.saved.query !== input.query)) {
        onStatus(null, "Stopping the previous calculation…");
        await this.stop(this.saved, signal);
      }
      signal.throwIfAborted();
      let record = this.saved || { ...input, requestId: this.requestId(), jobId: null };
      this.save(record);
      let failures = 0;
      while (record.jobId === null) {
        signal.throwIfAborted();
        try {
          const started = await this.client.start(input, record.requestId);
          record = { ...record, jobId: started.job_id };
          this.save(record);
        } catch (error) {
          signal.throwIfAborted();
          if (hasStatus(error, 409)) {
            onStatus(null, "Waiting for another calculation to finish…");
          } else {
            if (hasStatus(error, 400) || hasStatus(error, 422)) { this.save(null); throw error; }
            if (++failures >= 5) throw error;
            onStatus(null, "Reconnecting to your calculation…");
          }
          await this.delay(2000, signal);
        }
      }
      failures = 0;
      while (true) {
        signal.throwIfAborted();
        try {
          const job = await this.client.status(record.jobId, signal);
          signal.throwIfAborted();
          onStatus(job);
          if (job.state === "succeeded") {
            const result = await this.client.result(record.jobId, signal);
            signal.throwIfAborted();
            return result;
          }
          if (TERMINAL.has(job.state)) {
            this.save(null);
            throw new Error(job.state === "interrupted"
              ? "The API restarted before the calculation finished. Please retry."
              : job.error_summary || `Calculation ${job.state}. You can retry.`);
          }
          failures = 0;
        } catch (error) {
          signal.throwIfAborted();
          if (!this.saved || hasStatus(error, 404)) { this.save(null); throw error; }
          if (++failures >= 5) throw error;
          onStatus(null, "Reconnecting to your calculation…");
        }
        await this.delay(Math.min(8000, 2000 * 2 ** failures), signal);
      }
    });
  }
}
