"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";

type Section = { key: string; label: string; href?: string };
const SECTIONS: Section[] = [
  { key: "library", label: "Library", href: "/" },
  { key: "recommend", label: "Recommend", href: "/recommend" },
  { key: "playlists", label: "Playlists", href: "/playlists" },
  { key: "settings", label: "Settings", href: "/settings" },
];

const PREFIXES: [string, string][] = [
  ["/recommend", "recommend"],
  ["/playlists", "playlists"],
  ["/settings", "settings"],
];

function activeSection(path: string): string | null {
  if (path === "/") return "library";
  for (const [prefix, key] of PREFIXES) {
    if (path === prefix || path.startsWith(prefix + "/")) return key;
  }
  return null;
}

export function Nav() {
  const pathname = usePathname();
  const active = activeSection(pathname);

  return (
    <nav
      className="[grid-area:nav] py-4 px-3 border-r border-[var(--border)] bg-[var(--panel)] max-lg:border-r-0 max-lg:border-b max-lg:py-2 max-lg:px-3 max-lg:overflow-x-auto"
      aria-label="Sections"
    >
      <ul className="list-none m-0 p-0 grid gap-0.5 max-lg:grid-flow-col max-lg:auto-cols-max max-lg:gap-1">
        {SECTIONS.map((s) => {
          if (s.href) {
            return (
              <li key={s.key}>
                <Link
                  href={s.href}
                  className={`flex items-baseline justify-between gap-2 px-3 py-2 rounded-md text-[0.95rem] whitespace-nowrap no-underline
                    ${s.key === active
                      ? "bg-[var(--brand)] text-white font-semibold"
                      : "text-[var(--fg)] hover:bg-[var(--bg)]"
                    }`}
                  {...(s.key === active ? { "aria-current": "page" as const } : {})}
                >
                  {s.label}
                </Link>
              </li>
            );
          }
          return (
            <li key={s.key}>
              <span
                className="flex items-baseline justify-between gap-2 px-3 py-2 rounded-md text-[0.95rem] whitespace-nowrap text-[var(--muted)] cursor-default"
                aria-disabled="true"
              >
                <span>{s.label}</span>
                <span className="text-[0.72rem] text-[var(--muted)]">soon</span>
              </span>
            </li>
          );
        })}
      </ul>
    </nav>
  );
}
