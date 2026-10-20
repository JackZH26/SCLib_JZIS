#!/usr/bin/env node
// Data-only publisher. No Git, build, site restart or database access.
import {readFileSync,writeFileSync,mkdirSync,renameSync,unlinkSync,rmdirSync,existsSync,openSync,fsyncSync,closeSync} from "node:fs";
import path from "node:path";
import {createHash} from "node:crypto";
import {fileURLToPath} from "node:url";
import {validateResearch,assertAppendOnly} from "./scwiki-research-model.mjs";
const digest=value=>createHash("sha256").update(JSON.stringify(value)).digest("hex");
export function publishResearch({store,candidate,seed,today}) {
 store=path.resolve(store);mkdirSync(path.dirname(store),{recursive:true});
 const lock=store+".lock";
 // Never reclaim by age: a live worker or interrupted publication requires inspection.
 mkdirSync(lock);
 try {
  writeFileSync(path.join(lock,"owner.json"),JSON.stringify({pid:process.pid,startedAt:new Date().toISOString(),candidateDigest:digest(candidate)}),{flag:"wx",mode:0o600});
  const previous=validateResearch(JSON.parse(readFileSync(existsSync(store)?store:seed,"utf8")),today);
  const key=candidate.kind==="notice"?"notices":candidate.kind==="issue"?"issues":null;
  if(!key)throw new Error("Candidate kind must be issue or notice.");
  const record=candidate.record,old=previous[key].find(x=>x.id===record.id);
  if(old) {
   if(JSON.stringify(old)!==JSON.stringify(record))throw new Error("Existing ID differs. Published records cannot be replaced.");
   return {changed:false,id:record.id,revision:digest(previous)};
  }
  const next=validateResearch({...previous,[key]:[...previous[key],record]},today);
  assertAppendOnly(previous,next);
  const backup=store+".history";mkdirSync(backup,{recursive:true});
  const previousFile=path.join(backup,digest(previous)+".json");
  if(!existsSync(previousFile))writeFileSync(previousFile,JSON.stringify(previous,null,2)+"\n",{flag:"wx",mode:0o644});
  const temp=store+"."+process.pid+".tmp";
  try {
   const fd=openSync(temp,"wx",0o644);
   try {writeFileSync(fd,JSON.stringify(next,null,2)+"\n");fsyncSync(fd);}finally{closeSync(fd);}
   // The only visible mutation: readers see the complete old or complete new collection.
   renameSync(temp,store);
   const dir=openSync(path.dirname(store),"r");try{fsyncSync(dir);}finally{closeSync(dir);}
  } finally {if(existsSync(temp))unlinkSync(temp);}
  return {changed:true,id:record.id,revision:digest(next),previousRevision:digest(previous)};
 } finally {unlinkSync(path.join(lock,"owner.json"));rmdirSync(lock);}
}
if(process.argv[1]&&path.resolve(process.argv[1])===fileURLToPath(import.meta.url)) {
 try {
  const args=Object.fromEntries(process.argv.slice(2).reduce((a,x,i,all)=>i%2?a:[...a,[x,all[i+1]]],[]));
  if(!args["--store"]||!args["--candidate"]||!args["--seed"])throw new Error("Usage: --store FILE --candidate FILE --seed FILE");
  const candidate=JSON.parse(readFileSync(args["--candidate"],"utf8"));
  console.log(JSON.stringify(publishResearch({store:args["--store"],candidate,seed:args["--seed"]})));
 }catch(error){console.error(error.message);process.exitCode=1;}
}
