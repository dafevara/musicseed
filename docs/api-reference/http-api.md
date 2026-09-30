# HTTP API

The API returns JSON and delegates to framework-free [handlers](api-handlers.md), which call
[core services](core-services.md). The web UI consumes HTTP; CLI and MCP use core directly.

## Server modes and OpenAPI

| Launch mode | JSON base URL | Operation schema |
|---|---|---|
| `musicseed` | `http://127.0.0.1:8789/api` | `/api/openapi.json` |
| `musicseed --no-ui` | `http://127.0.0.1:8789` | `/openapi.json` |
| `uv run --project api uvicorn musicseed_api.app:app` | `http://127.0.0.1:8000` | `/openapi.json` |
| `./scripts/dev.sh` API process | `http://127.0.0.1:8789` | `/openapi.json` |

`musicseed` mounts the API at `/api` even if `web/out/` is missing. Its parent app's
`/openapi.json` does not describe the mounted operations; use `/api/openapi.json` and
`/api/docs`. Unprefixed modes expose interactive docs at `/docs`. Contributor Next.js serves
on port 3000 and proxies browser `/api/*` requests to the unprefixed API.

The live OpenAPI schema is the request-contract source of truth. Many routes currently return
plain `dict`/`list[dict]`, so their OpenAPI response schemas are generic; consult the handler
references and route tests for detailed response fields. No separate hand-maintained schema is
required.

## Request encoding

POST bodies for discovery/settings, enrichment credentials, recommendation, and playlist writes
are **form fields**, not JSON. ID lists in forms are comma-separated strings. GET parameters
are query parameters. `POST /sonic/refresh` also takes query parameters; job/import actions
take no body. All paths below are relative to the JSON base URL.

Read-only examples for the normal product server:

```bash
curl http://127.0.0.1:8789/api/library/status
curl 'http://127.0.0.1:8789/api/recommend/typeahead?q=radiohead'
curl -X POST http://127.0.0.1:8789/api/recommend \
  --data-urlencode 'seed_ids=123' --data 'limit=20' --data 'method=average'
```

Replace `123` with a local track ID from typeahead. `POST /recommend` only previews; its response
contains `seed_track_ids`, `method`, recommendations with `track_id`, per-signal `score` and
`availability`, `sources`, `sonic_coverage`, and effective `weights`. This is a different shape
from the nested service/MCP DTOs (`recommendations[].track.id`).

## Operations

| Area | Routes | Behavior |
|---|---|---|
| Discovery | `GET /discovery`, `POST /discovery/check`, `GET /discovery/plex-servers` | Probe local state/Plex; check accepts secret overrides in the body |
| Configuration | `POST /discovery/config`, `POST /discovery/init-db` | Save settings only, or save and initialize the local database |
| Library | `GET /library/status`, `POST /library/import` | Status or submit an incremental import job |
| Enrichment | `POST /enrichment/listenbrainz`, `POST /enrichment/spotify` | Save supplied credentials and submit enrichment jobs |
| Recommendations | `GET /recommend/presets`, `GET /recommend/typeahead`, `POST /recommend` | Presets, seed search, and read-only recommendations |
| Playlists | `GET /playlists`, `POST /playlists/create` | List Plex audio playlists or write an approved selection |
| Population | `GET /playlists/{playlist_id}/preview`, `POST /playlists/{playlist_id}/populate` | Preview complements or append approved IDs |
| Sonic | `GET /sonic/status`, `POST /sonic/refresh`, `POST /sonic/import` | Plex coverage, trigger/watch analysis, or submit local vector import |
| Dashboard | `GET /dashboard` | Snapshot; `check_server=true` also probes Plex |
| Jobs | `GET /jobs/{job_id}`, `POST /jobs/{job_id}/cancel`, `DELETE /jobs/{job_id}` | Poll, request cooperative cancellation, or delete terminal history |

Import, enrichment, and sonic import return `{"job_id": ...}`; poll the job route for progress.
One persisted writer claim per database prevents overlapping managed jobs. Pending and
cancel-requested jobs keep the claim until the worker finishes. Settings changes are rejected
while a managed writer is active. See [recovery](../infra/troubleshooting.md).

`POST /sonic/refresh` is synchronous and triggers Plex's **whole pending MusicAnalysis backlog**.
Its `days` parameter scopes watching/reporting, not the remote work.

## Playlist approval and retries

- `POST /playlists/create` requires `name`, `seed_ids`, and approved `track_ids`. Seeds come
  first; both ID lists must be nonempty positive SQLite integers.
- `POST /playlists/{playlist_id}/populate` requires a nonempty approved `track_ids` list.
  `playlist_id` is Plex's string rating key, not a local track ID or playlist title.
- Writes preserve approved order, deduplicate IDs, and reject stale/unmapped selections before
  any Plex write. Weights and filters belong to preview requests. Approval is enforced by the
  client workflow; routes do not store a preview or verify an approval token.
- Create retries reuse a playlist only when its name and ordered contents match exactly.
  A name collision with different contents raises `PlexAPIError` (HTTP 502).
- Populate skips tracks already in Plex. The HTTP response currently reports `added_count`;
  core/MCP also expose `already_present_count`.

Seed recommendation defaults to 50 results and accepts `per_seed_limit` and `min_score`.
HTTP playlist preview defaults to 40 results and exposes method, year filters, artist cap, and
six weights; it does not expose `per_seed_limit` or `min_score`. Core/MCP populate previews
default to 10 and expose both. Consult the generated signatures for surface-specific defaults.

## Error contract

| Exception or validation | HTTP status |
|---|---|
| `NotFoundError` | 404 |
| `ConfigurationError` | 400 |
| `JobConflictError` | 409 |
| `PlexAPIError` | 502 |
| Other `MusicSeedError` | 500 |
| FastAPI request validation (such as missing required fields) | 422 |

Typed errors return `{"detail": "..."}`; FastAPI validation details are structured lists.
Playlist routes explicitly reject malformed approved-ID lists and invalid methods with 400.
Some optional numeric fields are strings converted inside routes; malformed values are not all
covered by FastAPI's 422 validation. These mappings do not promise that every invalid request
currently receives a structured validation response.
