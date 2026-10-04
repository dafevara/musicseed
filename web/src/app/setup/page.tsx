"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { api } from "@/lib/api";
import type { DiscoveryResponse, LibraryStatus } from "@/lib/types";
import { discoveredLocalPlexPath, refreshSetupState, type SetupStep as Step } from "@/lib/setup-state";
import { DiscoveryChecks } from "@/components/discovery-checks";
import { SetupForm } from "@/components/setup-form";
import { SetupIntro } from "@/components/setup-intro";
import { PlexServerPicker } from "@/components/plex-server-picker";
import { PlexSignIn } from "@/components/plex-signin";
import { HelpIcon } from "@/components/help-icon";
import { JobProgress } from "@/components/job-progress";
import { PageHeader } from "@/components/page-header";

const STEPS: { key: Step; label: string }[] = [
  { key: "detect", label: "Sign in & connect" },
  { key: "review", label: "Review & initialize" },
  { key: "importing", label: "Import & enrich" },
  { key: "done", label: "Done" },
];

const MISSING_LABELS: Record<string, string> = {
  plex_token: "Plex token",
  plex_unreachable: "Plex server URL (unreachable)",
  plex_server: "Plex server URL",
  plex_library: "Plex library name",
  plex_db_path: "Plex database path",
  plex_db_ssh: "Plex SSH target",
  db_location: "MusicSeed database location",
  enrichment_credentials: "enrichment credentials",
};

function StepIndicator({ current }: { current: Step }) {
  const activeIndex = STEPS.findIndex((s) => s.key === current);
  return (
    <ol className="list-none m-0 mb-4 p-0 flex flex-wrap gap-1.5">
      {STEPS.map((s, i) => (
        <li
          key={s.key}
          className={`text-xs px-2.5 py-1 rounded-full border ${
            i === activeIndex
              ? "bg-[var(--brand)] text-white border-[var(--brand)] font-semibold"
              : i < activeIndex
                ? "text-[var(--fg)] border-[var(--border)]"
                : "text-[var(--muted)] border-[var(--border)]"
          }`}
        >
          {s.label}
        </li>
      ))}
    </ol>
  );
}

export default function SetupPage() {
  const [data, setData] = useState<DiscoveryResponse | null>(null);
  const [libraryStatus, setLibraryStatus] = useState<LibraryStatus | null>(null);
  const [step, setStep] = useState<Step>("detect");
  const [dbError, setDbError] = useState<string | null>(null);
  const [saveError, setSaveError] = useState<string | null>(null);
  const [saved, setSaved] = useState(false);
  const [jobId, setJobId] = useState<number | null>(null);
  const [jobKind, setJobKind] = useState<string | null>(null);
  // Bumped after a Plex sign-in so the server picker re-scans with the account
  // token and reveals servers that became reachable through the sign-in.
  const [plexScanKey, setPlexScanKey] = useState(0);

  async function applyDiscovery(discover: () => Promise<DiscoveryResponse>) {
    const fresh = await refreshSetupState(
      discover, () => api.get<LibraryStatus>("/library/status"),
    );
    setData(fresh.discovery);
    setLibraryStatus(fresh.status);
    setStep(fresh.step);
  }

  async function bootstrap() {
    setSaved(false);
    setSaveError(null);
    try {
      await applyDiscovery(() => api.get<DiscoveryResponse>("/discovery"));
    } catch (e) {
      setSaveError(String(e).replace("Error: ", ""));
      setStep("detect");
    }
  }

  useEffect(() => {
    bootstrap();
  }, []);

  async function handleRecheck(vals: Record<string, string>) {
    setSaveError(null);
    setSaved(false);
    try {
      // Persist (save-only) so the selected server, token, and library name
      // survive navigation, then return the fresh discovery result.
      const result = await api.post<DiscoveryResponse>("/discovery/config", vals);
      await applyDiscovery(() => Promise.resolve(result));
      setSaved(true);
    } catch (e) {
      setSaveError(String(e).replace("Error: ", ""));
    }
  }

  async function handleSelectServer(url: string) {
    await handleRecheck({ plex_url: url });
  }

  // A completed Plex sign-in wrote the token to the local config; re-probe so
  // the wizard reflects it (server connection, library, and step) immediately.
  async function handlePlexLinked() {
    setSaveError(null);
    setSaved(false);
    try {
      await applyDiscovery(() => api.get<DiscoveryResponse>("/discovery"));
      setPlexScanKey((key) => key + 1);
    } catch (e) {
      setSaveError(String(e).replace("Error: ", ""));
    }
  }

  async function handleInitDb() {
    if (!data) return;
    setDbError(null);
    try {
      await api.post("/discovery/init-db", {
        musicseed_db_path: data.result.musicseed_db.path,
        // Credentials/source overrides were already saved; do not replay stale fields.
        plex_url: data.result.plex_server.url,
        plex_library: data.result.plex_server.library || "",
        plex_db_path: discoveredLocalPlexPath(data.result),
      });
      await bootstrap();
    } catch (e) {
      setDbError(String(e).replace("Error: ", ""));
    }
  }

  async function handleStartImport() {
    setStep("importing");
    try {
      const { job_id } = await api.post<{ job_id: number }>("/library/import");
      setJobId(job_id);
      setJobKind("import");
    } catch (e) {
      setSaveError(String(e).replace("Error: ", ""));
      setStep("review");
    }
  }

  async function handleStartEnrich() {
    setStep("enriching");
    const source = data?.result.enrichers.listenbrainz.configured
      ? "listenbrainz"
      : "spotify";
    try {
      const { job_id } = await api.post<{ job_id: number }>(`/enrichment/${source}`);
      setJobId(job_id);
      setJobKind(`enrich:${source}`);
    } catch (e) {
      setSaveError(String(e).replace("Error: ", ""));
      setStep("review");
    }
  }

  async function handleJobDone() {
    setJobId(null);
    setJobKind(null);
    // Refresh both sources of state, including interrupted-import flags.
    await bootstrap();
  }

  if (!data) {
    return (
      <div className="panel">
        <p className="muted">{saveError || "Checking your setup…"}</p>
        {saveError && (
          <>
            <button className="btn btn-primary" onClick={bootstrap}>Retry</button>
            <a href="/settings" className="ml-3 underline">Repair settings</a>
          </>
        )}
      </div>
    );
  }

  const plex = data.result.plex_server;
  const trackCount = libraryStatus?.track_count ?? 0;

  return (
    <>
      <PageHeader
        eyebrow="Welcome"
        title="Set up MusicSeed"
        description="Connect Plex, prepare your local library, and start building recommendations from the music you already own."
      />

      <p className="m-0 text-sm muted">
        Need a hand? <Link href="/quick-start" className="underline">Follow the Quick Start guides</Link>
        {" "}for installation, configuration, and importing from a remote Plex server.
      </p>

      <SetupIntro />
      <StepIndicator current={step} />

      {saveError && (
        <div className="flash flash-error" role="alert">
          <p className="m-0">{saveError}</p>
        </div>
      )}

      {step === "detect" && (
        <>
          <section className="panel">
            <h2 className="mt-0 text-lg font-semibold">Sign in with Plex</h2>
            <p>
              Start here. Signing in tells MusicSeed which servers you can use —
              including servers on other networks — and lets it save playlists to Plex
              later. There is no token to copy, and your Plex password never reaches
              MusicSeed.
            </p>
            <PlexSignIn onLinked={handlePlexLinked} forwardPath="/setup" />
            {plex.token_configured && (
              <p className="mt-3 mb-0 text-sm muted">
                A Plex token is already saved on this computer. Sign in again to
                replace it.
              </p>
            )}
          </section>

          <section className="panel">
            <h2 className="mt-0 text-lg font-semibold">Choose your Plex server</h2>
            <p>
              {plex.token_configured
                ? "These are the servers available to your Plex account. Pick one — MusicSeed checks each address from this computer."
                : "MusicSeed looks for Plex servers on the local network. Sign in above to also see servers on other networks. Pick one, or enter its address manually."}
            </p>
            <PlexServerPicker
              key={plexScanKey}
              onSelect={handleSelectServer}
              defaultUrl={plex.url}
            />

            <p className="text-sm muted">
              {data.result.plex_library_db.ok
                ? "Plex database files were found. These let MusicSeed read library data, but do not authenticate the connection to Plex. "
                : "Database access and the Plex server connection are checked separately. "}
              You can also continue with local import and recommendations, and connect
              Plex later.
            </p>

            {plex.ok ? (
              <div className="flash flash-ok mt-3">
                Connected to Plex {plex.server_version} — music library &ldquo;{plex.library}
                &rdquo; found.
              </div>
            ) : (
              <div className="flash flash-warn mt-3">
                {plex.reason === "unreachable" &&
                  `Plex isn't responding at ${plex.url}. Plex advertises addresses that may only work on its own network — pick one marked reachable above, or enter an address that works from this computer.`}
                {plex.reason === "missing_token" &&
                  "Plex needs a sign-in and none was found on this computer. Sign in with Plex above — or paste a token manually under Advanced."}
                {plex.reason !== "unreachable" &&
                  plex.reason !== "missing_token" &&
                  (plex.detail || "Plex needs attention before continuing.")}
              </div>
            )}

            <div className="flex flex-wrap gap-2 mt-3 items-baseline">
              {(plex.ok || data.result.can_import) && (
                <button className="btn btn-secondary" onClick={() => setStep("review")}>
                  {plex.ok ? "Continue" : "Continue without Plex connection"}
                </button>
              )}
              <a href="/settings" className="text-sm text-[var(--muted)] underline">
                Open Settings to configure manually
              </a>
            </div>
          </section>
          <SetupForm
            result={data.result}
            onSubmit={handleRecheck}
            missing={["plex_server", "plex_token", "plex_library"]}
          />
        </>
      )}

      {step === "review" && (
        <>
          <DiscoveryChecks result={data.result} ready={data.ready} />

          {saved && (
            <div className={data.ready ? "flash flash-ok" : "flash flash-warn"}>
              <p className="m-0">
                Saved &amp; re-checked.{" "}
                {data.ready
                  ? "Local import is ready — continue below."
                  : `Still need: ${(data.result.missing_inputs || [])
                      .map((k) => MISSING_LABELS[k] || k)
                      .join(", ")}.`}
              </p>
            </div>
          )}

          <section className="panel">
            <h2 className="mt-0 text-lg font-semibold">Status</h2>
            <ul className="list-disc pl-5 m-0 text-sm grid gap-1">
              <li>
                Plex server:{" "}
                {plex.ok
                  ? "connected"
                  : `not connected — ${plex.detail || plex.reason || "unknown"}`}
              </li>
              <li>
                Plex library database:{" "}
                {data.result.plex_library_db.ok
                  ? "found"
                  : `not found — ${data.result.plex_library_db.candidates[0]?.detail || "check the path"}`}
              </li>
              <li>
                Plex blobs database:{" "}
                {data.result.plex_blobs_db.ok
                  ? "found"
                  : "not found (sonic vectors can't be imported until it is)"}
              </li>
              <li>
                MusicSeed database:{" "}
                {data.result.musicseed_db.exists ? "exists" : "not created yet"}
              </li>
            </ul>
          </section>

          {dbError && (
            <div className="flash flash-error">
              <p className="m-0">{dbError}</p>
            </div>
          )}

          {(!data.ready || !plex.ok) && (
            <>
              <SetupForm
                result={data.result}
                onSubmit={handleRecheck}
                missing={data.result.missing_inputs}
              />
              <p className="muted text-sm">
                Prefer the full form?{" "}
                <a href="/settings" className="text-[var(--brand)] underline">
                  Open Settings
                </a>
                .
              </p>
            </>
          )}

          {data.ready && !data.result.musicseed_db.exists && (
            <section className="panel">
              <h2 className="mt-0 text-lg font-semibold">Initialize</h2>
              <div className="flex flex-wrap items-baseline gap-2">
                <button className="btn btn-primary" onClick={handleInitDb}>
                  Initialize database
                </button>
                <HelpIcon>
                  Creates the MusicSeed database at{" "}
                  <code>{data.result.musicseed_db.path}</code>. Safe and idempotent —
                  it never replaces an existing database.
                </HelpIcon>
              </div>
              <p className="mt-2 mb-0 text-sm text-[var(--muted)]">
                {data.result.enrichers.listenbrainz.configured
                  ? "ListenBrainz enrichment configured."
                  : data.result.enrichers.spotify.configured
                    ? "Spotify enrichment configured."
                    : "No enrichment credentials — add a ListenBrainz token (free) or Spotify credentials."}
              </p>
            </section>
          )}

          {data.ready && data.result.musicseed_db.exists && (trackCount === 0 || data.result.first_run.import_incomplete) && (
            <section className="panel">
              <h2 className="mt-0 text-lg font-semibold">
                {trackCount === 0 ? "Import your library" : "Import stopped early"}
              </h2>
              {trackCount === 0 ? (
                <p>
                  The database is ready but empty. Import your Plex library to start
                  recommending.
                </p>
              ) : (
                <p>
                  MusicSeed has {trackCount.toLocaleString()} tracks
                  {libraryStatus?.import_coverage
                    ? `, Plex has ${libraryStatus.import_coverage.tracks.plex.toLocaleString()}`
                    : ""}
                  . Resume the import to finish.
                </p>
              )}
              <button className="btn btn-primary" onClick={handleStartImport}>
                {trackCount === 0 ? "Start import" : "Resume import"}
              </button>
            </section>
          )}

          {data.ready && data.result.musicseed_db.exists && trackCount > 0 && !data.result.first_run.import_incomplete && (
            <section className="panel">
              <h2 className="mt-0 text-lg font-semibold">Enrichment</h2>
              <p>
                Enrichment fetches popularity and metadata from Spotify&apos;s Web API
                using the credentials you provided. This may take several minutes.
              </p>
              <div className="flex flex-wrap gap-2">
                <button className="btn btn-primary" onClick={handleStartEnrich}>
                  Continue with enrichment
                </button>
                <button className="btn btn-secondary" onClick={() => setStep("done")}>
                  Skip for now
                </button>
              </div>
            </section>
          )}
        </>
      )}

      {step === "done" && (
        <div className="panel">
          <h2 className="mt-0 text-lg font-semibold">MusicSeed is ready</h2>
          <p>Your local library is available. Enrichment and sonic-vector import are optional.</p>
          <ul className="list-disc pl-5">
            <li>
              <a href="/" className="text-[var(--brand)] underline">
                Go to the dashboard
              </a>{" "}
              to review your library state.
            </li>
            <li>
              Use <code>musicseed-cli recommend</code> in the CLI to create playlists.
            </li>
          </ul>
          {data.result.sonic_vectors.imported_count === 0 && (
            <p className="mt-3 mb-0 text-sm text-[var(--muted)]">
              Plex sonic vectors aren&apos;t imported yet —{" "}
              <a href="/settings" className="text-[var(--brand)] underline">
                import them from Settings
              </a>{" "}
              to enable the sonic similarity signal.
            </p>
          )}
        </div>
      )}

      {(step === "importing" || step === "enriching") && jobId && (
        <>
          <section className="panel">
            <h2 className="mt-0 text-lg font-semibold">
              {jobKind === "import" ? "Importing your library" : "Enriching your library"}
            </h2>
            <p className="muted text-sm m-0">
              {jobKind === "import"
                ? "Reading artists, albums, tracks, and play history from Plex into " +
                  "MusicSeed's local database. For a remote Plex server it first downloads " +
                  "the database files — this can take a few minutes."
                : "Fetching popularity and metadata from ListenBrainz or Spotify for your tracks."}
            </p>
          </section>
          <JobProgress jobId={jobId} kind={jobKind!} onDone={handleJobDone} />
        </>
      )}
    </>
  );
}
