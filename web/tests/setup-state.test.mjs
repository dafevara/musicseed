import assert from "node:assert/strict";
import test from "node:test";
import {
  discoveredLocalPlexPath, refreshSetupState, resolveSetupStep,
} from "../src/lib/setup-state.ts";

function discovery(incomplete, exists = true) {
  return { result: {
    first_run: { import_incomplete: incomplete }, musicseed_db: { exists },
    can_import: true, plex_server: { ok: false },
  } };
}

const partial = { track_count: 5, import_coverage: { ever_succeeded: false } };
const complete = { track_count: 10, import_coverage: { ever_succeeded: true } };

test("job recovery refreshes discovery as well as library counts", async () => {
  const calls = [];
  let recovered = false;
  const fetchDiscovery = async () => {
    calls.push("discovery");
    return discovery(!recovered);
  };
  const fetchStatus = async () => {
    calls.push("status");
    return recovered ? complete : partial;
  };
  assert.equal((await refreshSetupState(fetchDiscovery, fetchStatus)).step, "review");
  recovered = true;
  assert.equal((await refreshSetupState(fetchDiscovery, fetchStatus)).step, "done");
  assert.deepEqual(calls, ["discovery", "status", "discovery", "status"]);
  assert.equal(resolveSetupStep(discovery(true), complete), "review");
});

test("unknown provenance is not treated as verified from track counts", () => {
  assert.equal(resolveSetupStep(discovery(false), partial), "review");
});

test("database absence skips status, and status failure stays recoverable", async () => {
  const noDatabase = await refreshSetupState(
    async () => discovery(false, false),
    async () => assert.fail("must not query a missing database"),
  );
  assert.equal(noDatabase.status, null);
  assert.equal(noDatabase.step, "review"); // can import locally without Plex HTTP
  const unavailable = await refreshSetupState(async () => discovery(false), async () => {
    throw new Error("fixture database failure");
  });
  assert.equal(unavailable.step, "review");
  await assert.rejects(refreshSetupState(async () => {
    throw new Error("fixture discovery failure");
  }, async () => complete), /discovery failure/);
});

test("SSH display paths are never persisted as local initialization paths", () => {
  const result = (source, path) => ({ plex_library_db: { selected: { source, path } } });
  assert.equal(discoveredLocalPlexPath(result("ssh", "nas:/db/library.db")), "");
  assert.equal(discoveredLocalPlexPath(result("config", "/fixture/plex.db")), "/fixture/plex.db");
  assert.equal(discoveredLocalPlexPath({ plex_library_db: { selected: null } }), "");
});
