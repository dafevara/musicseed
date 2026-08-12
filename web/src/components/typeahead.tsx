"use client";

import { useState, useRef, useEffect } from "react";
import { api } from "@/lib/api";
import type { TypeaheadTrack } from "@/lib/types";

export function Typeahead({
  seedIds,
  onSelect,
}: {
  seedIds: number[];
  onSelect: (track: TypeaheadTrack) => void;
}) {
  const [query, setQuery] = useState("");
  const [results, setResults] = useState<TypeaheadTrack[]>([]);
  const [open, setOpen] = useState(false);
  const containerRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (query.length < 2) {
      setResults([]);
      setOpen(false);
      return;
    }

    const timer = setTimeout(async () => {
      try {
        const tracks = await api.get<TypeaheadTrack[]>(
          `/recommend/typeahead?q=${encodeURIComponent(query)}&exclude=${seedIds.join(",")}`,
        );
        setResults(tracks);
        setOpen(tracks.length > 0);
      } catch {
        setOpen(false);
      }
    }, 200);

    return () => clearTimeout(timer);
  }, [query, seedIds]);

  // Close on outside click
  useEffect(() => {
    function handleClick(e: MouseEvent) {
      if (containerRef.current && !containerRef.current.contains(e.target as Node)) {
        setOpen(false);
      }
    }
    document.addEventListener("mousedown", handleClick);
    return () => document.removeEventListener("mousedown", handleClick);
  }, []);

  return (
    <div ref={containerRef} className="relative mb-3">
      <input
        type="search"
        value={query}
        onChange={(e) => setQuery(e.target.value)}
        onFocus={() => results.length > 0 && setOpen(true)}
        placeholder="Search by artist or title…"
        autoComplete="off"
        className="w-full"
      />
      {open && (
        <div className="absolute top-full left-0 right-0 z-10 bg-[var(--panel)] border border-[var(--border)] rounded-md shadow-lg max-h-80 overflow-y-auto">
          <ul className="list-none m-0 p-0">
            {results.map((t) => (
              <li key={t.id}>
                <button
                  className="block w-full text-left px-3 py-2 text-[0.95rem] bg-transparent border-none cursor-pointer text-[var(--fg)] hover:bg-[var(--bg)] leading-relaxed"
                  onClick={() => {
                    onSelect(t);
                    setQuery("");
                    setOpen(false);
                  }}
                >
                  <strong>{t.artist || "Unknown Artist"}</strong>
                  <span className="text-[var(--muted)]"> — {t.title}</span>
                  {t.album && (
                    <span className="text-[var(--muted)] text-sm">
                      ({t.album}{t.year ? `, ${t.year}` : ""})
                    </span>
                  )}
                </button>
              </li>
            ))}
          </ul>
        </div>
      )}
    </div>
  );
}
