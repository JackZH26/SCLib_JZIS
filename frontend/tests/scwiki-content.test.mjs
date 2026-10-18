import test from "node:test";
import assert from "node:assert/strict";
import {readFileSync,writeFileSync,mkdtempSync,cpSync,rmSync,mkdirSync} from "node:fs";
import {tmpdir} from "node:os";
import path from "node:path";
import {spawnSync} from "node:child_process";
test("committed SCWiki catalogue and search index match authored sources",()=>{
 const result=spawnSync(process.execPath,["scripts/scwiki-build.mjs","--check"],{encoding:"utf8"});
 assert.equal(result.status,0,result.stdout+result.stderr);
});
test("standalone packaging and E2E copies include content and scripts",()=>{
 const docker=readFileSync("Dockerfile","utf8"),server=readFileSync("tests/e2e/public-site-server.cjs","utf8"),config=readFileSync("next.config.js","utf8");
 assert.match(docker,/COPY --from=builder \/app\/content\/scwiki/);
 assert.match(docker,/COPY --from=builder \/app\/scripts/);
 assert.match(server,/"content", "scripts"/);
 assert.match(config,/outputFileTracingIncludes/);
});

function inventoryFixture(t){
 const cwd=mkdtempSync(path.join(tmpdir(),"scwiki-inventory-"));
 t.after(()=>rmSync(cwd,{recursive:true,force:true}));
 cpSync("content/scwiki",path.join(cwd,"content/scwiki"),{recursive:true});
 const directory=path.join(cwd,"content/scwiki");
 const manifest=JSON.parse(readFileSync(path.join(directory,"source-manifest.json"),"utf8"));
 const save=()=>writeFileSync(path.join(directory,"source-manifest.json"),JSON.stringify(manifest));
 const build=()=>spawnSync(process.execPath,[path.resolve("scripts/scwiki-build.mjs")],{cwd,encoding:"utf8"});
 return {cwd,directory,manifest,save,build};
}
test("publication inventory permits an explicitly approved additional core article",t=>{
 const f=inventoryFixture(t);
 const published=f.manifest.files.filter(x=>x.publicBody).length;
 const source=f.manifest.files.find(x=>x.topicId&&!x.publicBody);
 assert.ok(source,"fixture needs one unpublished approved core topic");
 const code=source.articleId.replace("scwiki-","");
 const meta=JSON.parse(readFileSync(path.join(f.directory,"articles/a1/meta.json"),"utf8"));
 Object.assign(meta,{id:source.articleId,topicId:source.topicId,code:code.toUpperCase(),slug:"synthetic-inventory-fixture",provenance:{...meta.provenance,path:source.path,sha256:source.sha256,sourceId:source.id}});
 mkdirSync(path.join(f.directory,"articles",code),{recursive:true});
 writeFileSync(path.join(f.directory,"articles",code,"meta.json"),JSON.stringify(meta));
 cpSync(path.join(f.directory,"articles/a1/body.md"),path.join(f.directory,"articles",code,"body.md"));
 source.publicBody=true;f.save();
 const result=f.build();assert.equal(result.status,0,result.stderr);
 const catalogue=JSON.parse(readFileSync(path.join(f.directory,"catalogue.json"),"utf8"));
 assert.equal(catalogue.articles.length,published+1);
 assert.ok(catalogue.articles.some(a=>a.id===source.articleId));
});
test("publication inventory rejects missing, unapproved and mismatched articles",async t=>{
 for(const scenario of ["missing","unapproved","identity-mismatch"]){
  await t.test(scenario,t=>{
   const f=inventoryFixture(t);
   if(scenario==="missing")rmSync(path.join(f.directory,"articles/a1"),{recursive:true});
   if(scenario==="unapproved"){f.manifest.files.find(x=>x.articleId==="scwiki-a1").publicBody=false;f.save();}
   if(scenario==="identity-mismatch"){
    const filename=path.join(f.directory,"articles/a1/meta.json"),meta=JSON.parse(readFileSync(filename,"utf8"));
    meta.topicId="scwiki-topic-a2";writeFileSync(filename,JSON.stringify(meta));
   }
   const result=f.build();assert.notEqual(result.status,0);assert.match(result.stderr,/publication inventory/);
  });
 }
});

test("known source-identity corrections block reintroducing an unrelated DOI",t=>{
 const f=inventoryFixture(t);
 const filename=path.join(f.directory,"articles/b12/meta.json");
 const meta=JSON.parse(readFileSync(filename,"utf8"));
 const source=meta.references.find(r=>r.doi==="10.1038/nature00898");
 assert.ok(source);
 source.doi="10.1038/nature00992";
 writeFileSync(filename,JSON.stringify(meta));
 const result=f.build();
 assert.notEqual(result.status,0);
 assert.match(result.stderr,/known incorrect DOI 10\.1038\/nature00992/);
});

test("d-wave migration rejects the unrelated Brillouin paper as its ARPES reference",t=>{
 const f=inventoryFixture(t),filename=path.join(f.directory,"articles/c3/meta.json");
 const meta=JSON.parse(readFileSync(filename,"utf8"));
 meta.references.find(r=>r.doi==="10.1103/PhysRevLett.70.1553").doi="10.1103/PhysRevLett.75.4234";
 writeFileSync(filename,JSON.stringify(meta));
 const result=f.build();assert.notEqual(result.status,0);
 assert.match(result.stderr,/known incorrect DOI 10\.1103\/PhysRevLett\.75\.4234/);
});

test("non-transition temperatures cannot become searchable transition records",async t=>{
 for(const kind of ["normal-state","transient-response","spectroscopic-gap","measurement","unassigned"]){
  await t.test(kind,t=>{
   const f=inventoryFixture(t),filename=path.join(f.directory,"articles/a1/meta.json");
   const meta=JSON.parse(readFileSync(filename,"utf8"));
   Object.assign(meta.materialCases[0],{temperatureKind:kind,tcK:100});
   writeFileSync(filename,JSON.stringify(meta));
   const result=f.build();assert.notEqual(result.status,0);
   assert.match(result.stderr,/non-transition temperature is not a transition Tc/);
  });
 }
});

test("DOI fields distinguish a canonical historical link from malformed identifiers",async t=>{
 for(const value of [null,"", "not-a-doi", 123]){
  await t.test(String(value),t=>{
   const f=inventoryFixture(t),filename=path.join(f.directory,"articles/a1/meta.json");
   const meta=JSON.parse(readFileSync(filename,"utf8"));meta.references[0].doi=value;
   writeFileSync(filename,JSON.stringify(meta));const result=f.build();
   if(value===null){assert.equal(result.status,0,result.stderr);const cat=JSON.parse(readFileSync(path.join(f.directory,"catalogue.json"),"utf8"));assert.ok(cat.articles.find(a=>a.code==="A1").markdown.includes("[Source publication]"));}
   else {assert.notEqual(result.status,0);assert.match(result.stderr,/reference schema/);}
  });
 }
});

test("QPI bibliography rejects the unrelated biology DOI but preserves the distinct vortex paper",t=>{
 const f=inventoryFixture(t),filename=path.join(f.directory,"articles/a10/meta.json");
 const meta=JSON.parse(readFileSync(filename,"utf8"));
 assert.ok(meta.references.some(r=>r.doi==="10.1126/science.1066974"));
 let result=f.build();assert.equal(result.status,0,result.stderr);
 meta.references.find(r=>r.doi==="10.1038/nature01496").doi="10.1038/nature02269";
 writeFileSync(filename,JSON.stringify(meta));result=f.build();
 assert.notEqual(result.status,0);assert.match(result.stderr,/known incorrect DOI 10\.1038\/nature02269/);
});

test("wrong DOI correction remains enforced when the replacement is a historical URL",t=>{
 const f=inventoryFixture(t),filename=path.join(f.directory,"articles/b2/meta.json");
 const meta=JSON.parse(readFileSync(filename,"utf8")),historical=meta.references.find(r=>r.doi===null);
 assert.ok(historical.url.includes("e_007_06_0996.pdf"));
 historical.doi="10.1007/BF02745500";writeFileSync(filename,JSON.stringify(meta));
 const result=f.build();assert.notEqual(result.status,0);
 assert.match(result.stderr,/known incorrect DOI 10\.1007\/BF02745500/);
});

test("known Kuroki erratum accompanies the original in newly authored and existing pages",t=>{
 for(const folder of ["b3","c2","c4"]){
  const f=inventoryFixture(t),filename=path.join(f.directory,"articles",folder,"meta.json");
  const meta=JSON.parse(readFileSync(filename,"utf8"));
  assert.ok(meta.references.some(r=>r.doi==="10.1103/PhysRevLett.101.087004"));
  meta.references=meta.references.filter(r=>r.doi!=="10.1103/PhysRevLett.102.109902");
  writeFileSync(filename,JSON.stringify(meta));const result=f.build();
  assert.notEqual(result.status,0);assert.match(result.stderr,/missing required erratum 10\.1103\/PhysRevLett\.102\.109902/);
 }
});

test("Leggett phase review retains the correction to its historical comparison",t=>{
 const f=inventoryFixture(t),filename=path.join(f.directory,"articles/c5/meta.json");
 const meta=JSON.parse(readFileSync(filename,"utf8"));
 meta.references=meta.references.filter(r=>r.doi!=="10.1103/RevModPhys.48.357");
 writeFileSync(filename,JSON.stringify(meta));const result=f.build();
 assert.notEqual(result.status,0);assert.match(result.stderr,/missing required erratum 10\.1103\/RevModPhys\.48\.357/);
});

test("uranium discovery references reject both inherited incorrect DOIs",t=>{
 for(const [correct,incorrect] of [["10.1038/35020500","10.1038/35050500"],["10.1038/35098048","10.1038/35065045"]]){
  const f=inventoryFixture(t),filename=path.join(f.directory,"articles/b4/meta.json"),meta=JSON.parse(readFileSync(filename,"utf8"));
  meta.references.find(r=>r.doi===correct).doi=incorrect;writeFileSync(filename,JSON.stringify(meta));
  const result=f.build();assert.notEqual(result.status,0);assert.ok(result.stderr.includes("known incorrect DOI "+incorrect));
 }
});

test("Yin material-label erratum remains attached to its original paper",t=>{
 const f=inventoryFixture(t),filename=path.join(f.directory,"articles/b10/meta.json");
 const meta=JSON.parse(readFileSync(filename,"utf8"));
 meta.references=meta.references.filter(r=>r.doi!=="10.1038/nmat3152");
 writeFileSync(filename,JSON.stringify(meta));const result=f.build();
 assert.notEqual(result.status,0);assert.match(result.stderr,/missing required erratum 10\.1038\/nmat3152/);
});


test("material generation rejects undeclared kinds and invalid observed temperatures",async t=>{
 for(const [name,change,error] of [["unknown kind",{temperatureKind:"spectroscopic",tcK:null},/invalid temperature kind/],["negative observation",{reportedTemperatureK:-1},/invalid reported temperature/],["text observation",{reportedTemperatureK:"300 mK"},/invalid reported temperature/]]){
  await t.test(name,t=>{
   const f=inventoryFixture(t),filename=path.join(f.directory,"articles/a1/meta.json");
   const meta=JSON.parse(readFileSync(filename,"utf8"));Object.assign(meta.materialCases[0],change);
   writeFileSync(filename,JSON.stringify(meta));const result=f.build();
   assert.notEqual(result.status,0);assert.match(result.stderr,error);
  });
 }
});

test("noncentrosymmetric classification cannot drop the Frigeri SOC erratum",t=>{
 const f=inventoryFixture(t),filename=path.join(f.directory,"articles/c9/meta.json");
 const meta=JSON.parse(readFileSync(filename,"utf8"));
 meta.references=meta.references.filter(r=>r.doi!=="10.1103/PhysRevLett.93.099903");
 writeFileSync(filename,JSON.stringify(meta));const result=f.build();
 assert.notEqual(result.status,0);assert.match(result.stderr,/missing required erratum 10\.1103\/PhysRevLett\.93\.099903/);
});
