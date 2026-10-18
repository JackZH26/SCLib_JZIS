import type {Article} from "./types";
import {ApiError} from "./http";

export const ARTICLE_FIELDS=["id","topicId","code","slug","title","summary","aliases","evidenceTypes","relatedCodes","editorialStatus","contentState","modifiedAt","revision","review","provenance","sourceMap","corrections","references","materialCases","claims","body","markdown","sections","wordCount","publicationKind","scopeItems"] as const;
export const REQUIRED_ARTICLE_FIELDS=["id","revision","code","slug","title","modifiedAt","editorialStatus","review","provenance"] as const;
const evidenceFields=new Set(["summary","body","markdown","sections","claims","materialCases","sourceMap","corrections","scopeItems"]);
export function parseArticleFields(raw:string|null):string[]|null{
 if(raw===null)return null;
 const selected=raw.split(",");
 if(!raw||selected.some(f=>!(ARTICLE_FIELDS as readonly string[]).includes(f))||new Set(selected).size!==selected.length)throw new ApiError(400,"INVALID_FIELDS","fields must be unique comma-separated article field names; nested paths and empty selections are not supported.");
 return selected.sort();
}
export function projectArticle(article:Article,fields:string[]):Record<string,unknown>{
 const selected=new Set<string>([...fields,...REQUIRED_ARTICLE_FIELDS]);
 // Scientific excerpts retain the entire local evidence bundle, not just labels.
 if(fields.some(f=>evidenceFields.has(f)))for(const f of ["claims","references","materialCases","scopeItems","corrections"])selected.add(f);
 return Object.fromEntries([...selected].sort().filter(f=>f in article).map(f=>[f,article[f as keyof Article]]));
}
