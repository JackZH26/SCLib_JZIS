"use client";

/**
 * Renders text that may contain inline LaTeX delimited by `$...$`.
 * Non-math segments are rendered as plain text; math segments are
 * rendered via KaTeX into safe HTML (KaTeX only produces math markup,
 * no scripts). Falls back to the raw LaTeX string on parse errors.
 */
import katex from "katex";

export function LatexText({
  children,
  className,
}: {
  children: string;
  className?: string;
}) {
  // Split on $...$ but keep the delimiters so we know which parts are math.
  // Regex: match "$" followed by one or more non-"$" chars, then "$".
  const parts = children.split(/(\$[^$]+\$)/g);

  if (parts.length === 1) {
    // No LaTeX at all — fast path, plain text.
    return <span className={className}>{children}</span>;
  }

  return (
    <span className={className}>
      {parts.map((part, i) => {
        if (part.startsWith("$") && part.endsWith("$") && part.length > 2) {
          const tex = part.slice(1, -1);
          try {
            const html = katex.renderToString(tex, {
              throwOnError: false,
              output: "html",
            });
            return (
              <span
                key={i}
                dangerouslySetInnerHTML={{ __html: html }}
              />
            );
          } catch {
            // KaTeX couldn't parse it — show raw text.
            return <span key={i}>{part}</span>;
          }
        }
        return <span key={i}>{part}</span>;
      })}
    </span>
  );
}
