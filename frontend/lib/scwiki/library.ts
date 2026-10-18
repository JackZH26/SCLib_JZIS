import {createHash} from "node:crypto";
import data from "@/content/scwiki/research-library.json";
import type {EvidenceType,SearchEntry} from "./types";
const digest=(value:unknown)=>createHash("sha256").update(JSON.stringify(value)).digest("hex").slice(0,20);
export const libraryNotes=data.notes.map(note=>({...note,revision:digest(note)}));
export const libraryRevision=digest(libraryNotes);
export function libraryNote(id:string){return libraryNotes.find(note=>note.id===id);}
export function librarySearchEntries():SearchEntry[]{return libraryNotes.map(note=>({
 id:note.id,topicId:"research-"+note.id,code:"Research note",slug:"library/"+note.id,title:note.title,summary:note.summary,
 aliases:note.aliases,evidenceTypes:note.evidenceTypes as EvidenceType[],editorialStatus:"scoped-check",revision:note.revision,materialCases:[],
 dois:note.sources.flatMap(s=>s.doi?[s.doi]:[]),text:[note.summary,...note.sections.map(s=>s.markdown),...note.sources.map(s=>s.title),...note.review.limitations].join("\n")
}));}
export function discoveryIndex(index:{revision:string;entries:SearchEntry[]}){return {revision:digest([index.revision,libraryRevision]),articleRevision:index.revision,libraryRevision,entries:[...index.entries,...librarySearchEntries()]};}
export function libraryMarkdown(note:typeof libraryNotes[number]){
 return "# "+note.title+"\n\n"+note.summary+"\n\n## Review scope\n\n"+note.review.scope+"\n\n"+note.review.limitations.map(x=>"- "+x).join("\n")+
 note.sections.map(s=>"\n\n## "+s.title+"\n\n"+s.markdown+"\n\nEvidence: "+s.evidenceType+". Source relationship: "+s.sourceRelationship+". Sources: "+s.sourceIds.join(", ")+".").join("")+
 "\n\n## Sources\n\n"+note.sources.map(s=>s.id+": "+s.authors+". ["+s.title+"]("+s.url+"). "+s.publicationStatus+"; "+s.dateLabel+" "+s.date+"; "+s.version+". "+s.scope+(s.licenseUrl?" Source license: ["+s.licenseLabel+"]("+s.licenseUrl+"). Editorial wording and organization changed.":"")).join("\n\n")+
 "\n\n## Editorial corrections\n\n"+note.corrections.map(c=>"- "+c.issue+": "+c.resolution).join("\n")+
 "\n\n## Provenance\n\n"+note.provenance.map(p=>p.path+"; commit "+p.commit+"; SHA-256 "+p.sha256+"; "+p.disposition).join("\n\n")+
 "\n\n"+note.rights+"\n\nNote ID: "+note.id+". Revision: "+note.revision+".\n";
}
