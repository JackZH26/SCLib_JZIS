// Publication inventory is separate from the immutable planning-source inventory.
export const articleIdPattern=/^scwiki-(?:[a-h][0-9]+|overview|[i-m]|n(?:[1-9]|10))$/;
export function sectionAnchor(title){
 const item=/^([I-M][0-9]+) — /u.exec(title);
 return (item?item[1]:title).toLowerCase().replace(/[^a-z0-9]+/g,"-").replace(/^-|-$/g,"");
}
export function validateExtensionInventory(inventory,manifest){
 const fail=reason=>{throw new Error("SCWiki extension inventory: "+reason)};
 const groups=[['I',15,'experimental-methods'],['J',12,'theoretical-tools'],['K',10,'applications'],['L',18,'history'],['M',6,'research-methodology']];
 const expected=new Map(groups.map(([code,count,slug])=>[code,{slug,kind:'handbook',items:Array.from({length:count},(_,i)=>code+(i+1))}]));
 for(let n=1;n<=10;n++)expected.set('N'+n,{slug:'open-questions/n'+n,kind:'open-question',items:['N'+n]});
 if(inventory.schemaVersion!==1||inventory.sourceCommit!==manifest.commit||inventory.pages?.length!==15)fail('frozen scope must retain 15 pages');
 const source=manifest.files.find(f=>f.path==='02_BATCH_2_IN_PLAN.md');
 const seen=new Set();
 for(const page of inventory.pages){
  const plan=expected.get(page.code);
  if(!plan||seen.has(page.code))fail('unknown or duplicate page');seen.add(page.code);
  if(page.id!=='scwiki-'+page.code.toLowerCase()||page.topicId!=='scwiki-topic-'+page.code.toLowerCase()||page.slug!==plan.slug||page.kind!==plan.kind||typeof page.publicBody!=='boolean'||page.sourceId!==source?.id)fail('page identity or planning provenance mismatch');
  if(!Array.isArray(page.items)||page.items.length!==plan.items.length||new Set(page.items.map(i=>i.id)).size!==plan.items.length)fail('missing or duplicate scope item');
  for(const item of page.items){
   const section=plan.kind==='handbook'?item.id.toLowerCase():null;
   if(!plan.items.includes(item.id)||item.sectionId!==section||item.target!==plan.slug+(section?'#'+section:'')||!Number.isInteger(item.sourceLine)||item.sourceLine<1||item.sourceLine>source.lineCount)fail('scope item target or source line mismatch');
  }
 }
 return inventory.pages.filter(p=>p.publicBody);
}
export function validateExtensionArticle(meta,chunks,registration){
 const fail=reason=>{throw new Error('SCWiki extension article: '+reason)};
 if(meta.slug!==registration.slug||meta.topicId!==registration.topicId||meta.publicationKind!==registration.kind||meta.provenance.sourceId!==registration.sourceId)fail('publication mapping mismatch');
 if(!Array.isArray(meta.scopeItems)||meta.scopeItems.length!==registration.items.length||new Set(meta.scopeItems.map(i=>i.id)).size!==registration.items.length)fail('each approved item needs its own review');
 for(const item of registration.items){
  const review=meta.scopeItems.find(r=>r.id===item.id);
  if(!review||review.status!=='scoped-check'||!/^\d{4}-\d{2}-\d{2}$/.test(review.checkedAt)||!review.scope||!review.limitations?.length||!review.sectionIds?.length)fail('missing item review scope');
  for(const id of review.sectionIds)if(!chunks.some(s=>s.id===id)||!meta.claims.some(c=>c.sectionId===id&&c.sourceIds.length))fail('item lacks cited section');
  if(item.sectionId&&(review.sectionIds.length!==1||review.sectionIds[0]!==item.sectionId))fail('stable handbook item anchor mismatch');
  const text=review.sectionIds.map(id=>chunks.find(s=>s.id===id).markdown).join(' ');
  if(text.split(/\s+/).length<100)fail('scope item has no substantive treatment');
 }
}
