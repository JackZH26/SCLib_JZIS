import Link from "next/link";
import type { ReactNode } from "react";

export function InformationPage({ title, description, children }: { title: string; description: string; children: ReactNode }) {
  return <main className="mx-auto max-w-3xl py-4 sm:py-8">
    <Link href="/" className="text-sm underline underline-offset-4">SCLib</Link>
    <h1 className="mt-6 text-3xl font-bold tracking-tight sm:text-4xl">{title}</h1>
    <p className="mt-4 text-lg text-sage-muted">{description}</p>
    <div className="prose prose-slate mt-10 max-w-none prose-a:text-accent prose-a:underline-offset-4 prose-headings:font-semibold">{children}</div>
  </main>;
}
