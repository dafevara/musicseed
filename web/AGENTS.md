# musicseed-web — Agent Guide

`web/` is the local web UI for MusicSeed: a **Next.js + React + TypeScript** single-page app. It is
a **thin rendering layer** — it calls the `musicseed-api` REST API over HTTP and renders JSON. No
business logic, database access, or Plex calls live here; anything that looks like logic belongs in
`core/services/` (orchestrated via `api/handlers/`).

Read the root `AGENTS.md` for product context and repo-wide safety rules, and `api/AGENTS.md` for
the API contract this app consumes. This file covers the web app only.

## Identity

- Distribution name: `musicseed-web`. Node/TypeScript app (no Python package).
- Stack: **Next.js 15 (App Router) + React 19 + TypeScript**, Tailwind CSS, all pages
  `"use client"` (client-rendered SPA — no server components, SSR, or server actions).
- Runtime: Node (`npm`). Dev server on port 3000 via `npm run dev`; it rewrites `/api/*` to the
  standalone API at `http://127.0.0.1:8789` (see `next.config.ts`; override with `API_URL`).
- No dependency on `musicseed-core` or `musicseed-cli` — the only channel to the backend is HTTP.

## Architecture

Every page is a thin client that talks to the JSON API through `src/lib/api.ts`. The API client is
the **single place** that parses error bodies (`{detail}`) and form-encodes POST bodies.

| Page | Calls |
|---|---|
| `src/app/setup/page.tsx` | `GET /discovery`, `POST /discovery/check`, `POST /discovery/init-db`, `GET /library/status`, `POST /library/import`, `POST /enrichment/spotify` |
| `src/app/page.tsx` (dashboard) | `GET /dashboard`, `GET /discovery`, `POST /library/import`, `POST /enrichment/spotify`, `POST /sonic/refresh` |
| `src/app/recommend/page.tsx` | `GET /recommend/presets`, `GET /recommend/typeahead`, `POST /recommend` |
| `src/app/playlists/page.tsx` | `GET /playlists`, `POST /recommend` (create preview), `POST /playlists/create`, `GET /playlists/{name}/preview`, `POST /playlists/{name}/populate` |

Shared components live in `src/components/` (`health-strip`, `job-list`, `job-progress`,
`typeahead`, `seed-chips`, `recommend-results`, `discovery-checks`, `setup-form`, `nav`).
API shapes are typed in `src/lib/types.ts`.

## Particularities to respect

- **No business logic.** Pages parse input, call the API, and render. Recommendation weights,
  scoring, and playlist/populate logic all live in core behind the API. Keep it that way.
- **Mutations require a preview + confirmation.** Playlist create and populate show a preview of
  the exact changes and require an explicit confirm before the mutating POST. Sonic refresh
  explains its whole-backlog impact and requires a separate confirmation. Cancel leaves Plex
  untouched.
- **Secrets never render.** The Plex token and Spotify secret travel in POST bodies only; the UI
  shows configured/not-set, never the value.
- **Polling is back-off aware.** The dashboard only polls `/dashboard` while jobs are active and
  skips polls when `document.visibilityState` is hidden. The Plex server probe runs once on mount
  and on window focus, not every poll.
- **Error messages come from the API client.** `src/lib/api.ts` already extracts `{detail}`; pages
  just show `String(e).replace("Error: ", "")`. Do not re-parse error JSON in pages.

## Run / verify (from `web/`)

```bash
npm install
npm run dev          # Next.js dev server on http://127.0.0.1:3000 (proxies /api to :8789)
npx tsc --noEmit     # type-check
npm run lint         # ESLint
npm run build        # production build
```

The UI needs `musicseed-api` running (`cd ../api && uv run musicseed-api`). There is no separate
web test suite — the API contract is covered by `api/tests/`, and the UI is type-checked with
`tsc`.
