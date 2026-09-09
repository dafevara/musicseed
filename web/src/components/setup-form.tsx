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
  plex_db_ssh: ["plexDbSsh"],
  db_location: ["musicseedDbPath"],
  enrichment_credentials: ["listenbrainzToken", "spotifyId", "spotifySecret"],
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
  const [plexDbSsh, setPlexDbSsh] = useState("");
  const [plexDbSshPassword, setPlexDbSshPassword] = useState("");
  const [plexDbSshPort, setPlexDbSshPort] = useState("");
  const [remotePlex, setRemotePlex] = useState(false);
  const [musicseedDbPath, setMusicseedDbPath] = useState("");
  const [spotifyId, setSpotifyId] = useState("");
  const [spotifySecret, setSpotifySecret] = useState("");
  const [listenbrainzToken, setListenbrainzToken] = useState("");

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
    if (remotePlex) {
      if (plexDbSsh.trim()) vals.plex_db_ssh = plexDbSsh.trim();
      if (plexDbSshPassword) vals.plex_db_ssh_password = plexDbSshPassword;
      if (plexDbSshPort.trim()) vals.plex_db_ssh_port = plexDbSshPort.trim();
    } else if (plexDbPath.trim()) {
      vals.plex_db_path = plexDbPath.trim();
    }
    if (musicseedDbPath.trim()) vals.musicseed_db_path = musicseedDbPath.trim();
    if (spotifyId.trim()) vals.spotify_client_id = spotifyId.trim();
    if (spotifySecret.trim()) vals.spotify_client_secret = spotifySecret.trim();
    if (listenbrainzToken.trim()) vals.listenbrainz_token = listenbrainzToken.trim();
    onSubmit(vals);
  }

  return (
    <section className="panel">
      <h2 className="mt-0 text-lg font-semibold">Provide the missing values</h2>
      <p className="muted text-sm">
        Fill in what needs attention and re-run the checks. Leave a field blank to
        keep the saved or automatic value. Secrets are saved locally in your configuration
        but never echoed in discovery results.
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
        {(!visible || visible.has("plexDbPath") || visible.has("plexDbSsh")) && (
          <div className="grid gap-2">
            <label className="flex items-center gap-2 text-sm">
              <input
                type="checkbox"
                checked={remotePlex}
                onChange={(e) => setRemotePlex(e.target.checked)}
              />
              Plex is on another machine (fetch the database over SSH)
            </label>
            {!remotePlex ? (
              <label className="grid gap-1 text-sm">
                Plex database path{" "}
                <span className="text-[var(--muted)]">
                  (local path, or a copied/mounted copy)
                </span>
                <input
                  type="text"
                  value={plexDbPath}
                  onChange={(e) => setPlexDbPath(e.target.value)}
                  placeholder="…/com.plexapp.plugins.library.db"
                />
              </label>
            ) : (
              <div className="grid gap-2">
                <label className="grid gap-1 text-sm">
                  SSH target{" "}
                  <span className="text-[var(--muted)]">(scp-style)</span>
                  <input
                    type="text"
                    value={plexDbSsh}
                    onChange={(e) => setPlexDbSsh(e.target.value)}
                    placeholder="user@nas.local:/volume1/Plex/…/Databases"
                  />
                </label>
                <label className="grid gap-1 text-sm">
                  SSH password{" "}
                  <span className="text-[var(--muted)]">
                    (blank keeps the saved password; keys are used if none is saved)
                  </span>
                  <input
                    type="password"
                    value={plexDbSshPassword}
                    onChange={(e) => setPlexDbSshPassword(e.target.value)}
                    autoComplete="off"
                    placeholder="optional"
                  />
                </label>
                <label className="grid gap-1 text-sm">
                  SSH port{" "}
                  <span className="text-[var(--muted)]">(default 22)</span>
                  <input
                    type="text"
                    value={plexDbSshPort}
                    onChange={(e) => setPlexDbSshPort(e.target.value)}
                    placeholder="22"
                  />
                </label>
              </div>
            )}
          </div>
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
        {(!visible || visible.has("listenbrainzToken")) && (
          <label className="grid gap-1 text-sm">
            ListenBrainz user token{" "}
            <span className="text-[var(--muted)]">
              (free — listenbrainz.org/settings; either this or Spotify enables enrichment)
            </span>
            <input
              type="password"
              value={listenbrainzToken}
              onChange={(e) => setListenbrainzToken(e.target.value)}
              autoComplete="off"
              placeholder={result.enrichers.listenbrainz.configured ? "configured" : "not set"}
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
