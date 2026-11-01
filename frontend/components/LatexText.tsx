/** Source notation is rendered on the server; raw assertions stay in the API. */
import { renderSourceNotation } from "@/lib/source-notation";

export function LatexText({ children, className, math = false }: {
  children: string; className?: string; math?: boolean;
}) {
  const rendered = renderSourceNotation(children, math);
  return <span className={className} dangerouslySetInnerHTML={{ __html: rendered.html }} />;
}
