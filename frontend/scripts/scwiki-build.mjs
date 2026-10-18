import {readFileSync,readdirSync,writeFileSync} from "node:fs";
import path from "node:path";
import {createHash} from "node:crypto";
import katex from "katex";
import {articleIdPattern,sectionAnchor,validateExtensionInventory,validateExtensionArticle} from "./scwiki-publication.mjs";

const directory=path.join(process.cwd(),"content/scwiki");
const sha=value=>createHash("sha256").update(value).digest("hex");
const anchor=sectionAnchor;
const fail=message=>{throw new Error("SCWiki: "+message)};
const required=["scope","mathematical-assumptions","experimental-criteria","limits-and-disputes","discovery-implications","related-topics"];
const manifest=JSON.parse(readFileSync(path.join(directory,"source-manifest.json"),"utf8"));
const bySource=new Map(manifest.files.map(f=>[f.id,f]));
// publicBody is an explicit editorial publication decision, not a file-count target.
const publishedSources=manifest.files.filter(f=>f.publicBody);
const expectedIds=new Set(publishedSources.map(f=>f.articleId));
if(!expectedIds.size||expectedIds.size!==publishedSources.length||publishedSources.some(f=>!/^scwiki-(?:[a-h][0-9]+|overview)$/.test(f.articleId)))fail("invalid publication inventory");
const extensionInventory=JSON.parse(readFileSync(path.join(directory,"extension-inventory.json"),"utf8"));
const publishedExtensions=validateExtensionInventory(extensionInventory,manifest);
const extensions=new Map(publishedExtensions.map(p=>[p.id,p]));
for(const p of publishedExtensions){if(expectedIds.has(p.id))fail("duplicate extension publication");expectedIds.add(p.id);}
const articles=[],ids=new Set(),slugs=new Set();
for(const folder of readdirSync(path.join(directory,"articles")).sort()){
 const meta=JSON.parse(readFileSync(path.join(directory,"articles",folder,"meta.json"),"utf8"));
 const body=readFileSync(path.join(directory,"articles",folder,"body.md"),"utf8").trim();
 if(meta.contentState!=="pilot")continue;
 for(const key of ["id","topicId","code","slug","title","summary","modifiedAt"])if(!meta[key])fail(folder+" missing "+key);
 if(!articleIdPattern.test(meta.id)||meta.topicId!=="scwiki-topic-"+meta.code.toLowerCase()||! /^(?:[-a-z0-9]+|open-questions\/n(?:[1-9]|10))$/.test(meta.slug))fail(folder+" invalid ID");
 if(ids.has(meta.id)||slugs.has(meta.slug))fail("duplicate article");
 ids.add(meta.id);slugs.add(meta.slug);
 const source=bySource.get(meta.provenance.sourceId);
 const extension=extensions.get(meta.id);
 if(meta.id!=="scwiki-"+meta.code.toLowerCase()||(!extension&&(!source?.publicBody||source.articleId!==meta.id||source.topicId!==meta.topicId)))fail(folder+" article is not approved in the publication inventory");
 if(!source||source.sha256!==meta.provenance.sha256||source.path!==meta.provenance.path||meta.provenance.commit!==manifest.commit)fail(folder+" provenance mismatch");
 if(/\p{Script=Han}/u.test(body)||/\p{Script=Han}/u.test(meta.title+" "+meta.summary))fail(folder+" authored English content contains Han copy");
 if(/<\/?[a-z][^>]*>/i.test(body)||/\]\(\s*(?:javascript|data|vbscript):/i.test(body))fail(folder+" unsafe authored Markdown");
 const chunks=body.split(/^## /m).slice(1).map(chunk=>{
  const split=chunk.indexOf("\n"),title=chunk.slice(0,split).trim();
  return {id:anchor(title),title,markdown:"## "+chunk.trim()};
 });
 for(const id of required)if(!chunks.some(s=>s.id===id))fail(folder+" missing section "+id);
 if(extension)validateExtensionArticle(meta,chunks,extension);
 const sectionIds=new Set(chunks.map(s=>s.id));
 if(sectionIds.size!==chunks.length)fail(folder+" duplicate section");
 const refIds=new Set(meta.references.map(r=>r.id));
 for(const ref of meta.references)if(ref.year!==null&&(!Number.isInteger(ref.year)||ref.year<1000))fail(folder+" invalid source publication year");
 // Known identity corrections must also protect future migrations of pinned chapters.
 const incorrectDois=new Set((manifest.correctionRegister??[]).filter(c=>c.incorrectDoi&&(c.correctDoi||c.correctUrl)).map(c=>c.incorrectDoi.toLowerCase()));
 for(const ref of meta.references)if((ref.doi!==null&&(typeof ref.doi!=="string"||!/^10\.\d{4,9}\/\S+$/.test(ref.doi)))||!/^source-[a-f0-9]{16}$/.test(ref.id)||!/^https:\/\//.test(ref.url)||!ref.verification?.scope)fail(folder+" reference schema");
 for(const ref of meta.references)if(ref.doi!==null&&incorrectDois.has(ref.doi.toLowerCase()))fail(folder+" known incorrect DOI "+ref.doi);
 const citedDois=new Set(meta.references.map(r=>r.doi?.toLowerCase()).filter(Boolean));
 for(const correction of manifest.correctionRegister??[]){
  if(correction.articleDoi&&correction.requiredCompanionDoi&&citedDois.has(correction.articleDoi.toLowerCase())&&!citedDois.has(correction.requiredCompanionDoi.toLowerCase()))fail(folder+" missing required erratum "+correction.requiredCompanionDoi);
  if(correction.retractedDoi){
   const retracted=meta.references.find(r=>r.doi?.toLowerCase()===correction.retractedDoi.toLowerCase());
   if(retracted&&(!retracted.retraction||retracted.retraction.noticeDoi!==correction.retractionNoticeDoi||retracted.retraction.retractedAt!==correction.retractedAt))fail(folder+" missing known retraction metadata "+correction.retractedDoi);
  }
 }
 for(const ref of meta.references)if(ref.retraction){
  const notice=ref.retraction;
  if(!/^10\.\d{4,9}\/\S+$/.test(notice.noticeDoi??"")||!/^\d{4}-\d{2}-\d{2}$/.test(notice.retractedAt??"")||!/^https:\/\//.test(notice.evidenceUrl??""))fail(folder+" invalid retraction metadata");
  if(!citedDois.has(notice.noticeDoi.toLowerCase())||notice.noticeDoi.toLowerCase()===ref.doi?.toLowerCase())fail(folder+" missing retraction notice "+notice.noticeDoi);
 }
 for(const claim of meta.claims)if(!sectionIds.has(claim.sectionId)||!claim.sourceIds.length||claim.sourceIds.some(id=>!refIds.has(id))||!claim.conditions)fail(folder+" claim mapping "+claim.id);
 for(const c of meta.claims){
  if(c.sourceRelationship!==undefined&&(!["direct-support","context-for-local-derivation","mixed-source-and-local-derivation"].includes(c.sourceRelationship)||typeof c.derivationNote!=="string"||!c.derivationNote.trim()))fail(folder+" invalid claim source relationship "+c.id);
  if(c.derivationNote!==undefined&&c.sourceRelationship===undefined)fail(folder+" missing claim source relationship "+c.id);
 }
 for(const match of body.matchAll(/\]\(#ref-([a-z0-9-]+)\)/g))if(!refIds.has(match[1]))fail(folder+" unresolved citation");
 for(const match of body.matchAll(/\$\$([\s\S]+?)\$\$|\$([^\n$]+)\$/g)){
  try{katex.renderToString(match[1]??match[2],{throwOnError:true,trust:false,maxExpand:1000,maxSize:10});}
  catch(error){fail(folder+" invalid math: "+error.message)}
 }
 for(const record of meta.materialCases){
  if(record.aliases!==undefined&&(!Array.isArray(record.aliases)||record.aliases.some(a=>typeof a!=="string"||!a.trim())))fail(folder+" invalid material aliases");
  const pressure=record.pressureGPa;
  if(pressure!==null&&(typeof pressure!=="object"||Array.isArray(pressure)||!Number.isFinite(pressure.min)||!Number.isFinite(pressure.max)||pressure.min<0||pressure.max<pressure.min))fail(folder+" invalid pressure range");
  if(!["ambient","high","unknown"].includes(record.pressureRegime)||!["equilibrium","transient","metastable","unknown"].includes(record.equilibrium)||!["theory","experiment","prediction","hypothesis"].includes(record.recordType))fail(folder+" invalid material condition enum");
  if(!["transition","spectroscopic-gap","measurement","normal-state","transient-response","unassigned"].includes(record.temperatureKind))fail(folder+" invalid temperature kind");
  if(record.reportedTemperatureK!==null&&(!Number.isFinite(record.reportedTemperatureK)||record.reportedTemperatureK<0))fail(folder+" invalid reported temperature");
  if(!refIds.has(record.sourceId)||!record.criterion||!record.sample||!record.probe||!record.equilibrium||!record.pressureRegime)fail(folder+" missing material conditions");
  if(record.temperatureKind!=="transition"&&record.tcK!==null)fail(folder+" non-transition temperature is not a transition Tc");
  if(record.tcK!==null&&(!Number.isFinite(record.tcK)||record.tcK<0))fail(folder+" invalid Tc");
  if(record.recordType!=="experiment"&&record.tcK!==null)fail(folder+" non-experimental Tc cannot enter experimental records");
  if(record.tcK!==null&&meta.references.find(r=>r.id===record.sourceId)?.retraction)fail(folder+" retracted source cannot supply an experimental Tc");
 }
 const conditions=meta.materialCases.length===0?"## Material cases\n\nNo sample-specific material records are included in this article. Model results are not experimental transition temperatures.":"## Material cases\n\nValues describe individual reports, not a ranking. Unknown means the checked source did not supply the field at this review scope.\n\n"+
 "| Material and sample | Reported temperature | Criterion | Probe | Pressure | State | Evidence |\n|---|---|---|---|---|---|---|\n"+
 meta.materialCases.map(r=>"| "+r.formula+(r.aliases?.length?" (aliases: "+r.aliases.join(", ")+")":"")+"; "+r.sample+" | "+(r.reportedTemperatureK===null?r.temperatureNote:r.reportedTemperatureK+" K; "+r.temperatureNote)+" | "+r.temperatureKind+"; "+r.criterion+" | "+r.probe+" | "+r.pressureRegime+"; "+(r.pressureGPa?r.pressureGPa.min+" to "+r.pressureGPa.max+" GPa":"unknown GPa")+" | "+r.equilibrium+" | "+r.recordType+"; [source](#ref-"+r.sourceId+") |").join("\n");
 const referenceText=meta.references.map((r,i)=>"### Ref "+r.id+"\n\n[R"+(i+1)+"] "+r.title+" ("+(r.year??"Publication date unknown")+"). ["+(r.doi?"DOI "+r.doi:"Source publication")+"]("+r.url+"). Publication: "+r.publicationStatus+". "+(r.retraction?"Retracted: "+r.retraction.retractedAt+". [Retraction notice]("+r.retraction.evidenceUrl+"). ":"")+"Check: "+r.verification.scope+". Checked: "+r.verification.checkedAt+". "+(r.verification.note??"")).join("\n");
 // Export v4 also retains each material record's probe and measurement protocol.
 const revision=sha("scwiki-export-v4\n"+JSON.stringify(meta)+"\n"+body).slice(0,20);
 const provenance="## Revision and review\n\nArticle ID: "+meta.id+". Revision: "+revision+". Updated: "+meta.modifiedAt+".\n\nReview scope: "+meta.review.scope+"\n\n"+meta.review.limitations.map(x=>"- "+x).join("\n")+"\n\nSource: ["+meta.provenance.path+"](https://github.com/"+meta.provenance.repository+"/blob/"+meta.provenance.commit+"/"+meta.provenance.path+"), commit "+meta.provenance.commit+", SHA-256 "+meta.provenance.sha256+".";
 const claimText="## Claim evidence and conditions\n\n"+meta.claims.map(c=>"### "+c.id+"\n\n"+c.statement+"\n\nEvidence: "+c.evidenceType+". Sources: "+c.sourceIds.join(", ")+"."+(c.sourceRelationship?"\n\nSource relationship: "+c.sourceRelationship+". "+c.derivationNote:"")+"\n\nConditions: "+c.conditions+"\n\nVerification scope: "+(c.verificationScope??"No additional claim-level review recorded; see source checks.")).join("\n\n");
 const scopeText=(meta.scopeItems??[]).length?"\n\n## Approved scope items\n\n"+meta.scopeItems.map(item=>item.id+". Checked: "+item.checkedAt+". "+item.scope+"\n\n"+item.limitations.map(x=>"- "+x).join("\n")).join("\n\n"):"";
 const markdown="# "+meta.title+"\n\n"+meta.summary+"\n\n"+body+"\n\n"+conditions+"\n\n## Sources\n\n"+referenceText+"\n\n"+claimText+scopeText+"\n\n"+provenance+"\n";
 articles.push({...meta,body,revision,sections:[...chunks,{id:"material-cases",title:"Material cases",markdown:conditions}],markdown,wordCount:body.split(/\s+/).length});
}
if(articles.length!==expectedIds.size||articles.some(a=>!expectedIds.has(a.id)))fail("published articles do not match the publication inventory");
for(const a of articles)for(const code of a.relatedCodes)if(!articles.some(other=>other.code===code))fail("unpublished related article "+code);
const revision=sha(articles.map(a=>a.revision).join("\n")).slice(0,20);
const catalogue={schemaVersion:"1.0",revision,articles};
const entries=articles.map(({id,topicId,code,slug,title,summary,aliases,evidenceTypes,editorialStatus,revision,materialCases,references,body})=>({id,topicId,code,slug,title,summary,aliases,evidenceTypes,editorialStatus,revision,materialCases,dois:references.map(r=>r.doi).filter(doi=>typeof doi==="string"),text:body.replace(/\[[^\]]+\]\([^)]+\)/g,"").replace(/[$#*_\x60]/g,"")}));
for(const[name,value]of[["catalogue.json",catalogue],["search-index.json",{schemaVersion:"1.0",revision,entries}]]){
 const data=JSON.stringify(value,null,2)+"\n",filename=path.join(directory,name);
 if(process.argv.includes("--check")){if(readFileSync(filename,"utf8")!==data)fail(name+" is stale");}
 else writeFileSync(filename,data);
}
console.log(JSON.stringify({articles:articles.length,sourceFiles:manifest.files.length,revision,wordCounts:articles.map(a=>[a.code,a.wordCount])}));
