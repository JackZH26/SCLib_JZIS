"use client";

/**
 * Renders the Gemini [n]-cited markdown answer from /ask and
 * hyperlinks each [n] bracket to the corresponding source in the
 * sidebar. The source list is passed in so [n] clicks can scroll
 * to the referenced card.
 */
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import type { AskSource } from "@/lib/api";

export function MarkdownAnswer({
  markdown,
  sources,
}: {
  markdown: string;
  sources: AskSource[];
}) {
  // Turn "[1]" into a markdown link that react-markdown will render
  // as an anchor, so we don't need custom tokenization inside MDAST.
  const linked = markdown.replace(/\[(\d+)\]/g, (m, n) => {
    const idx = Number(n);
    if (!sources.some((s) => s.index === idx)) return m;
    return `[[${n}]](#src-${n})`;
  });

  return (
    <div className="prose prose-slate max-w-none prose-p:leading-relaxed prose-a:text-blue-600">
      <ReactMarkdown remarkPlugins={[remarkGfm]}>{linked}</ReactMarkdown>
    </div>
  );
}
