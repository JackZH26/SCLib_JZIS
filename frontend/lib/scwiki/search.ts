import type { SearchEntry, SearchFilters } from "./types";
const subscripts: Record<string, string> = { "₀":"0","₁":"1","₂":"2","₃":"3","₄":"4","₅":"5","₆":"6","₇":"7","₈":"8","₉":"9","−":"-","±":" plus minus " };
export function normalizeSearch(value: string): string {
  return value.replace(/[₀-₉−±]/g,x=>subscripts[x]||x).normalize("NFKC").toLowerCase().replace(/[^\p{L}\p{N}]+/gu," ").trim();
}
export function searchArticles(entries: SearchEntry[], query: string, filters: SearchFilters = {}): SearchEntry[] {
  const normalizedQuery=normalizeSearch(query.slice(0,200));
  const tokens = normalizedQuery.split(/\s+/).filter(Boolean);
  const phraseMatches=(text:string,term:string)=>!!term && (" "+text+" ").includes(" "+term+" ");
  // Recognized material names bind conditions to that material, even in a multi-material topic.
  // Aliases are explicitly curated; do not infer stoichiometric equivalence from a formula.
  const materialTerms=[...new Set(entries.flatMap(e=>e.materialCases.flatMap(r=>[r.formula,...(r.aliases??[])]).map(normalizeSearch)))];
  const selectedMaterials=materialTerms.filter(term=>(term.length>2||term===normalizedQuery)&&phraseMatches(normalizedQuery,term));
  return entries.filter(entry => {
    const haystack = normalizeSearch([entry.title,...entry.aliases,...entry.dois,entry.text,...entry.materialCases.flatMap(x=>[x.formula,...(x.aliases??[])])].join(" "));
    const words=new Set(haystack.split(" "));
    if(!tokens.every(token=>token.length<=2?words.has(token):haystack.includes(token))) return false;
    if(filters.evidence && !entry.evidenceTypes.some(type=>type===filters.evidence)) return false;
    const conditioned=filters.pressure || filters.equilibrium || filters.criterion || filters.tcMin!==undefined;
    if(!conditioned) return true;
    // All requested conditions must hold for ONE evidence record, never across samples.
    return entry.materialCases.some(record =>
      selectedMaterials.every(term=>[record.formula,...(record.aliases??[])].some(name=>phraseMatches(normalizeSearch(name),term))) &&
      (!filters.evidence || record.recordType===filters.evidence) &&
      (!filters.pressure || record.pressureRegime===filters.pressure) &&
      (!filters.equilibrium || record.equilibrium===filters.equilibrium) &&
      (!filters.criterion || record.criterion===filters.criterion) &&
      (filters.tcMin===undefined || (record.recordType==="experiment" && record.tcK!==null && record.tcK>=filters.tcMin)));
  }).sort((a,b)=>{
    const q=normalizeSearch(query);
    const score=(x:SearchEntry)=>normalizeSearch(x.title).includes(q)?0:1;
    return score(a)-score(b)||a.code.localeCompare(b.code,"en",{numeric:true});
  });
}
