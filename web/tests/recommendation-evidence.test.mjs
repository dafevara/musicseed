import assert from "node:assert/strict";
import test from "node:test";
import { breakdownTitle } from "../src/lib/score-explanation.ts";
import { playlistCreateBody } from "../src/lib/playlist-preview.ts";

const score = {
  total: 0.5, sonic: 0.5, popularity: 0.5, style: 0, genre: 0.5, era: 0.5, novelty: 1,
};

test("tooltip distinguishes neutral, missing-zero, mixed, skipped, and observed evidence", () => {
  const title = breakdownTitle({ ...score, availability: {
    sonic: "neutral_missing", popularity: "mixed", style: "missing",
    genre: "not_applicable", era: "observed", novelty: "observed",
  } });
  assert.match(title, /sonic 50% — neutral fallback/);
  assert.match(title, /popularity 50% — mixed evidence/);
  assert.match(title, /style 0% — missing candidate tags; existing zero-score policy/);
  assert.match(title, /genre 50% — no seed basis/);
  assert.match(title, /era 50% — observed/);
});

test("legacy scores do not acquire invented observed evidence", () => {
  assert.equal(breakdownTitle(score).split("availability not supplied").length - 1, 6);
});

test("creation sends the ordered IDs from the approved preview, not new scoring inputs", () => {
  const body = playlistCreateBody(" Approved ", {
    seed_track_ids: [2, 1], recommendations: [{ track_id: 5 }, { track_id: 3 }],
  });
  assert.deepEqual(body, { name: "Approved", seed_ids: "2,1", track_ids: "5,3" });
  assert.equal(body.limit, undefined);
});

test("empty preview is not a request to regenerate a selection", () => {
  assert.throws(() => playlistCreateBody("Empty", {
    seed_track_ids: [1], recommendations: [],
  }), /nonempty approved preview/);
});
