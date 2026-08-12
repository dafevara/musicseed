import type { Metadata } from "next";
import "./globals.css";
import { Nav } from "@/components/nav";

export const metadata: Metadata = {
  title: "MusicSeed",
  description: "Local-first Plex playlist recommendations",
};

export default function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <html lang="en">
      <body>
        <div className="min-h-screen grid grid-cols-[13rem_minmax(0,1fr)] grid-rows-[auto_minmax(0,1fr)] [grid-template-areas:'header_header'_'nav_main'] max-lg:grid-cols-[minmax(0,1fr)] max-lg:grid-rows-[auto_auto_minmax(0,1fr)] max-lg:[grid-template-areas:'header'_'nav'_'main']">
          <header
            className="[grid-area:header] flex flex-wrap items-baseline gap-x-3 gap-y-0.5 px-6 py-2.5 border-b border-[var(--border)] bg-[var(--panel)]"
          >
            <a href="/" className="text-lg font-bold text-[var(--brand)] no-underline">
              MusicSeed
            </a>
            <p className="m-0 text-[var(--muted)] text-sm">
              Local-first Plex playlist recommendations
            </p>
          </header>

          <Nav />

          <main
            className="[grid-area:main] min-w-0 max-w-6xl p-6 grid gap-5 content-start max-lg:p-4"
          >
            {children}
          </main>
        </div>
      </body>
    </html>
  );
}
