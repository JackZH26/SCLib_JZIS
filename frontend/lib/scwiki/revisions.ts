import type {Article} from "./types";
export interface RevisionEntry {id:string;revision:string;modifiedAt:string;url:string}
export interface RevisionSnapshot {revision:string;total:number;records:RevisionEntry[]}
export function revisionEntries(articles:Article[]):RevisionEntry[]{
 return articles.map(a=>({id:a.id,revision:a.revision,modifiedAt:a.modifiedAt,url:"/scwiki/"+a.slug}));
}
/** Call only after collecting every page of each consistent manifest snapshot. */
export function diffRevisionSnapshots(previous:RevisionSnapshot,current:RevisionSnapshot){
 const index=(snapshot:RevisionSnapshot)=>{
  if(!/^[a-f0-9]{20}$/.test(snapshot.revision)||!Number.isSafeInteger(snapshot.total)||snapshot.total<0||snapshot.total!==snapshot.records.length)throw new Error("A complete revision snapshot is required.");
  const map=new Map<string,RevisionEntry>();
  for(const record of snapshot.records){
   if(!/^scwiki-(?:[a-h][0-9]+|overview|[i-m]|n(?:[1-9]|10))$/.test(record.id)||!/^[a-f0-9]{20}$/.test(record.revision)||map.has(record.id))throw new Error("Invalid or duplicate revision record.");
   map.set(record.id,record);
  }
  return map;
 };
 const old=index(previous),next=index(current);
 const added=[...next.keys()].filter(id=>!old.has(id)).sort();
 const updated=[...next.keys()].filter(id=>old.has(id)&&old.get(id)!.revision!==next.get(id)!.revision).sort();
 const removed=[...old.keys()].filter(id=>!next.has(id)).sort();
 if(previous.revision===current.revision&&(added.length||updated.length||removed.length))throw new Error("Conflicting records for the same catalogue revision.");
 return {fromRevision:previous.revision,toRevision:current.revision,added,updated,removed};
}
