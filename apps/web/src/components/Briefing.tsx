import {
  SECTION_IDS,
  SECTION_TITLES,
  type BriefingSection,
  type Citation,
  type Sentence,
} from "@mpa/contract";
import { citeKey, tokenize, trailingCitations } from "@/lib/segments";
import type { RunStatus, RunView } from "@/lib/run";
import { CitationChip } from "./CitationChip";
import { InlineMarkdown } from "./InlineMarkdown";

interface Common {
  activeCite: string | null;
  onOpenSource: (citation: Citation) => void;
}

function SentenceItem({ sentence, activeCite, onOpenSource }: Common & { sentence: Sentence }) {
  const isNote = sentence.kind === "note";
  const chip = (c: Citation, key: string) => (
    <CitationChip key={key} citation={c} active={activeCite === citeKey(c)} onOpen={onOpenSource} />
  );
  return (
    <li className={isNote ? "italic text-slate-500" : undefined}>
      {tokenize(sentence.text).map((seg, i) =>
        seg.kind === "text" ? (
          <InlineMarkdown key={i} text={seg.text} />
        ) : (
          chip(seg.citation, `i${i}`)
        ),
      )}
      {trailingCitations(sentence.text, sentence.citations).map((c) => chip(c, citeKey(c)))}
    </li>
  );
}

function SectionView({ section, ...common }: Common & { section: BriefingSection }) {
  const sentences: readonly Sentence[] = section.sentences;
  return (
    <section data-testid={`section-${section.id}`} aria-labelledby={`h-${section.id}`}>
      <h3 id={`h-${section.id}`} className="mb-1.5 text-sm font-semibold text-slate-900">
        {section.title}
      </h3>
      {sentences.length === 0 ? (
        <p className="text-sm italic text-slate-500">Nothing to report for this section.</p>
      ) : (
        <ul className="list-disc space-y-1.5 pl-5 text-sm leading-6 text-slate-800 marker:text-slate-400">
          {sentences.map((s, i) => (
            <SentenceItem key={i} sentence={s} {...common} />
          ))}
        </ul>
      )}
    </section>
  );
}

function SectionSkeleton({ id }: { id: (typeof SECTION_IDS)[number] }) {
  return (
    <section data-testid={`section-skeleton-${id}`} aria-hidden="true">
      <h3 className="mb-1.5 text-sm font-semibold text-slate-400">{SECTION_TITLES[id]}</h3>
      <div className="skeleton space-y-2">
        <div className="h-3 w-11/12 rounded bg-slate-200" />
        <div className="h-3 w-3/4 rounded bg-slate-200" />
      </div>
    </section>
  );
}

interface Props extends Common {
  view: RunView;
  status: RunStatus;
}

export function Briefing({ view, status, ...common }: Props) {
  if (!view.writing) return null;
  const byId = new Map(view.sections.map((s) => [s.id, s]));
  const finished = status !== "running";
  const showBanner = finished && view.partial;
  return (
    <div data-testid="briefing" className="space-y-5 border-t border-slate-200 pt-4">
      <div>
        <h2 className="text-base font-semibold text-slate-900">
          {view.plan?.meeting_title ?? "Briefing"}
        </h2>
        {view.plan && <p className="text-xs text-slate-500">{view.plan.client}</p>}
      </div>
      {showBanner && (
        <div
          data-testid="partial-banner"
          role="status"
          className="rounded-lg border border-amber-300 bg-amber-50 px-3 py-2 text-sm text-amber-900"
        >
          <p className="font-semibold">Partial briefing</p>
          {view.gaps.length === 0 ? (
            <p className="text-xs">Some information may be missing from this briefing.</p>
          ) : (
            <ul className="mt-1 space-y-0.5 text-xs">
              {view.gaps.map((g, i) => (
                <li key={i} data-testid="gap">
                  <span className="font-medium">{g.source}</span> · {g.reason}
                  {g.detail ? ` · ${g.detail}` : ""}
                </li>
              ))}
            </ul>
          )}
        </div>
      )}
      {SECTION_IDS.map((id) => {
        const section = byId.get(id);
        if (section) return <SectionView key={id} section={section} {...common} />;
        return finished ? null : <SectionSkeleton key={id} id={id} />;
      })}
    </div>
  );
}
