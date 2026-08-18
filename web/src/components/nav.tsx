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
      className="app-nav [grid-area:nav]"
      aria-label="Sections"
    >
      <ul className="app-nav-list">
        {SECTIONS.map((s) => {
          if (s.href) {
            return (
              <li key={s.key}>
                <Link
                  href={s.href}
                  className={`app-nav-link ${s.key === active ? "app-nav-link-active" : ""}`}
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
                className="app-nav-link app-nav-link-disabled"
                aria-disabled="true"
              >
                <span>{s.label}</span>
                <span className="app-nav-soon">soon</span>
              </span>
            </li>
          );
        })}
      </ul>
    </nav>
  );
}
