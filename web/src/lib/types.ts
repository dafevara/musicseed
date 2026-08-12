// ── Discovery ──────────────────────────────

export interface CheckCandidate {
  path: string;
  source: string;
  reason?: string;
  detail?: string | null;
}

export interface CheckResult {
  ok: boolean;
  reason: string;
  path: string;
  source: string;
  detail: string | null;
  selected: { path: string; source: string } | null;
  candidates: CheckCandidate[];
  exists: boolean;
  creatable: boolean;
}

export interface PlexServerCheck {
  ok: boolean;
  url: string;
  source: string;
  server_version: string | null;
  library: string | null;
  token_configured: boolean;
  reason: string | null;
  detail: string | null;
}

export interface DiscoveredPlexServer {
  name: string;
  host: string;
  port: number;
  product: string;
  version: string | null;
  machine_identifier: string | null;
  scheme: string;
}

export interface SpotifyCredentialsCheck {
  configured: boolean;
  client_id_set: boolean;
  client_secret_set: boolean;
}

export interface EnrichmentDiscovery {
  spotify: SpotifyCredentialsCheck;
  listenbrainz_requires_key: boolean;
}

export interface FirstRunStatus {
  no_config: boolean;
  db_missing: boolean;
  library_empty: boolean;
  is_first_run: boolean;
  reasons: string[];
}

export interface DiscoveryResult {
  musicseed_db: CheckResult;
  plex_library_db: CheckResult;
  plex_blobs_db: CheckResult;
  plex_server: PlexServerCheck;
  enrichers: EnrichmentDiscovery;
  first_run: FirstRunStatus;
  missing_inputs: string[];
}

export interface DiscoveryResponse {
  ready: boolean;
  result: DiscoveryResult;
}

export interface PlexServersResponse {
  servers: DiscoveredPlexServer[];
}

// ── Dashboard ──────────────────────────────

export interface EnrichmentCoverage {
  tracks_with_spotify: number;
  tracks_with_listenbrainz: number;
  tracks_with_sonic: number;
  spotify_attempted: number;
  listenbrainz_attempted: number;
}

export interface LibrarySnapshot {
  track_count: number;
  album_count: number;
  artist_count: number;
  play_count: number;
  enrichment: EnrichmentCoverage;
}

export interface LibraryStatus {
  track_count: number;
}

export interface JobSummary {
  id: number;
  kind: string;
  state: string;
  checkpoint: string | null;
  progress_current: number;
  progress_total: number;
  error_summary: string | null;
  result_summary: string | null;
  created_at: string | null;
  updated_at: string | null;
  started_at: string | null;
  completed_at: string | null;
}

export interface DashboardSnapshot {
  library: LibrarySnapshot;
  discovery: {
    plex_server: PlexServerCheck;
  };
  active_jobs: JobSummary[];
  recent_jobs: JobSummary[];
  last_sync: JobSummary | null;
}

// ── Recommend ──────────────────────────────

export interface TypeaheadTrack {
  id: number;
  title: string;
  artist: string | null;
  album: string | null;
  year: number | null;
}

export interface ScoreBreakdown {
  total: number;
  sonic: number;
  popularity: number;
  style: number;
  genre: number;
  era: number;
  novelty: number;
}

export interface RecommendationItem {
  track_id: number;
  title: string;
  artist: string | null;
  score: ScoreBreakdown;
}

export interface RecommendResponse {
  seed_track_ids: number[];
  recommendations: RecommendationItem[];
  sonic_coverage?: { candidates: number; with_vector: number };
  weights?: Record<string, number>;
}

export interface PopulatePreview {
  playlist_name: string;
  playlist_track_count: number;
  matched_track_count: number;
  weights?: Record<string, number>;
  recommendations: RecommendationItem[];
}
