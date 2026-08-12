"use client";

import { useEffect, useState } from "react";
import { api } from "@/lib/api";
import type { DiscoveryResponse, LibraryStatus } from "@/lib/types";
import { DiscoveryChecks } from "@/components/discovery-checks";
import { SetupForm } from "@/components/setup-form";
import { PlexServerPicker } from "@/components/plex-server-picker";
import { JobProgress } from "@/components/job-progress";

type Step = "detect" | "review" | "importing" | "enriching" | "done";

const STEPS: { key: Step; label: string }[] = [
  { key: "detect", label: "Connect Plex" },
  { key: "review", label: "Review & initialize" },
  { key: "importing", label: "Import & enrich" },
  { key: "done", label: "Done" },
];

function resolveStep(d: DiscoveryResponse, status: LibraryStatus | null): Step {
  if (status && status.track_count > 0) return "done";
  if (d.result.musicseed_db.exists) return "review";
  return "detect";
}

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
  const [jobId, setJobId] = useState<number | null>(null);
  const [jobKind, setJobKind] = useState<string | null>(null);
  const [formValues, setFormValues] = useState<Record<string, string>>({});

  async function refreshStatus() {
    try {
      const status = await api.get<LibraryStatus>("/library/status");
      setLibraryStatus(status);
    } catch {
      // ignore — status is advisory
    }
  }

  async function bootstrap() {
    try {
      const d = await api.get<DiscoveryResponse>("/discovery");
      setData(d);
      let status: LibraryStatus | null = null;
      if (d.result.musicseed_db.exists) {
        status = await api.get<LibraryStatus>("/library/status").catch(() => null);
      }
      setLibraryStatus(status);
      setStep(resolveStep(d, status));
    } catch {
      setStep("detect");
    }
  }

  useEffect(() => {
    bootstrap();
  }, []);

  async function handleRecheck(vals: Record<string, string>) {
    setFormValues(vals);
    try {
      const result = await api.post<DiscoveryResponse>("/discovery/check", vals);
      setData(result);
      setStep(resolveStep(result, libraryStatus));
    } catch {
      setStep("review");
    }
  }

  async function handleSelectServer(url: string) {
    const vals = { ...formValues, plex_url: url };
    await handleRecheck(vals);
  }

  async function handleInitDb() {
    if (!data) return;
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
    }
  }

  async function handleStartImport() {
    setStep("importing");
    try {
      const { job_id } = await api.post<{ job_id: number }>("/library/import");
      setJobId(job_id);
      setJobKind("import");
    } catch {
      setStep("review");
    }
  }

  async function handleStartEnrich() {
    setStep("enriching");
    try {
      const { job_id } = await api.post<{ job_id: number }>("/enrichment/spotify");
      setJobId(job_id);
      setJobKind("enrich");
    } catch {
      setStep("done");
    }
  }

  async function handleJobDone() {
    if (jobKind === "import") {
      await refreshStatus();
      setStep("review");
    } else {
      setStep("done");
    }
  }

  if (!data) {
    return (
      <div className="panel">
        <p className="muted">Checking your setup&hellip;</p>
      </div>
    );
  }

  const plex = data.result.plex_server;
  const trackCount = libraryStatus?.track_count ?? 0;

  return (
    <>
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
              {plex.reason === "unreachable"
                ? "Plex isn't responding. Make sure Plex Media Server is running, then scan again."
                : plex.detail ||
                  "Plex needs attention before continuing. You can finish the remaining details on the next step."}
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

          {dbError && (
            <div className="flash flash-error">
              <p className="m-0">{dbError}</p>
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
              <h2 className="mt-0 text-lg font-semibold">Review your setup</h2>
              <dl className="grid grid-cols-[max-content_1fr] gap-x-4 gap-y-1.5 mb-4 text-sm">
                <dt className="font-semibold">MusicSeed database</dt>
                <dd className="m-0">
                  <code>{data.result.musicseed_db.path}</code>
                  <span className="text-[var(--muted)] ml-1">(will be created)</span>
                </dd>
                <dt className="font-semibold">Plex server</dt>
                <dd className="m-0">
                  <code>{plex.url}</code> — Plex {plex.server_version}
                </dd>
                <dt className="font-semibold">Music library</dt>
                <dd className="m-0">{plex.library}</dd>
                <dt className="font-semibold">Spotify enrichment</dt>
                <dd className="m-0">
                  {data.result.enrichers.spotify.configured
                    ? "configured"
                    : "not set (optional — ListenBrainz needs no key)"}
                </dd>
              </dl>
              <p className="muted text-sm">
                Nothing has been changed yet. Press the button below to create the
                MusicSeed database at the path shown above. This is safe and idempotent —
                it never replaces an existing database.
              </p>
              <button className="btn btn-primary" onClick={handleInitDb}>
                Initialize database
              </button>
            </section>
          )}

          {data.ready && data.result.musicseed_db.exists && trackCount === 0 && (
            <section className="panel">
              <h2 className="mt-0 text-lg font-semibold">Import your library</h2>
              <p>
                The database is ready but empty. Import your Plex library to start
                recommending.
              </p>
              <button className="btn btn-primary" onClick={handleStartImport}>
                Start import
              </button>
            </section>
          )}

          {data.ready && data.result.musicseed_db.exists && trackCount > 0 && (
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
      )}

      {(step === "importing" || step === "enriching") && jobId && (
        <JobProgress jobId={jobId} kind={jobKind!} onDone={handleJobDone} />
      )}
    </>
  );
}
