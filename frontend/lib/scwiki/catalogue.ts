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
export function references() {
  const grouped=new Map<string, {reference: Article["references"][number]; articleChecks: {articleId:string; verification:Article["references"][number]["verification"]}[]}>();
  for(const article of articles())for(const reference of article.references){
    const group=grouped.get(reference.id)??{reference,articleChecks:[]};
    group.articleChecks.push({articleId:article.id,verification:reference.verification});
    grouped.set(reference.id,group);
  }
  return [...grouped.values()].map(({reference,articleChecks})=>{
    const distinct=new Set(articleChecks.map(check=>JSON.stringify(check.verification)));
    const verification=distinct.size===1?reference.verification:{
      scope:"article-scoped-checks", checkedAt:articleChecks.map(c=>c.verification.checkedAt).sort().at(-1)!,
      evidenceUrl:reference.url,
      note:"Review scope varies by article. Use articleChecks or the article/section endpoint; a source check does not certify every claim that cites it.",
    };
    return {...reference,verification,articleChecks};
  });
}
export function revisionHeaders(revision=catalogue().revision) {
  return { "X-SCWiki-Revision":revision, ETag:'"'+revision+'"', "Cache-Control":"public, max-age=300", "X-Content-Type-Options":"nosniff" };
}
