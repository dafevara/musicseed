"use client";

import { useEffect, useState } from "react";

const HIDE_KEY = "musicseed.setupIntroHidden";

/**
 * First-run explainer for the setup wizard. Shown until the user dismisses it;
 * the dismissal persists in localStorage so it never comes back.
 */
export function SetupIntro() {
  // Start hidden so the static pre-render matches; reveal after reading storage.
  const [hidden, setHidden] = useState(true);

  useEffect(() => {
    try {
      setHidden(window.localStorage.getItem(HIDE_KEY) === "1");
    } catch {
      setHidden(false); // storage unavailable — show it; dismissal just won't persist
    }
  }, []);

  function dismiss() {
    setHidden(true);
    try {
      window.localStorage.setItem(HIDE_KEY, "1");
    } catch {
      // ignore — private mode etc.
    }
  }

  if (hidden) return null;

  return (
    <section className="panel setup-intro">
      <h2 className="text-lg font-semibold">What this setup does</h2>
      <p>
        MusicSeed recommends tracks from your own Plex library and saves them as Plex
        playlists. Everything runs on this machine — it never streams or hosts music.
        This one-time wizard prepares the three things recommendations rely on:
      </p>
      <ol>
        <li>
          <strong>Plex connection.</strong> Your server URL and token let MusicSeed read
          your library — and, only when you explicitly ask, create playlists in Plex.
          The token is stored locally and never displayed.
        </li>
        <li>
          <strong>A local database.</strong> MusicSeed keeps its own copy of your library
          metadata in a single SQLite file on this machine. Your Plex databases are only
          ever read, never modified.
        </li>
        <li>
          <strong>Import &amp; enrichment.</strong> Background jobs that copy your library
          into the local database and add popularity signals (ListenBrainz needs no
          account; Spotify is optional). They can take a while for large libraries and
          are safe to interrupt and resume.
        </li>
      </ol>
      <p>
        With these in place, recommendations combine sonic similarity from Plex&apos;s own
        analysis with popularity, style, genre, era, and novelty signals.
      </p>
      <button type="button" className="btn btn-secondary" onClick={dismiss}>
        Got it — don&apos;t show this again
      </button>
    </section>
  );
}
