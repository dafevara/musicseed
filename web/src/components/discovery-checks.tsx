import type { DiscoveryResult } from "@/lib/types";

function StatusIcon({ ok }: { ok: boolean }) {
  return (
    <>
      <svg
        className={`discovery-check-icon ${ok ? "text-[var(--status-ok)]" : "text-[var(--status-problem)]"}`}
        viewBox="0 0 24 24"
        fill="none"
        stroke="currentColor"
        strokeWidth="2.5"
        strokeLinecap="round"
        strokeLinejoin="round"
        aria-hidden="true"
      >
        <path d={ok ? "M5 12l4 4L19 6" : "M6 6l12 12M18 6L6 18"} />
      </svg>
      <span className="sr-only">{ok ? "Passed: " : "Failed: "}</span>
    </>
  );
}

function CheckRow({
  label,
  ok,
  detail,
  guidance,
}: {
  label: string;
  ok: boolean;
  detail?: string | null;
  guidance: string;
}) {
  const heading = <><StatusIcon ok={ok} /><strong>{label}</strong></>;

  return (
    <li>
      {ok ? (
        <div className="discovery-check-heading">{heading}</div>
      ) : (
        <details className="discovery-check-failed">
          <summary className="discovery-check-heading">
            {heading}
            <span className="sr-only"> — show error details</span>
          </summary>
          <div className="discovery-check-explanation">
            {detail && <p>{detail}</p>}
            {guidance !== detail && <p>{guidance}</p>}
          </div>
        </details>
      )}
    </li>
  );
}

function dbGuidance(reason: string | undefined): string {
  switch (reason) {
    case "not_found":
      return "No file at the usual location. If Plex lives somewhere custom, enter the path in Settings.";
    case "not_readable":
      return "The file exists but can't be read. Check its permissions, or run MusicSeed as the same user as Plex.";
    case "invalid_sqlite":
      return "That path isn't a SQLite database — double-check the path.";
    case "not_a_file":
      return "That path isn't a file — double-check the path.";
    default:
      return "No usable Plex database was found. Check the database location and permissions in Settings.";
  }
}

function plexGuidance(reason: string | null): string {
  switch (reason) {
    case "unreachable":
      return "Can't reach Plex at this address. Is Plex Media Server running? If it uses a different host or port, enter the URL in Settings.";
    case "missing_token":
      return "Plex needs a sign-in and none was found on this computer. Choose Sign in with Plex in the setup wizard or Settings (or run 'musicseed-cli plex-login' on the machine running MusicSeed).";
    case "unauthorized":
      return "Plex rejected the saved credentials. Sign in with Plex again in Settings — the account token may have been revoked or replaced.";
    case "library_not_found":
      return "Enter the exact library name in Settings.";
    default:
      return "MusicSeed could not verify the Plex connection. Check the server URL, sign-in, and library name in Settings.";
  }
}

export function DiscoveryChecks({
  result,
  ready: _ready,
}: {
  result: DiscoveryResult;
  ready: boolean;
}) {
  const { musicseed_db, plex_library_db, plex_blobs_db, sonic_vectors, plex_server } = result;
  const dbOk = musicseed_db.reason === "ok" || musicseed_db.reason === "parent_missing";

  return (
    <section className="panel">
      <h2 className="mt-0 text-lg font-semibold">Checks</h2>
      <p className="text-sm muted">
        Import: {result.can_import ? "available" : "needs source access"} ·
        Recommend: {result.can_recommend ? "available locally" : "needs local tracks"} ·
        Write playlists: {result.can_write_playlists ? "available" : "needs Plex connection"}
      </p>
      <ul className="list-none m-0 p-0 grid gap-2.5">
        <CheckRow
          label="MusicSeed database"
          ok={dbOk}
          detail={musicseed_db.detail}
          guidance="Fix the permissions or choose a different location in Settings."
        />
        <CheckRow
          label="Plex library database"
          ok={plex_library_db.ok}
          detail={plex_library_db.detail || plex_library_db.candidates[0]?.detail}
          guidance={dbGuidance(plex_library_db.candidates[0]?.reason || plex_library_db.reason)}
        />
        <CheckRow
          label="Plex blobs database"
          ok={plex_blobs_db.ok}
          detail={plex_blobs_db.detail || plex_blobs_db.candidates[0]?.detail}
          guidance={`${dbGuidance(plex_blobs_db.candidates[0]?.reason || plex_blobs_db.reason)} Sonic vectors are imported into MusicSeed's local store, so the blobs database is only needed when importing them. It normally sits next to the library database with a .blobs.db suffix.`}
        />
        <CheckRow
          label="Sonic vectors (local)"
          ok={sonic_vectors.imported_count > 0}
          guidance="No Plex sonic vectors have been imported. In Library → Coverage → Sonic vectors (local), choose Import vectors to enable the sonic similarity signal in recommendations."
        />
        <CheckRow
          label="Plex server"
          ok={plex_server.ok}
          detail={plex_server.detail}
          guidance={plexGuidance(plex_server.reason)}
        />
      </ul>
    </section>
  );
}
