"use client";

import { useEffect, useState } from "react";

/** Live elapsed milliseconds while `running`; holds its last value afterwards. */
export function useElapsed(startedAt: number, running: boolean): number {
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {
    if (!running) return;
    setNow(Date.now());
    const id = setInterval(() => setNow(Date.now()), 200);
    return () => clearInterval(id);
  }, [running]);
  return Math.max(0, now - startedAt);
}
