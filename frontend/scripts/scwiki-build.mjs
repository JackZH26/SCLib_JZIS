import {readFileSync,readdirSync,writeFileSync} from "node:fs";
import path from "node:path";
import {createHash} from "node:crypto";
import katex from "katex";

const directory=path.join(process.cwd(),"content/scwiki");
const sha=value=>createHash("sha256").update(value).digest("hex");
const anchor=value=>value.toLowerCase().replace(/[^a-z0-9]+/g,"-").replace(/^-|-$/g,"");
const fail=message=>{throw new Error("SCWiki: "+message)};
const required=["scope","mathematical-assumptions","experimental-criteria","limits-and-disputes","discovery-implications","related-topics"];
const manifest=JSON.parse(readFileSync(path.join(directory,"source-manifest.json"),"utf8"));
const bySource=new Map(manifest.files.map(f=>[f.id,f]));
const articles=[],ids=new Set(),slugs=new Set();
for(const folder of readdirSync(path.join(directory,"articles")).sort()){
 const meta=JSON.parse(readFileSync(path.join(directory,"articles",folder,"meta.json"),"utf8"));
 const body=readFileSync(path.join(directory,"articles",folder,"body.md"),"utf8").trim();
 if(meta.contentState!=="pilot")continue;
 for(const key of ["id","topicId","code","slug","title","summary","modifiedAt"])if(!meta[key])fail(folder+" missing "+key);
 if(!/^scwiki-[a-h][0-9]+$/.test(meta.id)||!/^scwiki-topic-[a-h][0-9]+$/.test(meta.topicId)||!/^[-a-z0-9]+$/.test(meta.slug))fail(folder+" invalid ID");
 if(ids.has(meta.id)||slugs.has(meta.slug))fail("duplicate article");
 ids.add(meta.id);slugs.add(meta.slug);
 const source=bySource.get(meta.provenance.sourceId);
 if(!source||source.sha256!==meta.provenance.sha256||source.path!==meta.provenance.path||meta.provenance.commit!==manifest.commit)fail(folder+" provenance mismatch");
 if(/\p{Script=Han}/u.test(body)||/\p{Script=Han}/u.test(meta.title+" "+meta.summary))fail(folder+" authored English content contains Han copy");
 if(/<\/?[a-z][^>]*>/i.test(body)||/\]\(\s*(?:javascript|data|vbscript):/i.test(body))fail(folder+" unsafe authored Markdown");
 const chunks=body.split(/^## /m).slice(1).map(chunk=>{
  const split=chunk.indexOf("\n"),title=chunk.slice(0,split).trim();
  return {id:anchor(title),title,markdown:"## "+chunk.trim()};
 });
 for(const id of required)if(!chunks.some(s=>s.id===id))fail(folder+" missing section "+id);
 const sectionIds=new Set(chunks.map(s=>s.id));
 if(sectionIds.size!==chunks.length)fail(folder+" duplicate section");
 const refIds=new Set(meta.references.map(r=>r.id));
 for(const ref of meta.references)if(!/^source-[a-f0-9]{16}$/.test(ref.id)||!/^https:\/\//.test(ref.url)||!ref.verification?.scope)fail(folder+" reference schema");
 for(const claim of meta.claims)if(!sectionIds.has(claim.sectionId)||!claim.sourceIds.length||claim.sourceIds.some(id=>!refIds.has(id))||!claim.conditions)fail(folder+" claim mapping "+claim.id);
 for(const match of body.matchAll(/\]\(#ref-([a-z0-9-]+)\)/g))if(!refIds.has(match[1]))fail(folder+" unresolved citation");
 for(const match of body.matchAll(/\$\$([\s\S]+?)\$\$|\$([^\n$]+)\$/g)){
  try{katex.renderToString(match[1]??match[2],{throwOnError:true,trust:false,maxExpand:1000,maxSize:10});}
  catch(error){fail(folder+" invalid math: "+error.message)}
 }
 for(const record of meta.materialCases){
  if(!refIds.has(record.sourceId)||!record.criterion||!record.sample||!record.probe||!record.equilibrium||!record.pressureRegime)fail(folder+" missing material conditions");
  if(record.temperatureKind==="spectroscopic-gap"&&record.tcK!==null)fail(folder+" spectral scale is not a transition Tc");
  if(record.tcK!==null&&(!Number.isFinite(record.tcK)||record.tcK<0))fail(folder+" invalid Tc");
  if(record.recordType!=="experiment"&&record.tcK!==null)fail(folder+" non-experimental Tc cannot enter experimental records");
 }
 const conditions="## Material cases\n\nValues describe individual reports, not a ranking. Unknown means the checked source did not supply the field at this review scope.\n\n"+
 "| Material and sample | Reported temperature | Criterion | Pressure | State | Evidence |\n|---|---|---|---|---|---|\n"+
 meta.materialCases.map(r=>"| "+r.formula+"; "+r.sample+" | "+(r.reportedTemperatureK===null?r.temperatureNote:r.reportedTemperatureK+" K; "+r.temperatureNote)+" | "+r.temperatureKind+"; "+r.criterion+" | "+r.pressureRegime+"; "+(r.pressureGPa?r.pressureGPa.min+" to "+r.pressureGPa.max+" GPa":"unknown GPa")+" | "+r.equilibrium+" | "+r.recordType+"; [source](#ref-"+r.sourceId+") |").join("\n");
 const referenceText=meta.references.map((r,i)=>"### Ref "+r.id+"\n\n[R"+(i+1)+"] "+r.title+" ("+r.year+"). [DOI "+r.doi+"]("+r.url+"). Publication: "+r.publicationStatus+". Check: "+r.verification.scope+". Checked: "+r.verification.checkedAt+". "+(r.verification.note??"")).join("\n");
 // Export v2 preserves reference review notes; invalidate prior Markdown/API cache validators.
 const revision=sha("scwiki-export-v2\n"+JSON.stringify(meta)+"\n"+body).slice(0,20);
 const provenance="## Revision and review\n\nArticle ID: "+meta.id+". Revision: "+revision+". Updated: "+meta.modifiedAt+".\n\nReview scope: "+meta.review.scope+"\n\n"+meta.review.limitations.map(x=>"- "+x).join("\n")+"\n\nSource: ["+meta.provenance.path+"](https://github.com/"+meta.provenance.repository+"/blob/"+meta.provenance.commit+"/"+meta.provenance.path+"), commit "+meta.provenance.commit+", SHA-256 "+meta.provenance.sha256+".";
 const markdown="# "+meta.title+"\n\n"+meta.summary+"\n\n"+body+"\n\n"+conditions+"\n\n## Sources\n\n"+referenceText+"\n\n"+provenance+"\n";
 articles.push({...meta,body,revision,sections:[...chunks,{id:"material-cases",title:"Material cases",markdown:conditions}],markdown,wordCount:body.split(/\s+/).length});
}
if(articles.length!==12)fail("expected exactly 12 pilot articles, got "+articles.length);
for(const a of articles)for(const code of a.relatedCodes)if(!articles.some(other=>other.code===code))fail("unpublished related article "+code);
const revision=sha(articles.map(a=>a.revision).join("\n")).slice(0,20);
const catalogue={schemaVersion:"1.0",revision,articles};
const entries=articles.map(({id,topicId,code,slug,title,summary,aliases,evidenceTypes,editorialStatus,revision,materialCases,references,body})=>({id,topicId,code,slug,title,summary,aliases,evidenceTypes,editorialStatus,revision,materialCases,dois:references.map(r=>r.doi),text:body.replace(/\[[^\]]+\]\([^)]+\)/g,"").replace(/[$#*_\x60]/g,"")}));
for(const[name,value]of[["catalogue.json",catalogue],["search-index.json",{schemaVersion:"1.0",revision,entries}]]){
 const data=JSON.stringify(value,null,2)+"\n",filename=path.join(directory,name);
 if(process.argv.includes("--check")){if(readFileSync(filename,"utf8")!==data)fail(name+" is stale");}
 else writeFileSync(filename,data);
}
console.log(JSON.stringify({articles:articles.length,sourceFiles:manifest.files.length,revision,wordCounts:articles.map(a=>[a.code,a.wordCount])}));
