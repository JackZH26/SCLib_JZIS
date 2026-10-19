import test from "node:test";
import assert from "node:assert/strict";
import {validateReferenceIdentities} from "../scripts/scwiki-reference-identity.mjs";
const ref={id:"source-21442c6eb33d9b94",doi:null,title:"Interaction between Electrons and Lattice Vibrations in a Normal Metal",year:1958,url:"https://www.jetp.ras.ru/cgi-bin/dn/e_007_06_0996.pdf"};
const article=(code,r)=>({code,references:[r]});
test("a reused non-DOI URL cannot merge Migdal and Larkin-Ovchinnikov papers",()=>{
 assert.throws(()=>validateReferenceIdentities([article("B2",ref),article("C8",{...ref,title:"Nonuniform state of superconductors"})]),/conflicting publication identities/);
});
test("source identity permits title punctuation and article-specific review scopes",()=>{
 assert.doesNotThrow(()=>validateReferenceIdentities([article("B2",ref),article("X",{...ref,title:ref.title.toUpperCase()+".",verification:{scope:"abstract-only"}})]));
});
test("shared source IDs cannot change DOI, canonical non-DOI URL or year",()=>{
 for(const patch of [{doi:"10.1103/PhysRev.135.A550"},{url:"https://example.org/another-paper"},{year:1965}]){
  assert.throws(()=>validateReferenceIdentities([article("B2",ref),article("C8",{...ref,...patch})]),/conflicting publication identities/);
 }
});
test("one DOI has one source identity and each article cites each ID once",()=>{
 const a={...ref,doi:"10.1103/PhysRev.135.A550"};
 assert.throws(()=>validateReferenceIdentities([article("A",a),article("B",{...a,id:"source-0000000000000000",doi:a.doi.toUpperCase()})]),/multiple source IDs/);
 assert.throws(()=>validateReferenceIdentities([{code:"A",references:[a,a]}]),/duplicate reference ID/);
});
