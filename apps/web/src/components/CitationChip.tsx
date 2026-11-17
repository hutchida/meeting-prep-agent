import type { Citation } from "@mpa/contract";
import { citeKey } from "@/lib/segments";

interface Props {
  citation: Citation;
  active: boolean;
  onOpen: (citation: Citation) => void;
}

export function CitationChip({ citation, active, onOpen }: Props) {
  const key = citeKey(citation);
  return (
    <button
      type="button"
      data-testid="citation"
      data-cite={key}
      aria-label={`Open source ${citation.type} ${citation.id}`}
      aria-pressed={active}
      title={key}
      onClick={() => onOpen(citation)}
      className={`mx-0.5 inline-flex h-5 items-center rounded-md border px-1.5 align-baseline font-mono text-[11px] leading-none transition-colors ${
        active
          ? "border-accent bg-accent text-white"
          : "border-slate-300 bg-slate-100 text-slate-700 hover:border-accent hover:bg-white hover:text-accent"
      }`}
    >
      {citation.id}
    </button>
  );
}
