"use client";

/**
 * Renders the Gemini [n]-cited markdown answer from /ask and
 * hyperlinks each [n] bracket to the corresponding source in the
 * sidebar. The source list is passed in so [n] clicks can scroll
 * to the referenced card.
 */
import ReactMarkdown from "react-markdown";
import rehypeSanitize from "rehype-sanitize";
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
    // react-markdown already blocks raw HTML and javascript: URLs by
    // default. rehype-sanitize is belt-and-braces: even if Gemini
    // ever emits an exotic scheme or the default url transform
    // regresses, the sanitizer strips it before it hits the DOM.
    <div className="prose prose-slate max-w-none prose-p:leading-relaxed prose-a:text-accent hover:prose-a:text-accent-deep">
      <ReactMarkdown
        remarkPlugins={[remarkGfm]}
        rehypePlugins={[rehypeSanitize]}
      >
        {linked}
      </ReactMarkdown>
    </div>
  );
}
