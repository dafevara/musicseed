"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { api } from "@/lib/api";
import type { DiscoveryResponse } from "@/lib/types";

export type SetupGate = "loading" | "ready" | "needs-setup";

/**
 * Redirect to /setup when the app is not past first-run (missing or empty
 * library). Pages call this on mount; it fails open (treats as ready) if the
 * discovery request itself fails, so an unreachable API does not hide the app.
 */
export function useSetupGate(): SetupGate {
  const router = useRouter();
  const [state, setState] = useState<SetupGate>("loading");

  useEffect(() => {
    api.get<DiscoveryResponse>("/discovery")
      .then((d) => {
        const first = d.result.first_run;
        if (first.db_missing || first.library_empty || first.import_incomplete) {
          setState("needs-setup");
          router.replace("/setup");
        } else {
          setState("ready");
        }
      })
      .catch(() => setState("ready"));
  }, [router]);

  return state;
}
