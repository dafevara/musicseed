"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { api } from "@/lib/api";
import type { PlexLinkResult, PlexLinkStart } from "@/lib/types";

// Shared across this origin's tabs, so returning from app.plex.tv in either tab
// resumes the pending PIN instead of losing it.
const PIN_KEY = "musicseed.plex_pin";
const POLL_MS = 2000;

/**
 * "Sign in with Plex" — the plex.tv PIN flow, no token to copy.
 *
 * MusicSeed creates a PIN, this component sends the browser to Plex's own
 * sign-in page, and polls MusicSeed until the approved token has been written
 * to the local config file. The token never reaches the browser.
 */
export function PlexSignIn({
  onLinked,
  forwardPath = "/setup",
}: {
  onLinked?: (result: PlexLinkResult) => void | Promise<void>;
  /** Where Plex returns the browser to after sign-in. */
  forwardPath?: string;
}) {
  const [start, setStart] = useState<PlexLinkStart | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [linkedAs, setLinkedAs] = useState<string | null>(null);
  // Keep the callback out of the polling effect's dependencies.
  const onLinkedRef = useRef(onLinked);
  onLinkedRef.current = onLinked;

  const cancel = useCallback(() => {
    window.localStorage.removeItem(PIN_KEY);
    setStart(null);
  }, []);

  // Resume a PIN started before the browser left for app.plex.tv.
  useEffect(() => {
    const stored = window.localStorage.getItem(PIN_KEY);
    if (!stored) return;
    try {
      setStart(JSON.parse(stored) as PlexLinkStart);
    } catch {
      window.localStorage.removeItem(PIN_KEY);
    }
  }, []);

  async function begin() {
    setBusy(true);
    setError(null);
    setLinkedAs(null);
    try {
      const info = await api.post<PlexLinkStart>("/auth/plex/pin", {
        handoff: "forward",
        forward_url: `${window.location.origin}${forwardPath}`,
      });
      window.localStorage.setItem(PIN_KEY, JSON.stringify(info));
      setStart(info);
      window.open(info.auth_url, "_blank", "noopener,noreferrer");
    } catch (e) {
      setError(String(e).replace("Error: ", ""));
    } finally {
      setBusy(false);
    }
  }

  useEffect(() => {
    if (!start) return;
    let cancelled = false;
    let timer = 0;
    const deadline = Date.now() + start.expires_in * 1000;

    async function tick() {
      let result: PlexLinkResult;
      try {
        result = await api.get<PlexLinkResult>(`/auth/plex/pin/${start!.pin_id}`);
      } catch (e) {
        if (cancelled) return;
        window.localStorage.removeItem(PIN_KEY);
        setStart(null);
        setError(String(e).replace("Error: ", ""));
        return;
      }
      if (cancelled) return;
      if (result.linked) {
        window.localStorage.removeItem(PIN_KEY);
        setStart(null);
        setLinkedAs(
          result.account?.title || result.account?.username || "your Plex account",
        );
        await onLinkedRef.current?.(result);
        return;
      }
      if (result.expired) {
        window.localStorage.removeItem(PIN_KEY);
        setStart(null);
        setError("That sign-in code expired. Choose Sign in with Plex to try again.");
        return;
      }
      if (Date.now() >= deadline) {
        window.localStorage.removeItem(PIN_KEY);
        setStart(null);
        setError("Sign-in timed out. Choose Sign in with Plex to try again.");
        return;
      }
      timer = window.setTimeout(tick, POLL_MS);
    }

    timer = window.setTimeout(tick, POLL_MS);
    return () => {
      cancelled = true;
      window.clearTimeout(timer);
    };
  }, [start]);

  async function unlink() {
    setBusy(true);
    setError(null);
    try {
      await api.post("/auth/plex/unlink");
      setLinkedAs(null);
      await onLinkedRef.current?.({
        linked: false,
        pending: false,
        expired: false,
        token_saved: false,
        url_saved: null,
        account: null,
        servers: [],
      });
    } catch (e) {
      setError(String(e).replace("Error: ", ""));
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="grid gap-3">
      {error && (
        <div className="flash flash-error" role="alert">
          <p className="m-0 text-sm">{error}</p>
        </div>
      )}

      {!start && !linkedAs && (
        <div className="grid gap-2">
          <button type="button" className="btn btn-primary justify-self-start" onClick={begin} disabled={busy}>
            {busy ? "Starting…" : "Sign in with Plex"}
          </button>
          <p className="m-0 text-sm text-[var(--muted)]">
            Opens Plex in a new tab. MusicSeed never sees your Plex password, and
            the token it receives is stored only on this computer.
          </p>
        </div>
      )}

      {start && (
        <div className="grid gap-2">
          <p className="m-0 text-sm">
            Waiting for approval. If a Plex tab opened, finish signing in there.
          </p>
          <p className="m-0 text-sm text-[var(--muted)]">
            Otherwise open{" "}
            <a href={start.link_url} target="_blank" rel="noreferrer" className="text-[var(--brand)] underline">
              {start.link_url}
            </a>{" "}
            and enter this code:
          </p>
          <p className="m-0 text-2xl font-semibold tracking-widest">{start.code}</p>
          <div className="flex flex-wrap items-center gap-3">
            <a href={start.auth_url} target="_blank" rel="noreferrer" className="text-sm text-[var(--brand)] underline">
              Open Plex sign-in again
            </a>
            <button type="button" className="btn btn-secondary text-sm" onClick={cancel}>
              Cancel
            </button>
          </div>
        </div>
      )}

      {linkedAs && (
        <div className="flash flash-ok">
          <p className="m-0 text-sm">
            Signed in with Plex as <strong>{linkedAs}</strong>. The token was saved to
            this computer, so the CLI and MCP server can use it too.
          </p>
          <div className="flex flex-wrap items-center gap-3 mt-2">
            <button type="button" className="btn btn-secondary text-sm" onClick={begin} disabled={busy}>
              Sign in as someone else
            </button>
            <button type="button" className="btn btn-secondary text-sm" onClick={unlink} disabled={busy}>
              Sign out
            </button>
          </div>
        </div>
      )}
    </div>
  );
}
