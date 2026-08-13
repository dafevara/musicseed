import type { DiscoveryResult } from "@/lib/types";
import { HelpIcon } from "@/components/help-icon";

function StatusBadge({ ok }: { ok: boolean }) {
  return ok ? (
    <span className="badge badge-ok">ok</span>
  ) : (
    <span className="badge badge-problem">attention</span>
  );
}

const SHORT_REASON: Record<string, string> = {
  not_found: "not found",
  not_a_file: "not a file",
  not_readable: "not readable",
  not_writable: "not writable",
  invalid_sqlite: "not a SQLite file",
  parent_missing: "folder missing",
  parent_not_writable: "folder not writable",
  unreachable: "unreachable",
  missing_token: "needs a token",
  unauthorized: "token rejected",
  library_not_found: "library not found",
  error: "error",
  skipped: "not checked",
};

function dbGuidance(reason: string | undefined, detail: string | null | undefined): string {
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
      return detail || "";
  }
}

function plexGuidance(reason: string | null, detail: string | null): string {
  switch (reason) {
    case "unreachable":
      return "Can't reach Plex at this address. Is Plex Media Server running? If it uses a different host or port, enter the URL in Settings.";
    case "missing_token":
      return "Plex requires a token and none was found on this machine. To get one: sign in at app.plex.tv/desktop, open your browser's developer tools (Network tab), load any library, find a request with an X-Plex-Token header, and copy its value — then paste it in Settings.";
    case "unauthorized":
      return "Plex rejected the configured token. Paste a valid token in Settings.";
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
  const dbOk = musicseed_db.reason === "ok" || musicseed_db.reason === "parent_missing";

  return (
    <section className="panel">
      <h2 className="mt-0 text-lg font-semibold">Checks</h2>
      <ul className="list-none m-0 p-0 grid gap-2.5">
        {/* MusicSeed DB */}
        <li className="flex flex-wrap items-baseline gap-x-1.5">
          <StatusBadge ok={dbOk} /> <strong>MusicSeed database</strong>
          {dbOk ? (
            <>
              <code>{musicseed_db.path}</code>{" "}
              <span className="text-[var(--muted)] text-sm">({musicseed_db.source})</span>
              {!musicseed_db.exists && (
                <span className="text-[var(--muted)] text-sm">(will be created)</span>
              )}
            </>
          ) : (
            <>
              <span className="text-[var(--muted)] text-sm">
                {SHORT_REASON[musicseed_db.reason] || ""}
              </span>
              <HelpIcon>
                {musicseed_db.detail} Fix the permissions or choose a different location in
                Settings.
              </HelpIcon>
            </>
          )}
        </li>

        {/* Plex library DB */}
        <li className="flex flex-wrap items-baseline gap-x-1.5">
          <StatusBadge ok={plex_library_db.ok} /> <strong>Plex library database</strong>
          {plex_library_db.selected ? (
            <>
              <code>{plex_library_db.selected.path}</code>{" "}
              <span className="text-[var(--muted)] text-sm">({plex_library_db.selected.source})</span>
            </>
          ) : (
            <>
              <span className="text-[var(--muted)] text-sm">
                {SHORT_REASON[plex_library_db.candidates[0]?.reason || ""] || "missing"}
              </span>
              <HelpIcon>
                {dbGuidance(plex_library_db.candidates[0]?.reason, plex_library_db.candidates[0]?.detail)}
              </HelpIcon>
            </>
          )}
        </li>

        {/* Plex blobs DB */}
        <li className="flex flex-wrap items-baseline gap-x-1.5">
          <StatusBadge ok={plex_blobs_db.ok} /> <strong>Plex blobs database</strong>
          {plex_blobs_db.selected ? (
            <>
              <code>{plex_blobs_db.selected.path}</code>{" "}
              <span className="text-[var(--muted)] text-sm">({plex_blobs_db.selected.source})</span>
            </>
          ) : (
            <>
              <span className="text-[var(--muted)] text-sm">
                {SHORT_REASON[plex_blobs_db.candidates[0]?.reason || ""] || "missing"}
              </span>
              <HelpIcon>
                {dbGuidance(plex_blobs_db.candidates[0]?.reason, plex_blobs_db.candidates[0]?.detail)}{" "}
                It normally sits next to the library database with a{" "}
                <code>.blobs.db</code> suffix.
              </HelpIcon>
            </>
          )}
        </li>

        {/* Plex server */}
        <li className="flex flex-wrap items-baseline gap-x-1.5">
          <StatusBadge ok={plex_server.ok} /> <strong>Plex server</strong>
          {plex_server.ok ? (
            <>
              <code>{plex_server.url}</code>{" "}
              <span className="text-[var(--muted)] text-sm">({plex_server.source})</span>
              <span className="text-[var(--muted)] text-sm">
                Plex {plex_server.server_version} &middot; &ldquo;{plex_server.library}&rdquo;
              </span>
            </>
          ) : (
            <>
              <span className="text-[var(--muted)] text-sm">
                {SHORT_REASON[plex_server.reason || ""] || ""}
              </span>
              <HelpIcon>{plexGuidance(plex_server.reason, plex_server.detail)}</HelpIcon>
            </>
          )}
        </li>
      </ul>
    </section>
  );
}
