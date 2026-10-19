// Article-specific review scopes may differ; publication identities must not.
const normalizedTitle=value=>value.normalize("NFKC").toLowerCase().replace(/[^\p{L}\p{N}]/gu,"");
export function validateReferenceIdentities(articles){
 const identities=new Map(),doiIds=new Map();
 for(const article of articles){
  const local=new Set();
  for(const ref of article.references){
   if(local.has(ref.id))throw new Error(`SCWiki: duplicate reference ID ${ref.id} in ${article.code}`);
   local.add(ref.id);
   const doi=ref.doi?.toLowerCase()??null;
   // Without a DOI, use the curated canonical URL, title and year, not the URL alone.
   const identity=JSON.stringify([doi,ref.year,...(doi?[]:[ref.url,normalizedTitle(ref.title)])]);
   const previous=identities.get(ref.id);
   if(previous&&previous.identity!==identity)throw new Error(`SCWiki: source ID ${ref.id} has conflicting publication identities in ${previous.code} and ${article.code}`);
   identities.set(ref.id,{identity,code:article.code});
   if(doi){
    const priorId=doiIds.get(doi);
    if(priorId&&priorId!==ref.id)throw new Error(`SCWiki: DOI ${doi} has multiple source IDs`);
    doiIds.set(doi,ref.id);
   }
  }
 }
}
