"use client";

import { useCallback, useEffect, useReducer, useRef } from "react";
import { chatReducer, initialChat, isRunning } from "@/lib/chat";
import { API_URL } from "@/lib/config";
import { streamBriefing } from "@/lib/stream";

export interface UseChatOptions {
  apiUrl?: string;
  fetchImpl?: typeof fetch;
}

export function useChat({ apiUrl = API_URL, fetchImpl }: UseChatOptions = {}) {
  const [state, dispatch] = useReducer(chatReducer, initialChat);
  const controller = useRef<AbortController | null>(null);
  const nextId = useRef(1);
  const running = isRunning(state);
  const runningRef = useRef(false);
  runningRef.current = running;

  const run = useCallback(
    (id: number, message: string, failSource: "news" | undefined) => {
      const ctrl = new AbortController();
      controller.current = ctrl;
      void streamBriefing({
        apiUrl,
        message,
        failSource,
        signal: ctrl.signal,
        fetchImpl,
        dispatch: (action) => dispatch({ type: "turn_action", id, action }),
      });
    },
    [apiUrl, fetchImpl],
  );

  const send = useCallback(
    (message: string, failSource?: "news") => {
      const text = message.trim();
      if (!text || runningRef.current) return;
      const id = nextId.current++;
      dispatch({ type: "turn_start", id, message: text, failSource, at: Date.now() });
      run(id, text, failSource);
    },
    [run],
  );
  const retry = useCallback(
    (id: number) => {
      const turn = state.turns.find((t) => t.id === id);
      if (!turn || runningRef.current) return;
      dispatch({ type: "turn_restart", id, at: Date.now() });
      run(id, turn.run.message, turn.run.failSource);
    },
    [run, state.turns],
  );

  const stop = useCallback(() => controller.current?.abort(), []);
  useEffect(() => () => controller.current?.abort(), []);

  return { turns: state.turns, running, send, retry, stop };
}
