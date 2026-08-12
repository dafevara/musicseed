import type { DiscoveryResult } from "@/lib/types";

function StatusBadge({ ok }: { ok: boolean }) {
  return ok ? (
    <span className="badge badge-ok">ok</span>
  ) : (
    <span className="badge badge-problem">needs attention</span>
  );
}

function dbGuidance(reason: string | undefined, detail: string | null | undefined): string {
  switch (reason) {
    case "not_found":
      return "No file found at the usual location. If Plex lives somewhere custom on this machine, enter the full path below.";
    case "not_readable":
      return "The file exists but this user can't read it. Check its permissions (for example ls -l on the path) or run MusicSeed as the same user as Plex.";
    case "invalid_sqlite":
      return "A file exists at that path but it isn't a SQLite database — double-check the path.";
    case "not_a_file":
      return "That path exists but isn't a file — double-check the path.";
    default:
      return detail || "";
  }
}

function plexGuidance(reason: string | null, detail: string | null): string {
  switch (reason) {
    case "unreachable":
      return "Can't reach Plex at this address. Is Plex Media Server running? If it uses a different host or port, enter the URL below.";
    case "missing_token":
      return "Plex is running but requires a token, and MusicSeed couldn't find one on this machine. To get one: sign in at app.plex.tv/desktop, open your browser's developer tools (Network tab), load any library, find a request with an X-Plex-Token header, and copy its value — then paste it below. The token is stored only in your local config and never shown.";
    case "unauthorized":
      return "Plex rejected the configured token. Paste a valid Plex token below.";
    case "library_not_found":
      return detail || "Enter the exact library name below.";
    default:
      return detail || "";
  }
}

export function DiscoveryChecks({
  result,
  ready: _ready,
}: {
  result: DiscoveryResult;
  ready: boolean;
}) {
  const { musicseed_db, plex_library_db, plex_blobs_db, plex_server } = result;

  return (
    <section className="panel">
      <h2 className="mt-0 text-lg font-semibold">Discovery results</h2>
      <ul className="list-none m-0 p-0 grid gap-4">
        {/* MusicSeed DB */}
        <li>
          <StatusBadge ok={musicseed_db.reason === "ok" || musicseed_db.reason === "parent_missing"} />{" "}
          <strong>MusicSeed database</strong>{" "}
          <code>{musicseed_db.path}</code>{" "}
          <span className="text-[var(--muted)] text-sm">({musicseed_db.source})</span>
          {musicseed_db.reason === "parent_missing" && (
            <p className="mt-1 mb-0 text-sm text-[var(--muted)]">
              Nothing here yet — the database and its folder will be created
              when you confirm setup in a later step.
            </p>
          )}
          {musicseed_db.ok && musicseed_db.creatable && (
            <p className="mt-1 mb-0 text-sm text-[var(--muted)]">
              Will be created here when you confirm setup in a later step.
            </p>
          )}
          {!musicseed_db.ok && (
            <p className="mt-1 mb-0 text-sm text-[var(--muted)]">
              {musicseed_db.detail} Fix the permissions or choose a different location below.
            </p>
          )}
        </li>

        {/* Plex library DB */}
        <li>
          <StatusBadge ok={plex_library_db.ok} />{" "}
          <strong>Plex library database</strong>
          {plex_library_db.selected ? (
            <>
              {" "}
              <code>{plex_library_db.selected.path}</code>{" "}
              <span className="text-[var(--muted)] text-sm">({plex_library_db.selected.source})</span>
            </>
          ) : (
            <p className="mt-1 mb-0 text-sm text-[var(--muted)]">
              {dbGuidance(plex_library_db.candidates[0]?.reason, plex_library_db.candidates[0]?.detail)}
            </p>
          )}
        </li>

        {/* Plex blobs DB */}
        <li>
          <StatusBadge ok={plex_blobs_db.ok} />{" "}
          <strong>Plex blobs database</strong>{" "}
          <span className="text-[var(--muted)] text-sm">(sonic analysis data)</span>
          {plex_blobs_db.selected ? (
            <>
              {" "}
              <code>{plex_blobs_db.selected.path}</code>{" "}
              <span className="text-[var(--muted)] text-sm">({plex_blobs_db.selected.source})</span>
            </>
          ) : (
            <p className="mt-1 mb-0 text-sm text-[var(--muted)]">
              {dbGuidance(plex_blobs_db.candidates[0]?.reason, plex_blobs_db.candidates[0]?.detail)}{" "}
              It normally sits next to the library database with a{" "}
              <code>.blobs.db</code> suffix.
            </p>
          )}
        </li>

        {/* Plex server */}
        <li>
          <StatusBadge ok={plex_server.ok} />{" "}
          <strong>Plex server</strong>{" "}
          <code>{plex_server.url}</code>{" "}
          <span className="text-[var(--muted)] text-sm">({plex_server.source})</span>
          {plex_server.ok ? (
            <p className="mt-1 mb-0 text-sm text-[var(--muted)]">
              Connected — Plex {plex_server.server_version},
              music library &ldquo;{plex_server.library}&rdquo; found.
              Token:{" "}
              {plex_server.token_configured
                ? plex_server.token_source === "local"
                  ? "found on this machine"
                  : "configured"
                : "not set"}
              .
            </p>
          ) : (
            <p className="mt-1 mb-0 text-sm text-[var(--muted)]">
              {plexGuidance(plex_server.reason, plex_server.detail)}
            </p>
          )}
        </li>
      </ul>
    </section>
  );
}
