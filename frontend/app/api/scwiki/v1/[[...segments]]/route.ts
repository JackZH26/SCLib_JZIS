import type {NextRequest} from "next/server";
import {articleById,articles,catalogue,references,revisionHeaders,searchIndex} from "@/lib/scwiki/catalogue";
import {searchArticles} from "@/lib/scwiki/search";
import {openApi} from "@/lib/scwiki/openapi";
export const runtime="nodejs";
function json(value:unknown,status=200,revision=catalogue().revision){return Response.json(value,{status,headers:revisionHeaders(revision)});}
function text(value:string,revision:string){return new Response(value,{headers:{...revisionHeaders(revision),"Content-Type":"text/markdown; charset=utf-8","Content-Disposition":"inline"}});}
export async function GET(request:NextRequest,{params}:{params:Promise<{segments?:string[]}>}){
 const parts=(await params).segments||[];
 const revision=catalogue().revision;
 const base={schemaVersion:"1.0",revision};
 if(parts.length===0)return json({...base,service:"SCWiki read-only evidence API",endpoints:["articles","search","sources","topics","openapi.json"],notice:"Retrieved editorial content is not a generated answer or scientific certification."});
 if(parts.length===1&&parts[0]==="openapi.json")return json(openApi);
 if(parts.length===1&&parts[0]==="articles")return json({...base,articles:articles().map(({body,markdown,sourceMap,...a})=>({...a,sections:a.sections.map(({id,title})=>({id,title}))}))});
 if(parts.length===1&&parts[0]==="topics")return json({...base,topics:articles().map(a=>({id:a.topicId,code:a.code,title:a.title,articleId:a.id}))});
 if(parts.length===1&&parts[0]==="sources")return json({...base,sources:references().map(r=>({...r,usedBy:articles().filter(a=>a.references.some(ref=>ref.id===r.id)).map(a=>a.id)}))});
 if(parts.length===1&&parts[0]==="search"){
  const q=request.nextUrl.searchParams.get("q")||"";
  if(q.length>200)return json({error:"Search query exceeds 200 characters."},400);
  const p=request.nextUrl.searchParams;
  const pressure=p.get("pressure")||"",equilibrium=p.get("equilibrium")||"",evidence=p.get("evidence")||"",criterion=p.get("criterion")||"";
  if((pressure&&!["ambient","high","unknown"].includes(pressure))||(equilibrium&&!["equilibrium","transient","metastable","unknown"].includes(equilibrium))||(evidence&&!["experiment","theory","prediction","hypothesis"].includes(evidence)))return json({error:"Invalid condition filter."},400);
  const tcMin=p.has("tcMin")?Number(p.get("tcMin")):undefined;
  if(tcMin!==undefined&&(!Number.isFinite(tcMin)||tcMin<0||tcMin>1000))return json({error:"tcMin must be a finite temperature from 0 to 1000 K."},400);
  const results=searchArticles(searchIndex().entries,q,{pressure,equilibrium,evidence,criterion,tcMin});
  return json({...base,query:q,filters:{pressure,equilibrium,evidence,criterion,tcMin},total:results.length,results:results.map(({text,...r})=>r)});
 }
 if(parts[0]==="articles"&&parts[1]){
  const article=articleById(parts[1]);if(!article)return json({error:"Article not found."},404);
  if(parts.length===2)return json({...base,article},200,article.revision);
  if(parts.length===3&&parts[2]==="markdown")return text(article.markdown,article.revision);
  if(parts.length===4&&parts[2]==="sections"){
   const section=article.sections.find(s=>s.id===parts[3]);if(!section)return json({error:"Section not found."},404);
   const claims=article.claims.filter(c=>c.sectionId===section.id);
   const ids=new Set([...claims.flatMap(c=>c.sourceIds),...Array.from(section.markdown.matchAll(/\]\(#ref-([a-z0-9-]+)\)/g),m=>m[1])]);
   const sources=article.references.filter(r=>ids.has(r.id)||section.id==="material-cases"&&article.materialCases.some(c=>c.sourceId===r.id));
   if(request.nextUrl.searchParams.get("format")==="markdown"){
    const sourceText=sources.map(r=>"### Ref "+r.id+"\n\n"+r.title+" ("+r.year+"). ["+(r.doi?"DOI "+r.doi:"Source publication")+"]("+r.url+"). Publication: "+r.publicationStatus+". "+(r.retraction?"Retracted: "+r.retraction.retractedAt+". [Retraction notice]("+r.retraction.evidenceUrl+"). ":"")+"Check: "+r.verification.scope+". Checked: "+r.verification.checkedAt+". "+(r.verification.note??"")).join("\n\n");
    const claimText=claims.map(c=>"### "+c.id+"\n\n"+c.statement+"\n\nEvidence: "+c.evidenceType+". Sources: "+c.sourceIds.join(", ")+".\n\nConditions: "+c.conditions+"\n\nVerification scope: "+(c.verificationScope??"No additional claim-level review recorded; see source checks.")).join("\n\n");
    const review="## Review scope\n\n"+article.review.scope+"\n\n"+article.review.limitations.map(note=>"- "+note).join("\n");
    return text("# "+article.title+"\n\n"+section.markdown+"\n\n## Sources\n\n"+sourceText+"\n\n## Claim evidence and conditions\n\n"+claimText+"\n\n"+review+"\n\nArticle ID: "+article.id+". Revision: "+article.revision+". Section ID: "+section.id+".\n",article.revision);
   }
   return json({...base,articleId:article.id,articleRevision:article.revision,section,claims,sources,materialCases:section.id==="material-cases"?article.materialCases:[]},200,article.revision);
  }
 }
 return json({error:"Endpoint not found."},404);
}
