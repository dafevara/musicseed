import assert from "node:assert/strict";
import test from "node:test";
import { PreviewRunner, PREVIEW_STORAGE_KEY, readSavedPreview, newRequestId } from "../src/lib/preview-job.ts";

const input = { playlistId: "42", query: "method=frequency&limit=40" };
const preview = { playlist_id: "42", recommendations: [{ track_id: 9 }] };
const job = (state, extra = {}) => ({ id: 1, state, ...extra });
const httpError = (status) => Object.assign(new Error(`HTTP ${status}`), { status });
function storage(record = null) {
  let value = record ? JSON.stringify(record) : null;
  return {
    getItem: () => value,
    setItem: (key, next) => { assert.equal(key, PREVIEW_STORAGE_KEY); value = next; },
    removeItem: () => { value = null; },
  };
}
function options(controller = new AbortController()) {
  return { signal: controller.signal, onStatus: () => {} };
}
const noDelay = async (_ms, signal) => { signal?.throwIfAborted(); };
const saved = { ...input, requestId: "saved-request", jobId: 1 };

test("request identity works without the secure-context randomUUID API", () => {
  const first = newRequestId();
  assert.match(first, /^[a-f0-9]{32}$/);
  assert.notEqual(newRequestId(), first);
});

test("a calculation exceeding 60 seconds polls serially and fetches its result once", async () => {
  let starts = 0, polls = 0, results = 0, elapsed = 0, inFlight = 0;
  const client = {
    start: async () => { starts++; return { job_id: 1 }; },
    status: async () => {
      assert.equal(inFlight++, 0);
      await Promise.resolve();
      inFlight--;
      return job(++polls <= 45 ? "running" : "succeeded");
    },
    result: async () => { results++; return preview; },
    cancel: async () => assert.fail("no cancellation expected"),
  };
  const store = storage();
  const runner = new PreviewRunner(client, store, async (ms) => { elapsed += ms; });
  assert.deepEqual(await runner.run(input, options()), preview);
  assert.equal(elapsed, 90_000);
  assert.equal(starts, 1);
  assert.equal(results, 1);
  assert.equal(readSavedPreview(store).jobId, 1);
});

test("page refresh reconnects to a saved job without starting it again", async () => {
  const runner = new PreviewRunner({
    start: async () => assert.fail("refresh must not resubmit"),
    status: async () => job("succeeded"),
    result: async () => preview,
  }, storage(saved), noDelay);
  assert.deepEqual(await runner.run(input, options()), preview);
});

test("a lost submission response retries with the same saved request identity", async () => {
  const ids = [];
  const store = storage();
  const runner = new PreviewRunner({
    start: async (_input, id) => {
      ids.push(id);
      assert.equal(readSavedPreview(store).requestId, id);
      if (ids.length === 1) throw new Error("connection lost after POST");
      return { job_id: 1 };
    },
    status: async () => job("succeeded"),
    result: async () => preview,
  }, store, noDelay, () => "stable-request");
  assert.deepEqual(await runner.run(input, options()), preview);
  assert.deepEqual(ids, ["stable-request", "stable-request"]);
});

test("replacement waits for cooperative cancellation before starting the next job", async () => {
  const events = [];
  let oldPolls = 0;
  const runner = new PreviewRunner({
    start: async () => { events.push("start new"); return { job_id: 2 }; },
    status: async (id) => {
      if (id === 2) return job("succeeded");
      events.push("poll old");
      return job(++oldPolls === 3 ? "canceled" : "running");
    },
    cancel: async () => { events.push("cancel old"); },
    result: async () => preview,
  }, storage(saved), noDelay);
  await runner.run({ ...input, query: "method=average" }, options());
  assert.deepEqual(events, ["poll old", "cancel old", "poll old", "poll old", "start new"]);
});

test("a late result from an aborted caller cannot replace the new calculation", async () => {
  const controller = new AbortController();
  let resolveResult, entered;
  const waiting = new Promise((resolve) => { entered = resolve; });
  let starts = 0;
  const runner = new PreviewRunner({
    start: async () => ({ job_id: ++starts }),
    status: async () => job("succeeded"),
    result: async (id) => {
      if (id === 2) return { ...preview, method: "average" };
      entered();
      return new Promise((resolve) => { resolveResult = resolve; });
    },
  }, storage(), noDelay);
  const first = runner.run(input, options(controller));
  const rejected = assert.rejects(first, { name: "AbortError" });
  await waiting;
  controller.abort();
  const second = runner.run({ ...input, query: "method=average" }, options());
  resolveResult(preview);
  await rejected;
  assert.equal((await second).method, "average");
});

test("temporary status errors reconnect with backoff without creating a new job", async () => {
  let polls = 0;
  const delays = [];
  const runner = new PreviewRunner({
    start: async () => assert.fail("existing job must be reused"),
    status: async () => {
      if (++polls <= 2) throw new Error("offline");
      return job("succeeded");
    },
    result: async () => preview,
  }, storage(saved), async (ms) => { delays.push(ms); });
  assert.deepEqual(await runner.run(input, options()), preview);
  assert.deepEqual(delays, [4000, 8000]);
});

for (const state of ["failed", "canceled", "interrupted"]) {
  test(`${state} stops polling and clears saved identity for retry`, async () => {
    const store = storage(saved);
    let polls = 0;
    const runner = new PreviewRunner({
      status: async () => { polls++; return job(state); },
      result: async () => assert.fail("no result for a terminal error"),
    }, store, noDelay);
    await assert.rejects(runner.run(input, options()), state === "interrupted" ? /API restarted/ : /retry/);
    assert.equal(readSavedPreview(store), null);
    assert.equal(polls, 1);
  });
}

test("missing job clears reload state and surfaces an error", async () => {
  const store = storage(saved);
  const runner = new PreviewRunner({ status: async () => { throw httpError(404); } }, store, noDelay);
  await assert.rejects(runner.run(input, options()), /404/);
  assert.equal(readSavedPreview(store), null);
});

test("storage failures do not prevent calculation or duplicate submission", async () => {
  let starts = 0;
  const denied = () => { throw new Error("storage denied"); };
  const runner = new PreviewRunner({
    start: async () => { starts++; return { job_id: 1 }; },
    status: async () => job("succeeded"), result: async () => preview,
  }, { getItem: denied, setItem: denied, removeItem: denied }, noDelay);
  await runner.run(input, options());
  await runner.run(input, options());
  assert.equal(starts, 1);
});
