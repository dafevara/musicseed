"use client";

import { useEffect, useState } from "react";
import { api } from "@/lib/api";
import type { DiscoveryResponse, LibraryStatus } from "@/lib/types";
import { discoveredLocalPlexPath, refreshSetupState, type SetupStep as Step } from "@/lib/setup-state";
import { DiscoveryChecks } from "@/components/discovery-checks";
import { SetupForm } from "@/components/setup-form";
import { SetupIntro } from "@/components/setup-intro";
import { PlexServerPicker } from "@/components/plex-server-picker";
import { HelpIcon } from "@/components/help-icon";
import { JobProgress } from "@/components/job-progress";
import { PageHeader } from "@/components/page-header";

const STEPS: { key: Step; label: string }[] = [
  { key: "detect", label: "Connect Plex" },
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
      setStep("review");
    }
  }

  async function handleSelectServer(url: string) {
    await handleRecheck({ plex_url: url });
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

      <SetupIntro />
      <StepIndicator current={step} />

      {step === "detect" && (
        <section className="panel">
          <h2 className="mt-0 text-lg font-semibold">Connect to Plex</h2>
          <p>
            MusicSeed looks for your Plex Media Server on the local network. Pick a
            server below, or enter its address manually.
          </p>
          <PlexServerPicker onSelect={handleSelectServer} defaultUrl={plex.url} />

          {plex.ok ? (
            <div className="flash flash-ok mt-3">
              Connected to Plex {plex.server_version} — music library &ldquo;{plex.library}
              &rdquo; found.
            </div>
          ) : (
            <div className="flash flash-warn mt-3">
              {plex.reason === "unreachable" &&
                "Plex isn't responding. Make sure Plex Media Server is running, then scan again."}
              {plex.reason === "missing_token" && (
                <>
                  Plex requires a token and none was found on this machine.{" "}
                  <HelpIcon>
                    Sign in at app.plex.tv/desktop, open your browser&apos;s developer tools
                    (Network tab), load any library, find a request with an X-Plex-Token
                    header, and copy its value — then paste it in Settings.
                  </HelpIcon>
                </>
              )}
              {plex.reason !== "unreachable" &&
                plex.reason !== "missing_token" &&
                (plex.detail || "Plex needs attention before continuing.")}
            </div>
          )}

          <div className="flex flex-wrap gap-2 mt-3 items-baseline">
            <button className="btn btn-primary" onClick={() => setStep("review")}>
              Continue
            </button>
            <a href="/settings" className="text-sm text-[var(--muted)] underline">
              Open Settings to configure manually
            </a>
          </div>
        </section>
      )}

      {step === "review" && (
        <>
          <DiscoveryChecks result={data.result} ready={data.ready} />

          {saved && (
            <div className={data.ready ? "flash flash-ok" : "flash flash-warn"}>
              <p className="m-0">
                Saved &amp; re-checked.{" "}
                {data.ready
                  ? "All checks passed — continue below."
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

          {saveError && (
            <div className="flash flash-error">
              <p className="m-0">{saveError}</p>
            </div>
          )}

          {!data.ready && (
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
