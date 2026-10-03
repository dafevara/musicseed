"use client";

import { useCallback, useEffect, useState } from "react";
import { api } from "@/lib/api";
import type { DiscoveredPlexServer, PlexServersResponse } from "@/lib/types";

/**
 * Plex server picker.
 *
 * A Plex server advertises several addresses (its own LAN interfaces, a VPN
 * address, a `*.plex.direct` hostname), and only some of them work from the
 * machine running MusicSeed. The API probes each one, so entries are labelled
 * and ordered by whether they actually answer — picking the wrong address used
 * to leave the wizard reporting "Plex isn't responding".
 */
export function PlexServerPicker({
  onSelect,
  defaultUrl,
}: {
  onSelect: (url: string) => void;
  /** The URL currently in effect, marked in the list. */
  defaultUrl?: string;
}) {
  const [servers, setServers] = useState<DiscoveredPlexServer[]>([]);
  const [scanning, setScanning] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [manualUrl, setManualUrl] = useState("");

  const scan = useCallback(async () => {
    setScanning(true);
    setError(null);
    try {
      const data = await api.get<PlexServersResponse>("/discovery/plex-servers");
      setServers(data.servers);
      if (data.servers.length === 0) {
        setError("No Plex server found on the local network. Enter a URL below.");
      }
    } catch {
      setError("Could not scan the local network. Enter a URL below.");
    } finally {
      setScanning(false);
    }
  }, []);

  useEffect(() => {
    scan();
  }, [scan]);

  function useManual(e: React.FormEvent) {
    e.preventDefault();
    const url = manualUrl.trim().replace(/\/+$/, "");
    if (url) onSelect(url);
  }

  const unreachable = servers.filter((s) => s.reachable === false).length;

  return (
    <div className="grid gap-3">
      <div className="flex items-center gap-2">
        <button type="button" className="btn btn-secondary text-sm" onClick={scan} disabled={scanning}>
          {scanning ? "Scanning…" : "Scan again"}
        </button>
        <span className="text-sm text-[var(--muted)]">
          {scanning
            ? "Looking for Plex on your local network and checking each address."
            : "Addresses are checked from this computer."}
        </span>
      </div>

      {unreachable > 0 && (
        <p className="text-sm text-[var(--muted)] m-0">
          {unreachable === servers.length
            ? "None of the discovered addresses answered from this computer."
            : "Some addresses are not reachable from this computer — pick one marked reachable."}
        </p>
      )}

      {servers.length > 0 && (
        <ul className="list-none m-0 p-0 grid gap-1.5">
          {servers.map((s) => {
            const url = `${s.scheme}://${s.host}:${s.port}`;
            const isCurrent = defaultUrl === url;
            const dead = s.reachable === false;
            return (
              <li key={`${s.host}:${s.port}`}>
                <button
                  type="button"
                  className={`w-full text-left px-3 py-2 rounded-md border bg-[var(--bg)] hover:border-[var(--brand)] cursor-pointer ${
                    isCurrent ? "border-[var(--brand)]" : "border-[var(--border)]"
                  }`}
                  onClick={() => onSelect(url)}
                >
                  <span className="font-medium">{s.name}</span>
                  {isCurrent && (
                    <span className="text-xs text-[var(--brand)] font-semibold"> · in use</span>
                  )}
                  {dead && (
                    <span className="text-xs text-[var(--muted)]"> · not reachable</span>
                  )}
                  <span className="text-xs text-[var(--muted)] block">
                    {url}
                    {s.version ? ` · Plex ${s.version}` : ""}
                    {s.reachable === true && !isCurrent ? " · reachable" : ""}
                  </span>
                </button>
              </li>
            );
          })}
        </ul>
      )}

      {error && <p className="text-sm text-[var(--muted)] m-0">{error}</p>}

      <form onSubmit={useManual} className="flex gap-2">
        <input
          type="text"
          className="flex-1"
          placeholder={defaultUrl || "http://192.168.1.10:32400"}
          value={manualUrl}
          onChange={(e) => setManualUrl(e.target.value)}
          aria-label="Plex server URL"
        />
        <button type="submit" className="btn btn-secondary" disabled={!manualUrl.trim()}>
          Use URL
        </button>
      </form>
    </div>
  );
}
