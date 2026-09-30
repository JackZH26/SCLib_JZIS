import Link from "next/link";
import { Children, cloneElement, isValidElement, type ReactNode } from "react";

/** Add stable, local heading anchors without changing any existing anchor. */
export function InformationPage({ title, description, children }: { title: string; description: string; children: ReactNode }) {
  const contents: { id: string; title: string }[] = [];
  const body = Children.map(children, (child) => {
    if (!isValidElement<{ children?: ReactNode; id?: string; className?: string }>(child) || child.type !== "h2" || typeof child.props.children !== "string") return child;
    const id = child.props.id || child.props.children.toLowerCase().replace(/[^a-z0-9]+/g, "-").replace(/^-|-$/g, "");
    contents.push({ id, title: child.props.children });
    return cloneElement(child, { id, className: `${child.props.className || ""} scroll-mt-28` });
  });
  return <main className="information-page py-3 sm:py-6">
    <Link href="/" className="site-text-link text-sm font-medium">SCLib</Link>
    <div className="mb-9 mt-6 max-w-4xl sm:mb-12">
      <h1 className="text-3xl font-semibold leading-tight tracking-tight sm:text-4xl lg:text-5xl">{title}</h1>
      <p className="mt-5 max-w-2xl text-lg leading-relaxed text-sage-muted">{description}</p>
    </div>
    <div className="grid gap-8 border-t border-sage-border pt-8 lg:grid-cols-[230px_minmax(0,1fr)] lg:gap-14 lg:pt-10">
      {contents.length > 0 && <nav aria-label="On this page" className="self-start lg:sticky lg:top-28">
        <h2 className="text-sm font-semibold">On this page</h2>
        <ul className="mt-3 flex flex-wrap gap-x-5 gap-y-3 text-sm lg:flex-col lg:gap-0">
          {contents.map(item => <li key={item.id}><a href={`#${item.id}`} className="contents-link inline-block py-1 leading-relaxed text-sage-muted hover:text-accent-deep lg:py-2">{item.title}</a></li>)}
        </ul>
      </nav>}
      <article className="prose prose-slate min-w-0 max-w-[68ch] prose-headings:font-semibold prose-headings:tracking-tight prose-h2:mt-10 prose-h2:scroll-mt-28 prose-h2:text-2xl prose-p:leading-relaxed prose-a:text-accent-deep prose-a:underline-offset-4">{body}</article>
    </div>
  </main>;
}
