import ReactMarkdown from "react-markdown";

const INLINE = ["p", "strong", "em", "code", "del", "a", "br"];

/** Untrusted text as inline markdown: no raw HTML, no images, links shown as plain styled text. */
export function InlineMarkdown({ text }: { text: string }) {
  return (
    <ReactMarkdown
      skipHtml
      allowedElements={INLINE}
      unwrapDisallowed
      components={{
        p: ({ children }) => <>{children}</>,
        a: ({ children }) => <span className="underline decoration-dotted">{children}</span>,
        code: ({ children }) => (
          <code className="rounded bg-slate-100 px-1 py-0.5 font-mono text-[0.85em]">{children}</code>
        ),
      }}
    >
      {text}
    </ReactMarkdown>
  );
}
