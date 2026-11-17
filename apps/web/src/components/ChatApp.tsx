"use client";

import type { Citation } from "@mpa/contract";
import { useCallback, useEffect, useRef, useState } from "react";
import { useChat } from "@/hooks/useChat";
import { API_URL } from "@/lib/config";
import { citeKey } from "@/lib/segments";
import { STARTERS } from "@/lib/starters";
import { AssistantCard } from "./AssistantCard";
import { Composer } from "./Composer";
import { SourcePanel } from "./SourcePanel";

export function ChatApp() {
  const { turns, running, send, retry, stop } = useChat();
  const [outage, setOutage] = useState(false);
  const [cite, setCite] = useState<Citation | null>(null);
  const endRef = useRef<HTMLDivElement>(null);

  const sendMessage = useCallback(
    (message: string) => send(message, outage ? "news" : undefined),
    [send, outage],
  );

  useEffect(() => {
    endRef.current?.scrollIntoView?.({ block: "end", behavior: "smooth" });
  }, [turns.length]);

  return (
    <div className={`flex min-h-screen flex-col ${cite ? "lg:pr-[26rem]" : ""}`}>
      <header className="sticky top-0 z-20 border-b border-slate-200 bg-white/90 backdrop-blur">
        <div className="mx-auto flex max-w-3xl items-center gap-2 px-4 py-3">
          <span
            aria-hidden="true"
            className="flex h-7 w-7 items-center justify-center rounded-lg bg-accent text-xs font-semibold text-white"
          >
            MP
          </span>
          <h1 className="text-base font-semibold text-slate-900">Meeting Prep Agent</h1>
        </div>
      </header>

      <main className="mx-auto w-full max-w-3xl flex-1 space-y-6 px-4 py-6">
        {turns.length === 0 ? (
          <section className="mx-auto flex max-w-xl flex-col items-center gap-5 pt-16 text-center">
            <h2 className="text-2xl font-semibold text-slate-900">Who are you meeting next?</h2>
            <p className="text-sm text-slate-600">
              Ask for a briefing and four agents will read email, chat, documents, news and contacts in
              parallel. Every sentence in the result is cited and checked.
            </p>
            <div className="flex w-full flex-col gap-2">
              {STARTERS.map((s) => (
                <button
                  key={s.testId}
                  type="button"
                  data-testid={s.testId}
                  disabled={running}
                  onClick={() => sendMessage(s.text)}
                  className="rounded-xl border border-slate-200 bg-white px-4 py-3 text-left text-sm text-slate-800 shadow-sm hover:border-accent hover:bg-slate-50 disabled:opacity-60"
                >
                  {s.text}
                </button>
              ))}
            </div>
          </section>
        ) : (
          turns.map((turn) => (
            <div key={turn.id} className="space-y-4" data-testid="turn">
              <div className="flex justify-end">
                <p
                  data-testid="user-message"
                  className="max-w-[80%] whitespace-pre-wrap break-words rounded-2xl rounded-br-md bg-accent px-4 py-2 text-sm text-white"
                >
                  {turn.run.message}
                </p>
              </div>
              <AssistantCard
                run={turn.run}
                apiUrl={API_URL}
                activeCite={cite ? citeKey(cite) : null}
                onOpenSource={setCite}
                onRetry={() => retry(turn.id)}
              />
            </div>
          ))
        )}
        <div ref={endRef} />
      </main>

      <div className="sticky bottom-0 z-10 border-t border-slate-200 bg-slate-50/95 px-4 py-3 backdrop-blur">
        <Composer
          running={running}
          outage={outage}
          onOutageChange={setOutage}
          onSend={sendMessage}
          onStop={stop}
        />
      </div>

      {cite && (
        <SourcePanel
          key={citeKey(cite)}
          citation={cite}
          apiUrl={API_URL}
          onClose={() => setCite(null)}
        />
      )}
    </div>
  );
}
