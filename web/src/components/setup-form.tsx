"use client";

import { useState } from "react";
import type { DiscoveryResult } from "@/lib/types";

// Maps a machine-readable missing-input key to the form fields it needs.
const FIELD_FOR_MISSING: Record<string, string[]> = {
  plex_token: ["plexToken"],
  plex_unreachable: ["plexUrl"],
  plex_server: ["plexUrl"],
  plex_library: ["plexLibrary"],
  plex_db_path: ["plexDbPath"],
  db_location: ["musicseedDbPath"],
  spotify_credentials: ["spotifyId", "spotifySecret"],
};

export function SetupForm({
  result,
  onSubmit,
  missing,
}: {
  result: DiscoveryResult;
  onSubmit: (values: Record<string, string>) => void;
  missing?: string[];
}) {
  const [plexUrl, setPlexUrl] = useState("");
  const [plexToken, setPlexToken] = useState("");
  const [plexLibrary, setPlexLibrary] = useState("");
  const [plexDbPath, setPlexDbPath] = useState("");
  const [musicseedDbPath, setMusicseedDbPath] = useState("");
  const [spotifyId, setSpotifyId] = useState("");
  const [spotifySecret, setSpotifySecret] = useState("");

  const visible =
    missing && missing.length > 0
      ? new Set(missing.flatMap((key) => FIELD_FOR_MISSING[key] ?? []))
      : null;

  function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    const vals: Record<string, string> = {};
    if (plexUrl.trim()) vals.plex_url = plexUrl.trim();
    if (plexToken.trim()) vals.plex_token = plexToken.trim();
    if (plexLibrary.trim()) vals.plex_library = plexLibrary.trim();
    if (plexDbPath.trim()) vals.plex_db_path = plexDbPath.trim();
    if (musicseedDbPath.trim()) vals.musicseed_db_path = musicseedDbPath.trim();
    if (spotifyId.trim()) vals.spotify_client_id = spotifyId.trim();
    if (spotifySecret.trim()) vals.spotify_client_secret = spotifySecret.trim();
    onSubmit(vals);
  }

  return (
    <section className="panel">
      <h2 className="mt-0 text-lg font-semibold">Provide the missing values</h2>
      <p className="muted text-sm">
        Fill in what needs attention and re-run the checks. Leave a field blank to
        keep the automatic value. The token is never stored or displayed.
      </p>
      <form onSubmit={handleSubmit} className="grid gap-3 max-w-md">
        {(!visible || visible.has("plexUrl")) && (
          <label className="grid gap-1 text-sm">
            Plex server URL
            <input
              type="text"
              value={plexUrl}
              onChange={(e) => setPlexUrl(e.target.value)}
              placeholder={result.plex_server.url}
            />
          </label>
        )}
        {(!visible || visible.has("plexToken")) && (
          <label className="grid gap-1 text-sm">
            Plex token
            <input
              type="password"
              value={plexToken}
              onChange={(e) => setPlexToken(e.target.value)}
              autoComplete="off"
              placeholder={result.plex_server.token_configured ? "configured" : "not set"}
            />
          </label>
        )}
        {(!visible || visible.has("plexLibrary")) && (
          <label className="grid gap-1 text-sm">
            Music library name
            <input
              type="text"
              value={plexLibrary}
              onChange={(e) => setPlexLibrary(e.target.value)}
              placeholder={result.plex_server.library || ""}
            />
          </label>
        )}
        {(!visible || visible.has("plexDbPath")) && (
          <label className="grid gap-1 text-sm">
            Plex database path
            <input
              type="text"
              value={plexDbPath}
              onChange={(e) => setPlexDbPath(e.target.value)}
              placeholder="…/com.plexapp.plugins.library.db"
            />
          </label>
        )}
        {(!visible || visible.has("musicseedDbPath")) && (
          <label className="grid gap-1 text-sm">
            MusicSeed database path
            <input
              type="text"
              value={musicseedDbPath}
              onChange={(e) => setMusicseedDbPath(e.target.value)}
              placeholder={result.musicseed_db.path}
            />
          </label>
        )}
        {(!visible || visible.has("spotifyId")) && (
          <label className="grid gap-1 text-sm">
            Spotify client ID{" "}
            <span className="text-[var(--muted)]">(optional — for enrichment)</span>
            <input
              type="text"
              value={spotifyId}
              onChange={(e) => setSpotifyId(e.target.value)}
              placeholder="Spotify Web API client ID"
            />
          </label>
        )}
        {(!visible || visible.has("spotifySecret")) && (
          <label className="grid gap-1 text-sm">
            Spotify client secret
            <input
              type="password"
              value={spotifySecret}
              onChange={(e) => setSpotifySecret(e.target.value)}
              autoComplete="off"
              placeholder={spotifyId ? "configured" : "not set"}
            />
          </label>
        )}
        <button type="submit" className="btn btn-primary justify-self-start">
          Save &amp; re-check
        </button>
      </form>
    </section>
  );
}
