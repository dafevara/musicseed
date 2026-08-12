"use client";

import { useCallback, useEffect, useState } from "react";
import { api } from "@/lib/api";
import type { DiscoveryResponse } from "@/lib/types";
import { DiscoveryChecks } from "@/components/discovery-checks";

export default function SettingsPage() {
  const [data, setData] = useState<DiscoveryResponse | null>(null);
  const [saving, setSaving] = useState(false);
  const [saved, setSaved] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const [plexUrl, setPlexUrl] = useState("");
  const [plexToken, setPlexToken] = useState("");
  const [plexLibrary, setPlexLibrary] = useState("");
  const [plexDbPath, setPlexDbPath] = useState("");
  const [musicseedDbPath, setMusicseedDbPath] = useState("");
  const [spotifyId, setSpotifyId] = useState("");
  const [spotifySecret, setSpotifySecret] = useState("");

  const load = useCallback(async () => {
    try {
      const d = await api.get<DiscoveryResponse>("/discovery");
      setData(d);
    } catch {
      setData(null);
    }
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  async function handleSave(e: React.FormEvent) {
    e.preventDefault();
    setSaving(true);
    setError(null);
    setSaved(false);
    try {
      await api.post("/discovery/config", {
        musicseed_db_path: musicseedDbPath,
        spotify_client_id: spotifyId,
        spotify_client_secret: spotifySecret,
        plex_url: plexUrl,
        plex_token: plexToken,
        plex_library: plexLibrary,
        plex_db_path: plexDbPath,
      });
      setPlexToken("");
      setSpotifySecret("");
      setSaved(true);
      await load();
    } catch (e) {
      setError(String(e).replace("Error: ", ""));
    } finally {
      setSaving(false);
    }
  }

  const plex = data?.result.plex_server;
  const spotify = data?.result.enrichers.spotify;

  return (
    <>
      <section className="panel">
        <h2 className="mt-0 text-lg font-semibold">Settings</h2>
        <p className="muted text-sm">
          Update your Plex connection, database location, and enrichment credentials.
          Saving here never starts an import, enrichment, or database initialization.
        </p>

        {data && <DiscoveryChecks result={data.result} ready={data.ready} />}
      </section>

      <section className="panel">
        <h2 className="mt-0 text-lg font-semibold">Configuration</h2>

        {saved && (
          <div className="flash flash-ok">
            <p className="m-0">Saved.</p>
          </div>
        )}
        {error && (
          <div className="flash flash-error">
            <p className="m-0">{error}</p>
          </div>
        )}

        <form onSubmit={handleSave} className="grid gap-3 max-w-md">
          <label className="grid gap-1 text-sm">
            Plex server URL
            <input
              type="text"
              value={plexUrl}
              onChange={(e) => setPlexUrl(e.target.value)}
              placeholder={plex?.url || "http://localhost:32400"}
            />
          </label>
          <label className="grid gap-1 text-sm">
            Plex token{" "}
            <span className="text-[var(--muted)]">
              ({plex?.token_configured ? "configured" : "not set"} — paste a new one to replace)
            </span>
            <input
              type="password"
              value={plexToken}
              onChange={(e) => setPlexToken(e.target.value)}
              autoComplete="off"
              placeholder={plex?.token_configured ? "••••••••" : "not set"}
            />
          </label>
          <label className="grid gap-1 text-sm">
            Music library name
            <input
              type="text"
              value={plexLibrary}
              onChange={(e) => setPlexLibrary(e.target.value)}
              placeholder={plex?.library || "Music"}
            />
          </label>
          <label className="grid gap-1 text-sm">
            Plex database path
            <input
              type="text"
              value={plexDbPath}
              onChange={(e) => setPlexDbPath(e.target.value)}
              placeholder={data?.result.plex_library_db.selected?.path || "…/com.plexapp.plugins.library.db"}
            />
          </label>
          <label className="grid gap-1 text-sm">
            MusicSeed database path
            <input
              type="text"
              value={musicseedDbPath}
              onChange={(e) => setMusicseedDbPath(e.target.value)}
              placeholder={data?.result.musicseed_db.path || ""}
            />
          </label>
          <label className="grid gap-1 text-sm">
            Spotify client ID{" "}
            <span className="text-[var(--muted)]">
              ({spotify?.client_id_set ? "configured" : "not set"} — optional)
            </span>
            <input
              type="text"
              value={spotifyId}
              onChange={(e) => setSpotifyId(e.target.value)}
              placeholder={spotify?.client_id_set ? "configured" : "Spotify Web API client ID"}
            />
          </label>
          <label className="grid gap-1 text-sm">
            Spotify client secret{" "}
            <span className="text-[var(--muted)]">
              ({spotify?.client_secret_set ? "configured" : "not set"} — optional)
            </span>
            <input
              type="password"
              value={spotifySecret}
              onChange={(e) => setSpotifySecret(e.target.value)}
              autoComplete="off"
              placeholder={spotify?.client_secret_set ? "••••••••" : "not set"}
            />
          </label>
          <p className="muted text-sm m-0">
            Leave a field blank to keep its current value. ListenBrainz needs no key.
          </p>
          <button type="submit" className="btn btn-primary justify-self-start" disabled={saving}>
            {saving ? "Saving…" : "Save"}
          </button>
        </form>
      </section>
    </>
  );
}
