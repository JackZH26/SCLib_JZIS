import {libraryNotes,libraryNote,libraryRevision,librarySearchEntries,libraryMarkdown} from "@/lib/scwiki/library";
import type {NextRequest} from "next/server";
import {articleById,articles,catalogue,references,revisionHeaders,searchIndex} from "@/lib/scwiki/catalogue";
import {searchArticles} from "@/lib/scwiki/search";
import {openApi} from "@/lib/scwiki/openapi";
import {ApiError,apiError,finalizeResponse,paginated,validateParameters} from "@/lib/scwiki/http";
import {parseArticleFields,projectArticle} from "@/lib/scwiki/projection";
import {revisionEntries} from "@/lib/scwiki/revisions";
export const runtime="nodejs";
function json(value:unknown,status=200,revision=catalogue().revision){return status>=400?apiError(new ApiError(status,status===404?"NOT_FOUND":"INVALID_REQUEST",(value as {error:string}).error)):Response.json(value,{status,headers:revisionHeaders(revision)});}
function text(value:string,revision:string){return new Response(value,{headers:{...revisionHeaders(revision),"Content-Type":"text/markdown; charset=utf-8","Content-Disposition":"inline"}});}
async function resource(request:NextRequest,{params}:{params:Promise<{segments?:string[]}>}){
 const parts=(await params).segments||[];
 const list=parts.length===1&&["articles","sources","topics","search","revisions","library"].includes(parts[0]);
 const allowed=list?["limit","cursor",...(parts[0]==="articles"?["fields"]:[]),...(parts[0]==="library"?["q"]:[]),...(parts[0]==="search"?["q","pressure","equilibrium","evidence","criterion","tcMin"]:[])]:parts.length===2&&parts[0]==="articles"?["fields"]:parts.length===4&&parts[2]==="sections"?["format"]:[];
 validateParameters(request,allowed);
 if(request.nextUrl.searchParams.has("format")&&!["json","markdown"].includes(request.nextUrl.searchParams.get("format")!))throw new ApiError(400,"INVALID_FORMAT","format must be json or markdown.");
 const fields=parseArticleFields(request.nextUrl.searchParams.get("fields"));
 const revision=catalogue().revision;
 const base={schemaVersion:"1.0",revision};
 if(parts.length===0)return json({...base,service:"SCWiki read-only evidence API",endpoints:["articles","search","sources","topics","revisions","library","openapi.json"],notice:"Retrieved editorial content is not a generated answer or scientific certification."});
 if(parts.length===1&&parts[0]==="openapi.json")return json(openApi);
 if(parts[0]==="library"){
  if(parts.length===1){
   const q=request.nextUrl.searchParams.get("q")||"";
   if(q.length>200)throw new ApiError(400,"INVALID_REQUEST","Search query exceeds 200 characters.");
   const ids=new Set(searchArticles(librarySearchEntries(),q).map(n=>n.id));
   return json(paginated(request,libraryNotes.filter(n=>ids.has(n.id)),libraryRevision,"notes",{query:q,collection:"research-library",notice:"Separate from the core article inventory; selected source review, not independent scientific acceptance."}),200,libraryRevision);
  }
  const note=libraryNote(parts[1]);
  if(!note)throw new ApiError(404,"NOT_FOUND","Research note not found.");
  if(parts.length===2)return json({schemaVersion:"1.0",revision:libraryRevision,note},200,note.revision);
  if(parts.length===3&&parts[2]==="markdown")return text(libraryMarkdown(note),note.revision);
  throw new ApiError(404,"NOT_FOUND","Library endpoint not found.");
 }
 if(parts.length===1&&parts[0]==="articles")return json(paginated(request,fields?articles().map(a=>projectArticle(a,fields)):articles().map(({body,markdown,sourceMap,...a})=>({...a,sections:a.sections.map(({id,title})=>({id,title}))})),revision,"articles",fields?{projection:{requested:fields,evidenceContextRetained:true}}:{}));
 if(parts.length===1&&parts[0]==="revisions")return json(paginated(request,revisionEntries(articles()),revision,"records",{snapshotKind:"complete-current-inventory",notice:"Collect every page at one revision before comparing with your prior complete snapshot. Absence from one page never proves removal. This is not a historical event log."}));
 if(parts.length===1&&parts[0]==="topics")return json(paginated(request,articles().map(a=>({id:a.topicId,code:a.code,title:a.title,articleId:a.id})),revision,"topics"));
 if(parts.length===1&&parts[0]==="sources")return json(paginated(request,references().map(r=>({...r,usedBy:articles().filter(a=>a.references.some(ref=>ref.id===r.id)).map(a=>a.id)})),revision,"sources"));
 if(parts.length===1&&parts[0]==="search"){
  const q=request.nextUrl.searchParams.get("q")||"";
  if(q.length>200)return json({error:"Search query exceeds 200 characters."},400);
  const p=request.nextUrl.searchParams;
  const pressure=p.get("pressure")||"",equilibrium=p.get("equilibrium")||"",evidence=p.get("evidence")||"",criterion=p.get("criterion")||"";
  if((pressure&&!["ambient","high","unknown"].includes(pressure))||(equilibrium&&!["equilibrium","transient","metastable","unknown"].includes(equilibrium))||(evidence&&!["experiment","theory","prediction","hypothesis"].includes(evidence)))return json({error:"Invalid condition filter."},400);
  if(criterion.length>128)return json({error:"criterion exceeds 128 characters."},400);
  if(p.has("tcMin")&&!/^(?:\d+(?:\.\d*)?|\.\d+)$/.test(p.get("tcMin")!))return json({error:"tcMin must be a decimal temperature from 0 to 1000 K."},400);
  const tcMin=p.has("tcMin")?Number(p.get("tcMin")):undefined;
  if(tcMin!==undefined&&(!Number.isFinite(tcMin)||tcMin<0||tcMin>1000))return json({error:"tcMin must be a finite temperature from 0 to 1000 K."},400);
  const results=searchArticles(searchIndex().entries,q,{pressure,equilibrium,evidence,criterion,tcMin});
  return json(paginated(request,results.map(({text,...r})=>r),revision,"results",{query:q,filters:{pressure,equilibrium,evidence,criterion,tcMin}}));
 }
 if(parts[0]==="articles"&&parts[1]){
  const article=articleById(parts[1]);if(!article)return json({error:"Article not found."},404);
  if(parts.length===2)return json({...base,article:fields?projectArticle(article,fields):article,...(fields?{projection:{requested:fields,evidenceContextRetained:true}}:{})},200,article.revision);
  if(parts.length===3&&parts[2]==="markdown")return text(article.markdown,article.revision);
  if(parts.length===4&&parts[2]==="sections"){
   const section=article.sections.find(s=>s.id===parts[3]);if(!section)return json({error:"Section not found."},404);
   const claims=article.claims.filter(c=>c.sectionId===section.id);
   const ids=new Set([...claims.flatMap(c=>c.sourceIds),...Array.from(section.markdown.matchAll(/\]\(#ref-([a-z0-9-]+)\)/g),m=>m[1])]);
   const sources=article.references.filter(r=>ids.has(r.id)||section.id==="material-cases"&&article.materialCases.some(c=>c.sourceId===r.id||c.preparation?.sourceId===r.id));
   const scopeItems=(article.scopeItems??[]).filter(item=>item.sectionIds.includes(section.id));
   if(request.nextUrl.searchParams.get("format")==="markdown"){
    const sourceText=sources.map(r=>"### Ref "+r.id+"\n\n"+r.title+" ("+(r.year??"Publication date unknown")+"). ["+(r.doi?"DOI "+r.doi:"Source publication")+"]("+r.url+"). Publication: "+r.publicationStatus+". "+(r.retraction?"Retracted: "+r.retraction.retractedAt+". [Retraction notice]("+r.retraction.evidenceUrl+"). ":"")+"Check: "+r.verification.scope+". Checked: "+r.verification.checkedAt+". "+(r.verification.note??"")).join("\n\n");
    const claimText=claims.map(c=>"### "+c.id+"\n\n"+c.statement+"\n\nEvidence: "+c.evidenceType+". Sources: "+c.sourceIds.join(", ")+"."+(c.sourceRelationship?"\n\nSource relationship: "+c.sourceRelationship+". "+c.derivationNote:"")+"\n\nConditions: "+c.conditions+"\n\nVerification scope: "+(c.verificationScope??"No additional claim-level review recorded; see source checks.")).join("\n\n");
    const itemReview=scopeItems.length?"\n\n## Approved scope items\n\n"+scopeItems.map(item=>item.id+". Checked: "+item.checkedAt+". "+item.scope+"\n\n"+item.limitations.map(x=>"- "+x).join("\n")).join("\n\n"):"";
    const review="## Review scope\n\n"+article.review.scope+"\n\n"+article.review.limitations.map(note=>"- "+note).join("\n");
    return text("# "+article.title+"\n\n"+section.markdown+"\n\n## Sources\n\n"+sourceText+"\n\n## Claim evidence and conditions\n\n"+claimText+"\n\n"+review+itemReview+"\n\nArticle ID: "+article.id+". Revision: "+article.revision+". Section ID: "+section.id+".\n",article.revision);
   }
   return json({...base,articleId:article.id,articleRevision:article.revision,review:article.review,section,claims,sources,scopeItems,materialCases:section.id==="material-cases"?article.materialCases:[]},200,article.revision);
  }
 }
 return json({error:"Endpoint not found."},404);
}

export async function GET(request:NextRequest,context:{params:Promise<{segments?:string[]}>}){
 try{return await finalizeResponse(request,await resource(request,context));}
 catch(error){if(error instanceof ApiError)return apiError(error);throw error;}
}
const allow="GET, HEAD, OPTIONS";
function readOnly(){return Response.json({error:"This API is read-only.",code:"METHOD_NOT_ALLOWED"},{status:405,headers:{Allow:allow,"Cache-Control":"no-store"}});}
export const POST=readOnly;
export const PUT=readOnly;
export const PATCH=readOnly;
export const DELETE=readOnly;
export function OPTIONS(){return new Response(null,{status:204,headers:{Allow:allow,"Cache-Control":"no-store"}});}
