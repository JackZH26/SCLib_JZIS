import { readFileSync } from "node:fs";
import path from "node:path";
import type { Article, SearchEntry } from "./types";
interface Catalogue { schemaVersion: string; revision: string; articles: Article[] }
let cached: Catalogue | undefined;
export function catalogue(): Catalogue {
  return cached ??= JSON.parse(readFileSync(path.join(process.cwd(),"content/scwiki/catalogue.json"),"utf8")) as Catalogue;
}
export function articles() { return catalogue().articles; }
export function articleById(id: string) { return articles().find(article=>article.id===id || article.slug===id); }
export function searchIndex(): { revision: string; entries: SearchEntry[] } {
  return JSON.parse(readFileSync(path.join(process.cwd(),"content/scwiki/search-index.json"),"utf8"));
}
export function references() { return [...new Map(articles().flatMap(a=>a.references.map(r=>[r.id,r] as const))).values()]; }
export function revisionHeaders(revision=catalogue().revision) {
  return { "X-SCWiki-Revision":revision, ETag:'"'+revision+'"', "Cache-Control":"public, max-age=300", "X-Content-Type-Options":"nosniff" };
}
