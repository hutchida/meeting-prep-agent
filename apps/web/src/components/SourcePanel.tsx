"use client";

import type { Citation, SourceItem } from "@mpa/contract";
import { useEffect, useRef, type ReactNode } from "react";
import { useSource } from "@/hooks/useSource";

const TYPE_LABEL: Record<Citation["type"], string> = {
  email: "Email",
  chat: "Chat message",
  doc: "Document",
  news: "News article",
  contact: "Contact",
  cal: "Calendar event",
};

function Field({ label, children }: { label: string; children: ReactNode }) {
  return (
    <div>
      <dt className="text-[11px] font-medium uppercase tracking-wide text-slate-500">{label}</dt>
      <dd className="break-words text-sm text-slate-800">{children}</dd>
    </div>
  );
}

const Body = ({ text }: { text: string }) => (
  <div
    data-testid="source-body"
    className="whitespace-pre-wrap break-words rounded-lg bg-slate-50 p-3 text-sm leading-6 text-slate-800"
  >
    {text}
  </div>
);

function ItemView({ item }: { item: SourceItem }) {
  switch (item.type) {
    case "email":
      return (
        <>
          <dl className="space-y-2">
            <Field label="From">{item.sender}</Field>
            <Field label="To">{item.to.join(", ") || "—"}</Field>
            {item.cc.length > 0 && <Field label="Cc">{item.cc.join(", ")}</Field>}
            <Field label="Date">{item.date}</Field>
            <Field label="Subject">{item.subject}</Field>
          </dl>
          <Body text={item.body} />
        </>
      );
    case "chat":
      return (
        <>
          <dl className="space-y-2">
            <Field label="Channel">{item.channel}</Field>
            <Field label="Author">{item.author}</Field>
            <Field label="Time">{item.ts}</Field>
          </dl>
          <Body text={item.text} />
        </>
      );
    case "doc":
      return (
        <>
          <dl className="space-y-2">
            <Field label="Title">{item.title}</Field>
            <Field label="Kind">{item.kind}</Field>
            <Field label="Author">{item.author}</Field>
            <Field label="Date">{item.date}</Field>
          </dl>
          <Body text={item.body} />
        </>
      );
    case "news":
      return (
        <>
          <dl className="space-y-2">
            <Field label="Headline">{item.title}</Field>
            <Field label="Source">{item.source}</Field>
            <Field label="Published">{item.published}</Field>
            <Field label="URL">
              <span className="font-mono text-xs">{item.url}</span>
            </Field>
          </dl>
          <Body text={item.body} />
        </>
      );
    case "contact":
      return (
        <dl className="space-y-2">
          <Field label="Name">{item.name}</Field>
          <Field label="Email">{item.email}</Field>
          <Field label="Organization">{item.organization}</Field>
          <Field label="Role">{item.role || "—"}</Field>
          {item.notes && <Field label="Notes">{item.notes}</Field>}
        </dl>
      );
    case "cal":
      return (
        <>
          <dl className="space-y-2">
            <Field label="Title">{item.title}</Field>
            <Field label="Start">{item.start}</Field>
            <Field label="End">{item.end}</Field>
            <Field label="Location">{item.location || "—"}</Field>
            <Field label="Attendees">{item.attendees.join(", ") || "—"}</Field>
          </dl>
          {item.description && <Body text={item.description} />}
        </>
      );
  }
}

interface Props {
  citation: Citation;
  apiUrl: string;
  fetchImpl?: typeof fetch;
  onClose: () => void;
}

export function SourcePanel({ citation, apiUrl, fetchImpl, onClose }: Props) {
  const { state, reload } = useSource(citation, apiUrl, fetchImpl);
  const closeRef = useRef<HTMLButtonElement>(null);
  const onCloseRef = useRef(onClose);
  onCloseRef.current = onClose;

  useEffect(() => {
    const opener = document.activeElement instanceof HTMLElement ? document.activeElement : null;
    closeRef.current?.focus();
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") onCloseRef.current();
    };
    window.addEventListener("keydown", onKey);
    return () => {
      window.removeEventListener("keydown", onKey);
      if (opener?.isConnected) opener.focus();
    };
  }, []);

  return (
    <aside
      data-testid="source-panel"
      data-cite={`${citation.type}:${citation.id}`}
      aria-label={`Source ${citation.type} ${citation.id}`}
      className="fixed inset-y-0 right-0 z-30 flex w-full max-w-[26rem] flex-col border-l border-slate-200 bg-white shadow-xl"
    >
      <header className="flex items-center justify-between gap-2 border-b border-slate-200 px-4 py-3">
        <div className="min-w-0">
          <h2 className="truncate text-sm font-semibold text-slate-900">{TYPE_LABEL[citation.type]}</h2>
          <p className="font-mono text-xs text-slate-500">
            {citation.type}:{citation.id}
          </p>
        </div>
        <button
          ref={closeRef}
          type="button"
          data-testid="source-panel-close"
          aria-label="Close source panel"
          onClick={onClose}
          className="rounded-md px-2 py-1 text-lg leading-none text-slate-600 hover:bg-slate-100"
        >
          <span aria-hidden="true">×</span>
        </button>
      </header>
      <div className="flex-1 space-y-3 overflow-y-auto p-4" aria-live="polite" aria-busy={state.status === "loading"}>
        {state.status === "loading" && (
          <div data-testid="source-loading" className="skeleton space-y-2">
            <div className="h-3 w-1/2 rounded bg-slate-200" />
            <div className="h-3 w-3/4 rounded bg-slate-200" />
            <div className="h-20 rounded bg-slate-200" />
          </div>
        )}
        {state.status === "error" && (
          <div
            role="alert"
            data-testid="source-error"
            className="space-y-2 rounded-lg border border-red-200 bg-red-50 p-3 text-sm text-red-800"
          >
            <p>
              {state.kind === "not_found"
                ? "This source could not be found."
                : "The source could not be loaded."}
            </p>
            {state.kind === "failed" && (
              <button
                type="button"
                onClick={reload}
                className="rounded-md border border-red-300 bg-white px-2.5 py-1 text-xs font-medium hover:bg-red-100"
              >
                Try again
              </button>
            )}
          </div>
        )}
        {state.status === "ok" && <ItemView item={state.item} />}
      </div>
    </aside>
  );
}
