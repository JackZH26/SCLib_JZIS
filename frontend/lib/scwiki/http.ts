import {createHash} from "node:crypto";
import type {NextRequest} from "next/server";

export const API_CONTRACT_VERSION="1.3.0";
export const DEFAULT_PAGE_LIMIT=20;
export const MAX_PAGE_LIMIT=50;
export const MAX_PAGE_BYTES=256*1024;
export const MAX_RESPONSE_BYTES=1024*1024;
export class ApiError extends Error {
 constructor(public status:number,public code:string,message:string){super(message);}
}
const digest=(value:string)=>createHash("sha256").update(value).digest("hex");
export function validateParameters(request:NextRequest,allowed:string[]){
 if(request.nextUrl.pathname.length+request.nextUrl.search.length>4096)throw new ApiError(414,"URI_TOO_LONG","Request path and query exceed 4096 characters.");
 const seen=new Set<string>();
 for(const [key,value]of request.nextUrl.searchParams){
  if(!allowed.includes(key))throw new ApiError(400,"UNKNOWN_PARAMETER","Unknown query parameter: "+key.slice(0,64));
  if(seen.has(key))throw new ApiError(400,"DUPLICATE_PARAMETER","Query parameters must occur only once.");
  if(value.length>512)throw new ApiError(400,"PARAMETER_TOO_LONG","Query parameter exceeds its size limit.");
  seen.add(key);
 }
}
export function paginated<T>(request:NextRequest,items:T[],revision:string,key:string,extra:Record<string,unknown>={}){
 const params=request.nextUrl.searchParams;
 const value=params.get("limit");
 if(value!==null&&(!/^[1-9]\d{0,2}$/.test(value)||Number(value)>MAX_PAGE_LIMIT))throw new ApiError(400,"INVALID_LIMIT","limit must be an integer from 1 to 50.");
 const limit=value===null?DEFAULT_PAGE_LIMIT:Number(value);
 const canonical=new URLSearchParams(params);canonical.delete("cursor");canonical.set("limit",String(limit));canonical.sort();
 const scope=digest(API_CONTRACT_VERSION+request.nextUrl.pathname+"?"+canonical.toString()).slice(0,24);
 let offset=0;
 if(params.has("cursor")){
  const cursor=params.get("cursor")!;
  if(!/^[A-Za-z0-9_-]{1,256}$/.test(cursor))throw new ApiError(400,"INVALID_CURSOR","Invalid pagination cursor.");
  let decoded;
  try{decoded=JSON.parse(Buffer.from(cursor,"base64url").toString("utf8"));}catch{throw new ApiError(400,"INVALID_CURSOR","Invalid pagination cursor.");}
  if(!decoded||decoded.v!==1||!Number.isSafeInteger(decoded.offset)||decoded.offset<0||typeof decoded.revision!=="string")throw new ApiError(400,"INVALID_CURSOR","Invalid pagination cursor.");
  if(decoded.revision!==revision)throw new ApiError(409,"STALE_CURSOR","The catalogue changed. Restart pagination without a cursor.");
  if(decoded.scope!==scope||decoded.offset>=items.length)throw new ApiError(400,"INVALID_CURSOR","Cursor does not match this endpoint, query or page size.");
  offset=decoded.offset;
 }
 const make=(count:number)=>{
  const nextOffset=offset+count;
  const nextCursor=nextOffset<items.length?Buffer.from(JSON.stringify({v:1,revision,scope,offset:nextOffset})).toString("base64url"):null;
  const nextParams=new URLSearchParams(params);nextParams.set("limit",String(limit));
  if(nextCursor)nextParams.set("cursor",nextCursor);
  const next=nextCursor?request.nextUrl.pathname+"?"+nextParams.toString():null;
  return {schemaVersion:"1.0",revision,...extra,total:items.length,[key]:items.slice(offset,nextOffset),page:{limit,returned:count,nextCursor,next}};
 };
 let count=Math.min(limit,items.length-offset),result=make(count);
 // Bound bytes as well as item count. Never truncate a scientific evidence record.
 while(Buffer.byteLength(JSON.stringify(result))>MAX_PAGE_BYTES&&count>1){count--;result=make(count);}
 if(Buffer.byteLength(JSON.stringify(result))>MAX_PAGE_BYTES)throw new ApiError(503,"RECORD_TOO_LARGE","A catalogue record exceeds the page limit; retrieve the article or section directly.");
 return result;
}
export async function finalizeResponse(request:NextRequest,response:Response){
 if(response.status!==200)return response;
 const body=await response.text();
 if(Buffer.byteLength(body)>MAX_RESPONSE_BYTES)return apiError(new ApiError(503,"RESPONSE_TOO_LARGE","This representation exceeds the response limit. Retrieve individual sections."));
 const headers=new Headers(response.headers);
 // Weak validator covers the representation before optional transport compression.
 const etag='W/"'+digest((headers.get("Content-Type")||"")+"\n"+body)+'"';
 headers.set("ETag",etag);
 const condition=request.headers.get("If-None-Match");
 const matches=condition?.split(",").some(tag=>tag.trim()==="*"||tag.trim().replace(/^W\//,"")===etag.slice(2));
 return new Response(matches?null:body,{status:matches?304:200,headers});
}
export function apiError(error:ApiError){
 return Response.json({error:error.message,code:error.code},{status:error.status,headers:{"Cache-Control":"no-store","X-Content-Type-Options":"nosniff"}});
}
