"use client";

import { SourceItem, type Citation } from "@mpa/contract";
import { useCallback, useEffect, useState } from "react";

export type SourceState =
  | { status: "loading" }
  | { status: "ok"; item: SourceItem }
  | { status: "error"; kind: "not_found" | "failed" };

export function useSource(
  citation: Citation | null,
  apiUrl: string,
  fetchImpl?: typeof fetch,
): { state: SourceState; reload: () => void } {
  const [state, setState] = useState<SourceState>({ status: "loading" });
  const [attempt, setAttempt] = useState(0);
  const type = citation?.type;
  const id = citation?.id;

  useEffect(() => {
    if (!type || !id) return;
    const ctrl = new AbortController();
    setState({ status: "loading" });
    (async () => {
      try {
        const res = await (fetchImpl ?? fetch)(`${apiUrl}/sources/${type}/${encodeURIComponent(id)}`, {
          signal: ctrl.signal,
        });
        if (res.status === 404) return setState({ status: "error", kind: "not_found" });
        if (!res.ok) return setState({ status: "error", kind: "failed" });
        const parsed = SourceItem.safeParse(await res.json());
        setState(
          parsed.success
            ? { status: "ok", item: parsed.data }
            : { status: "error", kind: "failed" },
        );
      } catch {
        if (!ctrl.signal.aborted) setState({ status: "error", kind: "failed" });
      }
    })();
    return () => ctrl.abort();
  }, [type, id, apiUrl, fetchImpl, attempt]);

  const reload = useCallback(() => setAttempt((n) => n + 1), []);
  return { state, reload };
}
