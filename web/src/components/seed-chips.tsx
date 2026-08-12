import type { TypeaheadTrack } from "@/lib/types";

export function SeedChips({
  seeds,
  onRemove,
}: {
  seeds: TypeaheadTrack[];
  onRemove: (id: number) => void;
}) {
  if (!seeds.length) return null;

  return (
    <ul className="list-none m-0 p-0 flex flex-wrap gap-2">
      {seeds.map((s) => (
        <li
          key={s.id}
          className="inline-flex items-center gap-1.5 pl-2.5 pr-1 py-1 rounded-full text-sm bg-[var(--border)] text-[var(--fg)] max-w-xs"
        >
          <span className="truncate">
            <strong>{s.artist || "Unknown"}</strong> — {s.title}
          </span>
          <button
            onClick={() => onRemove(s.id)}
            className="inline-flex items-center justify-center w-5 h-5 border-none rounded-full text-sm cursor-pointer bg-transparent text-[var(--muted)] hover:bg-[var(--status-problem)] hover:text-white flex-shrink-0"
            title={`Remove ${s.title}`}
            aria-label={`Remove ${s.title}`}
          >
            ×
          </button>
        </li>
      ))}
    </ul>
  );
}
