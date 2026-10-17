import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import remarkMath from "remark-math";
import rehypeSanitize, { defaultSchema } from "rehype-sanitize";
import rehypeKatex from "rehype-katex";
import { safeUrl, sectionId } from "@/lib/scwiki/safety";
const schema: typeof defaultSchema={...defaultSchema,attributes:{...defaultSchema.attributes,code:[["className",/^language-./,"math-inline","math-display"]]}};
function textOf(node: unknown): string {
  const n=node as {value?:string;children?:unknown[]};
  return n?.value || n?.children?.map(textOf).join("") || "";
}
export function ScientificMarkdown({markdown}:{markdown:string}) {
  return <div className="scwiki-prose">
    <ReactMarkdown skipHtml urlTransform={safeUrl}
      remarkPlugins={[remarkGfm,remarkMath]}
      rehypePlugins={[[rehypeSanitize,schema],[rehypeKatex,{trust:false,strict:"warn",maxExpand:1000,maxSize:10,throwOnError:false}]]}
      components={{
        h2:({node,children})=><h2 id={sectionId(textOf(node))}>{children}</h2>,
        h3:({node,children})=><h3 id={sectionId(textOf(node))}>{children}</h3>,
        a:({href,children})=><a href={safeUrl(href||"")||undefined} rel={href?.startsWith("https:")?"noopener noreferrer":undefined}>{children}</a>,
        img:({src,alt})=>typeof src==="string" && /^\/scwiki\/assets\/[a-zA-Z0-9/_-]+\.(png|jpe?g|webp)$/.test(src)
          ? <figure><img src={src} alt={alt||""} loading="lazy"/><figcaption>{alt}</figcaption></figure>
          : <span role="note">Image unavailable: {alt||"No description supplied"}</span>,
        table:({children})=><div className="scwiki-table-scroll" tabIndex={0} aria-label="Scrollable scientific table"><table>{children}</table></div>,
      }}>{markdown}</ReactMarkdown>
  </div>;
}
