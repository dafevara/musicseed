"use client";

import { useCallback, useEffect, useState } from "react";
import { api } from "@/lib/api";
import type { DiscoveredPlexServer, PlexServersResponse } from "@/lib/types";

export function PlexServerPicker({
  onSelect,
  defaultUrl,
}: {
  onSelect: (url: string) => void;
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

  return (
    <div className="grid gap-3">
      <div className="flex items-center gap-2">
        <button type="button" className="btn btn-secondary text-sm" onClick={scan} disabled={scanning}>
          {scanning ? "Scanning…" : "Scan again"}
        </button>
        <span className="text-sm text-[var(--muted)]">
          Looking for Plex on your local network.
        </span>
      </div>

      {servers.length > 0 && (
        <ul className="list-none m-0 p-0 grid gap-1.5">
          {servers.map((s) => (
            <li key={`${s.host}:${s.port}`}>
              <button
                type="button"
                className="w-full text-left px-3 py-2 rounded-md border border-[var(--border)] bg-[var(--bg)] hover:border-[var(--brand)] cursor-pointer"
                onClick={() => onSelect(`${s.scheme}://${s.host}:${s.port}`)}
              >
                <span className="font-medium">{s.name}</span>
                <span className="text-xs text-[var(--muted)] block">
                  {s.scheme}://{s.host}:{s.port}
                  {s.version ? ` · Plex ${s.version}` : ""}
                </span>
              </button>
            </li>
          ))}
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
