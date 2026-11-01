/**
 * Source notation is rendered on the server; no math runtime is needed by
 * Materials in the browser. Unknown paper macros remain escaped source text.
 */
import katex from "katex";
import "katex/contrib/mhchem";

const MATH_PART = /((?<!\\)\$\$[\s\S]+?(?<!\\)\$\$|(?<!\\)\$[^$]+?(?<!\\)\$|\\\([\s\S]+?\\\)|\\\[[\s\S]+?\\\])/g;

function mathPart(tex: string, original: string, key: number) {
  try {
    const html = katex.renderToString(tex, {
      throwOnError: true, trust: false, strict: "ignore", output: "htmlAndMathml",
      maxExpand: 200, maxSize: 10,
    });
    return <span key={key} className="reported-math" dangerouslySetInnerHTML={{ __html: html }} />;
  } catch {
    return <span key={key}>{original}</span>;
  }
}

export function LatexText({
  children,
  className,
  math = false,
}: {
  children: string;
  className?: string;
  /** A formula or quantity may contain undelimited TeX; prose must not. */
  math?: boolean;
}) {
  const parts = children.split(MATH_PART);

  if (parts.length === 1) {
    return <span className={className}>{math && /[\\_^]/.test(children)
      ? mathPart(children, children, 0) : children}</span>;
  }

  return (
    <span className={className}>
      {parts.map((part, i) => {
        if ((part.startsWith("$$") && part.endsWith("$$"))
          || (part.startsWith("\\(") && part.endsWith("\\)"))
          || (part.startsWith("\\[") && part.endsWith("\\]"))) {
          return mathPart(part.slice(2, -2), part, i);
        }
        if (part.startsWith("$") && part.endsWith("$") && part.length > 2) {
          return mathPart(part.slice(1, -1), part, i);
        }
        return <span key={i}>{part}</span>;
      })}
    </span>
  );
}
