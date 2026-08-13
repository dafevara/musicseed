import type { DiscoveryResult } from "@/lib/types";
import { HelpIcon } from "@/components/help-icon";

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
      return "No file found at the usual location. If Plex lives somewhere custom on this machine, enter the full path in Settings.";
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
      return "Can't reach Plex at this address. Is Plex Media Server running? If it uses a different host or port, enter the URL in Settings.";
    case "missing_token":
      return "Plex is running but requires a token and MusicSeed couldn't find one on this machine. To get one: sign in at app.plex.tv/desktop, open your browser's developer tools (Network tab), load any library, find a request with an X-Plex-Token header, and copy its value — then paste it in Settings.";
    case "unauthorized":
      return "Plex rejected the configured token. Paste a valid Plex token in Settings.";
    case "library_not_found":
      return detail || "Enter the exact library name in Settings.";
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
          <div className="flex flex-wrap items-baseline gap-x-1.5">
            <StatusBadge ok={musicseed_db.reason === "ok" || musicseed_db.reason === "parent_missing"} />{" "}
            <strong>MusicSeed database</strong>{" "}
            <code>{musicseed_db.path}</code>{" "}
            <span className="text-[var(--muted)] text-sm">({musicseed_db.source})</span>
            {musicseed_db.reason !== "ok" && musicseed_db.reason !== "parent_missing" && (
              <HelpIcon>
                {musicseed_db.detail} Fix the permissions or choose a different location
                in Settings.
              </HelpIcon>
            )}
          </div>
          {!musicseed_db.exists && (musicseed_db.creatable || musicseed_db.reason === "parent_missing") && (
            <p className="mt-1 mb-0 text-sm text-[var(--muted)]">
              Will be created when you confirm setup.
            </p>
          )}
        </li>

        {/* Plex library DB */}
        <li>
          <div className="flex flex-wrap items-baseline gap-x-1.5">
            <StatusBadge ok={plex_library_db.ok} />{" "}
            <strong>Plex library database</strong>
            {plex_library_db.selected ? (
              <>
                {" "}
                <code>{plex_library_db.selected.path}</code>{" "}
                <span className="text-[var(--muted)] text-sm">({plex_library_db.selected.source})</span>
              </>
            ) : (
              <HelpIcon>
                {dbGuidance(plex_library_db.candidates[0]?.reason, plex_library_db.candidates[0]?.detail)}
              </HelpIcon>
            )}
          </div>
        </li>

        {/* Plex blobs DB */}
        <li>
          <div className="flex flex-wrap items-baseline gap-x-1.5">
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
              <HelpIcon>
                {dbGuidance(plex_blobs_db.candidates[0]?.reason, plex_blobs_db.candidates[0]?.detail)}{" "}
                It normally sits next to the library database with a{" "}
                <code>.blobs.db</code> suffix.
              </HelpIcon>
            )}
          </div>
        </li>

        {/* Plex server */}
        <li>
          <div className="flex flex-wrap items-baseline gap-x-1.5">
            <StatusBadge ok={plex_server.ok} />{" "}
            <strong>Plex server</strong>{" "}
            <code>{plex_server.url}</code>{" "}
            <span className="text-[var(--muted)] text-sm">({plex_server.source})</span>
            {plex_server.ok ? (
              <span className="text-[var(--muted)] text-sm">
                Plex {plex_server.server_version} · &ldquo;{plex_server.library}&rdquo;
              </span>
            ) : (
              <HelpIcon>{plexGuidance(plex_server.reason, plex_server.detail)}</HelpIcon>
            )}
          </div>
        </li>
      </ul>
    </section>
  );
}
