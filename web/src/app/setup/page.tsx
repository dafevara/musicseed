"use client";

import { useEffect, useState } from "react";
import { api } from "@/lib/api";
import type { DiscoveryResponse, LibraryStatus } from "@/lib/types";
import { DiscoveryChecks } from "@/components/discovery-checks";
import { SetupForm } from "@/components/setup-form";
import { JobProgress } from "@/components/job-progress";

type Phase =
  | "loading"
  | "not_ready"
  | "ready"
  | "db_init_error"
  | "db_created"
  | "importing"
  | "import_done"
  | "enriching"
  | "done";

function resolvePhase(d: DiscoveryResponse, status: LibraryStatus | null): Phase {
  if (d.result.musicseed_db.exists) {
    return status && status.track_count > 0 ? "done" : "db_created";
  }
  return d.ready ? "ready" : "not_ready";
}

export default function SetupPage() {
  const [data, setData] = useState<DiscoveryResponse | null>(null);
  const [libraryStatus, setLibraryStatus] = useState<LibraryStatus | null>(null);
  const [phase, setPhase] = useState<Phase>("loading");
  const [dbError, setDbError] = useState<string | null>(null);
  const [jobId, setJobId] = useState<number | null>(null);
  const [jobKind, setJobKind] = useState<string | null>(null);
  const [formValues, setFormValues] = useState<Record<string, string>>({});

  async function bootstrap() {
    try {
      const d = await api.get<DiscoveryResponse>("/discovery");
      setData(d);
      let status: LibraryStatus | null = null;
      if (d.result.musicseed_db.exists) {
        try {
          status = await api.get<LibraryStatus>("/library/status");
        } catch {
          status = null;
        }
      }
      setLibraryStatus(status);
      setPhase(resolvePhase(d, status));
    } catch {
      setPhase("loading");
    }
  }

  // Auto-discover on load
  useEffect(() => {
    bootstrap();
  }, []);

  async function handleRecheck(vals: Record<string, string>) {
    setFormValues(vals);
    setPhase("loading");
    try {
      const result = await api.post<DiscoveryResponse>("/discovery/check", vals);
      setData(result);
      setPhase(resolvePhase(result, libraryStatus));
    } catch {
      setPhase("not_ready");
    }
  }

  async function handleInitDb() {
    if (!data) return;
    setPhase("loading");
    setDbError(null);
    try {
      await api.post("/discovery/init-db", {
        musicseed_db_path: data.result.musicseed_db.path,
        spotify_client_id: formValues.spotify_client_id || "",
        spotify_client_secret: formValues.spotify_client_secret || "",
        plex_url: formValues.plex_url || data.result.plex_server.url,
        plex_token: formValues.plex_token || "",
        plex_library: formValues.plex_library || data.result.plex_server.library || "",
        plex_db_path: formValues.plex_db_path || data.result.plex_library_db.selected?.path || "",
      });
      await bootstrap();
    } catch (e) {
      setDbError(String(e).replace("Error: ", ""));
      setPhase("db_init_error");
    }
  }

  async function handleStartImport() {
    setPhase("importing");
    try {
      const { job_id } = await api.post<{ job_id: number }>("/library/import");
      setJobId(job_id);
      setJobKind("import");
    } catch {
      setPhase("db_created");
    }
  }

  async function handleStartEnrich() {
    setPhase("enriching");
    try {
      const { job_id } = await api.post<{ job_id: number }>("/enrichment/spotify");
      setJobId(job_id);
      setJobKind("enrich");
    } catch {
      setPhase("import_done");
    }
  }

  function handleJobDone() {
    if (jobKind === "import") {
      setPhase("import_done");
    } else {
      setPhase("done");
    }
  }

  if (phase === "loading" && !data) {
    return (
      <div className="panel">
        <p className="muted">Checking your setup&hellip;</p>
      </div>
    );
  }

  if (phase === "done") {
    return (
      <div className="panel">
        <h2 className="mt-0 text-lg font-semibold">MusicSeed is ready</h2>
        <p>Your Plex library has been imported and enriched. You can now:</p>
        <ul className="list-disc pl-5">
          <li>
            <a href="/" className="text-[var(--brand)] underline">
              Go to the dashboard
            </a>{" "}
            to review your library state.
          </li>
          <li>
            Use <code>musicseed recommend</code> in the CLI to create playlists.
          </li>
        </ul>
      </div>
    );
  }

  return (
    <>
      {/* Explain shell — only on first visit */}
      {phase !== "importing" && phase !== "enriching" && phase !== "import_done" && (
        <section className="panel">
          <h2 className="mt-0 text-lg font-semibold">Welcome to MusicSeed</h2>
          <p>Before anything is imported, setup checks four things on this machine:</p>
          <ol className="list-decimal pl-5">
            <li>Where MusicSeed&apos;s own database should live — created later, only when you confirm.</li>
            <li>Your Plex library database (read-only) — where your artists, albums, and tracks are.</li>
            <li>Your Plex blobs database (read-only) — where Plex&apos;s sonic analysis data lives.</li>
            <li>A connection to your Plex server, including access to your music library.</li>
          </ol>
          <p className="muted text-sm">
            Checks run automatically and never modify anything. If something needs attention,
            you can correct the values and retry right here — no restart required.
          </p>
        </section>
      )}

      {/* Discovery checks */}
      {data && (phase === "not_ready" || phase === "ready" || phase === "db_init_error" || phase === "db_created") && (
        <>
          <DiscoveryChecks result={data.result} ready={data.ready} />

          {data.ready && (
            <section className="panel">
              <h2 className="mt-0 text-lg font-semibold">Review your setup</h2>

              {dbError && (
                <div className="flash flash-error">
                  <p className="m-0">{dbError}</p>
                </div>
              )}
              {phase === "db_created" && (
                <div className="flash flash-ok">
                  Database created at <code>{data.result.musicseed_db.path}</code>.
                </div>
              )}

              <dl className="grid grid-cols-[max-content_1fr] gap-x-4 gap-y-1.5 mb-4 text-sm">
                <dt className="font-semibold">MusicSeed database</dt>
                <dd className="m-0">
                  <code>{data.result.musicseed_db.path}</code>
                  {!data.result.musicseed_db.exists && (
                    <span className="text-[var(--muted)] ml-1">(will be created)</span>
                  )}
                </dd>
                <dt className="font-semibold">Plex library DB</dt>
                <dd className="m-0">
                  <code>{data.result.plex_library_db.selected?.path}</code>
                </dd>
                <dt className="font-semibold">Plex blobs DB</dt>
                <dd className="m-0">
                  <code>{data.result.plex_blobs_db.selected?.path}</code>
                </dd>
                <dt className="font-semibold">Plex server</dt>
                <dd className="m-0">
                  <code>{data.result.plex_server.url}</code> — Plex {data.result.plex_server.server_version}
                </dd>
                <dt className="font-semibold">Music library</dt>
                <dd className="m-0">{data.result.plex_server.library}</dd>
                <dt className="font-semibold">Plex token</dt>
                <dd className="m-0">
                  {data.result.plex_server.token_configured ? "•••••••• (configured)" : "not set"}
                </dd>
              </dl>

              {phase === "db_created" ? (
                <div>
                  <p className="muted text-sm">
                    The database is ready. The next step imports your Plex library
                    and enriches tracks with external metadata.
                  </p>
                  <button className="btn btn-primary" onClick={handleStartImport}>
                    Start import
                  </button>
                </div>
              ) : phase === "db_init_error" ? (
                <div>
                  <p className="muted text-sm">
                    Database initialization failed. Check the error above and try again,
                    or choose a different path using the form below.
                  </p>
                  <button className="btn btn-primary" onClick={handleInitDb}>
                    Try again
                  </button>
                </div>
              ) : (
                <div>
                  <p className="muted text-sm">
                    Nothing has been changed yet. Press the button below to create the
                    MusicSeed database at the path shown above. This is safe and idempotent —
                    it never replaces an existing database.
                  </p>
                  <button className="btn btn-primary" onClick={handleInitDb}>
                    Initialize database
                  </button>
                </div>
              )}
            </section>
          )}

          {!data.ready && (
            <SetupForm result={data.result} onSubmit={handleRecheck} />
          )}
        </>
      )}

      {/* Job progress */}
      {(phase === "importing" || phase === "enriching") && jobId && (
        <JobProgress jobId={jobId} kind={jobKind!} onDone={handleJobDone} />
      )}

      {/* Post-import: offer enrich */}
      {phase === "import_done" && (
        <section className="panel">
          <h2 className="mt-0 text-lg font-semibold">Enrichment</h2>
          <p>
            Enrichment fetches popularity and metadata from Spotify&apos;s Web API
            using the credentials you provided during setup.
          </p>
          <p className="muted text-sm">
            Tracks will be looked up to add popularity data
            and cross-reference IDs. This may take several minutes.
          </p>
          <button className="btn btn-primary" onClick={handleStartEnrich}>
            Continue with enrichment
          </button>
        </section>
      )}


    </>
  );
}
