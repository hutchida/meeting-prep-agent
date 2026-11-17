"use client";

import { useEffect, useRef, useState, type FormEvent, type KeyboardEvent } from "react";

interface Props {
  running: boolean;
  outage: boolean;
  onOutageChange: (value: boolean) => void;
  onSend: (message: string) => void;
  onStop: () => void;
}

export function Composer({ running, outage, onOutageChange, onSend, onStop }: Props) {
  const [text, setText] = useState("");
  const input = useRef<HTMLTextAreaElement>(null);
  const wasRunning = useRef(false);

  useEffect(() => {
    if (wasRunning.current && !running) input.current?.focus();
    wasRunning.current = running;
  }, [running]);

  const submit = (e?: FormEvent) => {
    e?.preventDefault();
    const message = text.trim();
    if (!message || running) return;
    onSend(message);
    setText("");
  };

  const onKeyDown = (e: KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === "Enter" && !e.shiftKey && !e.nativeEvent.isComposing) {
      e.preventDefault();
      submit();
    }
  };

  return (
    <form onSubmit={submit} className="mx-auto w-full max-w-3xl space-y-2">
      <div className="flex items-end gap-2 rounded-2xl border border-slate-300 bg-white p-2 shadow-sm focus-within:border-accent">
        <label htmlFor="chat-input" className="sr-only">
          Message
        </label>
        <textarea
          ref={input}
          id="chat-input"
          data-testid="chat-input"
          rows={1}
          maxLength={2000}
          disabled={running}
          value={text}
          onChange={(e) => setText(e.target.value)}
          onKeyDown={onKeyDown}
          placeholder="Ask for a meeting briefing, e.g. “Prep me for my meeting with Halden Pay on Wednesday”"
          className="max-h-40 min-h-9 flex-1 resize-none bg-transparent px-2 py-1.5 text-sm text-slate-900 placeholder:text-slate-400 focus-visible:outline-none disabled:cursor-not-allowed disabled:text-slate-500"
        />
        {running && (
          <button
            type="button"
            data-testid="chat-stop"
            onClick={onStop}
            className="h-9 rounded-xl border border-slate-300 bg-white px-3 text-sm font-medium text-slate-700 hover:bg-slate-100"
          >
            Stop
          </button>
        )}
        <button
          type="submit"
          data-testid="chat-send"
          disabled={running || text.trim() === ""}
          className="h-9 rounded-xl bg-accent px-4 text-sm font-medium text-white hover:bg-accent-strong disabled:cursor-not-allowed disabled:bg-slate-300"
        >
          Send
        </button>
      </div>
      <div className="flex flex-wrap items-center justify-between gap-x-4 gap-y-1 px-1 text-xs text-slate-500">
        <label className="flex cursor-pointer items-center gap-2">
          <input
            type="checkbox"
            role="switch"
            data-testid="toggle-news-outage"
            checked={outage}
            disabled={running}
            onChange={(e) => onOutageChange(e.target.checked)}
            className="h-4 w-4 accent-[var(--color-accent)]"
          />
          <span>
            <span className="font-medium text-slate-700">Simulate news outage</span> · the news
            source fails, so you can watch retries and a partial briefing
          </span>
        </label>
        <span>Enter to send · Shift+Enter for a new line</span>
      </div>
    </form>
  );
}
