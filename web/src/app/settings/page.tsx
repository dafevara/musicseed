"use client";

import { useCallback, useEffect, useState } from "react";
import { api } from "@/lib/api";
import type {
  DiscoveryResponse,
  PlexAccount,
  PlexAccountResponse,
  PlexLinkResult,
} from "@/lib/types";
import { DiscoveryChecks } from "@/components/discovery-checks";
import { PageHeader } from "@/components/page-header";
import { PlexSignIn } from "@/components/plex-signin";

function Group({
  title,
  description,
  children,
}: {
  title: string;
  description?: string;
  children: React.ReactNode;
}) {
  return (
    <div className="grid gap-3 border-t border-[var(--border)] pt-4 first:border-t-0 first:pt-0">
      <div>
        <h3 className="m-0 text-base font-semibold">{title}</h3>
        {description && <p className="muted text-sm m-0 mt-1">{description}</p>}
      </div>
      {children}
    </div>
  );
}

export default function SettingsPage() {
  const [data, setData] = useState<DiscoveryResponse | null>(null);
  const [saving, setSaving] = useState(false);
  const [saved, setSaved] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [account, setAccount] = useState<PlexAccount | null>(null);

  const [plexUrl, setPlexUrl] = useState("");
  const [plexUrlEdited, setPlexUrlEdited] = useState(false);
  const [plexToken, setPlexToken] = useState("");
  const [plexLibrary, setPlexLibrary] = useState("");
  const [musicseedDbPath, setMusicseedDbPath] = useState("");
  const [spotifyId, setSpotifyId] = useState("");
  const [spotifySecret, setSpotifySecret] = useState("");
  const [listenbrainzToken, setListenbrainzToken] = useState("");

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

  // Show the URL actually in use instead of leaving it in a placeholder, so a
  // wrong address is visible and correctable.
  useEffect(() => {
    if (!plexUrlEdited && data) setPlexUrl(data.result.plex_server.url);
  }, [data, plexUrlEdited]);

  // Verify the stored token against plex.tv once, so "signed in as …" is real
  // rather than inferred from the presence of a config value.
  useEffect(() => {
    api
      .get<PlexAccountResponse>("/auth/plex/account")
      .then((r) => setAccount(r.account))
      .catch(() => setAccount(null));
  }, []);

  async function handlePlexLinked(result: PlexLinkResult) {
    setAccount(result.account ?? null);
    await load();
  }

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
        listenbrainz_token: listenbrainzToken,
        plex_url: plexUrl,
        plex_token: plexToken,
        plex_library: plexLibrary,
      });
      setPlexToken("");
      setSpotifySecret("");
      setListenbrainzToken("");
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
  const listenbrainz = data?.result.enrichers.listenbrainz;

  return (
    <>
      <PageHeader
        eyebrow="Workspace"
        title="Settings"
        description="Keep your local paths, Plex connection, and optional enrichment services ready for MusicSeed."
      />

      <section className="panel">
        <h2 className="mt-0 text-lg font-semibold">Connection status</h2>
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

        <form onSubmit={handleSave} className="grid gap-6 max-w-md">
          <Group
            title="Plex"
            description="How MusicSeed reaches your Plex Media Server and reads your library."
          >
            <label className="grid gap-1 text-sm">
              Plex server URL
              <input
                type="text"
                value={plexUrl}
                onChange={(e) => {
                  setPlexUrl(e.target.value);
                  setPlexUrlEdited(true);
                }}
                placeholder="http://localhost:32400"
              />
            </label>
            <div className="grid gap-2">
              <h4 className="m-0 text-sm font-semibold">Plex account</h4>
              <p className="m-0 text-sm text-[var(--muted)]">
                {account
                  ? `Signed in as ${account.title || account.username}${
                      account.email ? ` (${account.email})` : ""
                    }.`
                  : plex?.token_configured
                    ? "A Plex token is saved on this computer but plex.tv did not verify it — it may have been revoked."
                    : "Not signed in with Plex."}
              </p>
              <PlexSignIn onLinked={handlePlexLinked} forwardPath="/settings" />
            </div>
            <details className="text-sm">
              <summary className="cursor-pointer text-[var(--muted)]">
                Advanced: paste a Plex token instead
              </summary>
              <label className="grid gap-1 text-sm mt-2">
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
            </details>
            <label className="grid gap-1 text-sm">
              Music library name
              <input
                type="text"
                value={plexLibrary}
                onChange={(e) => setPlexLibrary(e.target.value)}
                placeholder={plex?.library || "Music"}
              />
            </label>
          </Group>

          <Group
            title="MusicSeed database"
            description="Where MusicSeed keeps its local copy of your library."
          >
            <label className="grid gap-1 text-sm">
              MusicSeed database path
              <input
                type="text"
                value={musicseedDbPath}
                onChange={(e) => setMusicseedDbPath(e.target.value)}
                placeholder={data?.result.musicseed_db.path || ""}
              />
            </label>
          </Group>

          <Group
            title="Enrichment (optional)"
            description="Adds popularity and listening data to your recommendations. Either a ListenBrainz token or Spotify credentials is enough — you can also skip this."
          >
            <label className="grid gap-1 text-sm">
              ListenBrainz user token{" "}
              <span className="text-[var(--muted)]">
                ({listenbrainz?.configured ? "configured" : "not set"} — free at listenbrainz.org/settings)
              </span>
              <input
                type="password"
                value={listenbrainzToken}
                onChange={(e) => setListenbrainzToken(e.target.value)}
                autoComplete="off"
                placeholder={listenbrainz?.configured ? "••••••••" : "not set"}
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
          </Group>

          <p className="muted text-sm m-0">
            Anything you leave blank keeps its current value. Passwords and tokens are
            stored locally and are never shown again.
          </p>
          <button type="submit" className="btn btn-primary justify-self-start" disabled={saving}>
            {saving ? "Saving…" : "Save"}
          </button>
        </form>
      </section>
    </>
  );
}
