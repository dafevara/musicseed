import type { Metadata } from "next";
import "./globals.css";
import { Nav } from "@/components/nav";
import { BrandMark } from "@/components/brand-mark";

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
        <div className="app-shell min-h-screen grid grid-cols-[13rem_minmax(0,1fr)] grid-rows-[auto_minmax(0,1fr)] [grid-template-areas:'header_header'_'nav_main'] max-lg:grid-cols-[minmax(0,1fr)] max-lg:grid-rows-[auto_auto_minmax(0,1fr)] max-lg:[grid-template-areas:'header'_'nav'_'main']">
          <header className="app-header [grid-area:header]">
            <a href="/" className="app-brand-link" aria-label="MusicSeed home">
              <BrandMark />
              <span className="app-brand-name">MusicSeed</span>
            </a>
            <p className="app-tagline">
              Local-first Plex playlist recommendations
            </p>
          </header>

          <Nav />

          <main
            className="app-main [grid-area:main] min-w-0 max-w-6xl p-6 grid gap-5 content-start max-lg:p-4"
          >
            {children}
          </main>
        </div>
      </body>
    </html>
  );
}
