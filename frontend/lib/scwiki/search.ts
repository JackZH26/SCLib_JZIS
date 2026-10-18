import type { SearchEntry, SearchFilters } from "./types";
const subscripts: Record<string, string> = { "₀":"0","₁":"1","₂":"2","₃":"3","₄":"4","₅":"5","₆":"6","₇":"7","₈":"8","₉":"9","−":"-","±":" plus minus " };
export function normalizeSearch(value: string): string {
  return value.replace(/[₀-₉−±]/g,x=>subscripts[x]||x).normalize("NFKC").toLowerCase().replace(/[^\p{L}\p{N}]+/gu," ").trim();
}
export function searchArticles(entries: SearchEntry[], query: string, filters: SearchFilters = {}): SearchEntry[] {
  const normalizedQuery=normalizeSearch(query.slice(0,200));
  const doiQuery=query.trim().replace(/^https?:\/\/(?:dx\.)?doi\.org\//i,"").replace(/^doi:\s*/i,"").toLowerCase();
  const isDoi=/^10\.\d{4,9}\/\S+$/i.test(doiQuery);
  const tokens = normalizedQuery.split(/\s+/).filter(Boolean);
  const phraseMatches=(text:string,term:string)=>!!term && (" "+text+" ").includes(" "+term+" ");
  // Recognized material names bind conditions to that material, even in a multi-material topic.
  // Aliases are explicitly curated; do not infer stoichiometric equivalence from a formula.
  const materialTerms=[...new Set(entries.flatMap(e=>e.materialCases.flatMap(r=>[r.formula,...(r.aliases??[])]).map(normalizeSearch)))];
  const selectedMaterials=materialTerms.filter(term=>(term.length>2||term===normalizedQuery)&&phraseMatches(normalizedQuery,term));
  return entries.filter(entry => {
    const haystack = normalizeSearch([entry.title,...entry.aliases,...entry.dois,entry.text,...entry.materialCases.flatMap(x=>[x.formula,...(x.aliases??[])])].join(" "));
    const words=new Set(haystack.split(" "));
    // Han keywords do not use spaces as word boundaries; keep short Latin
    // tokens exact so element symbols do not match arbitrary prose fragments.
    if(isDoi ? !entry.dois.some(doi=>doi.toLowerCase()===doiQuery) : !tokens.every(token=>token.length<=2&&!/^\p{Script=Han}+$/u.test(token)?words.has(token):haystack.includes(token))) return false;
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
    // A curated topic alias is stronger evidence of relevance than an incidental
    // mention in another article's body. Ranking never changes record filters.
    const score=(x:SearchEntry)=>{
      if(!normalizedQuery||isDoi)return 0;
      const title=normalizeSearch(x.title),aliases=x.aliases.map(normalizeSearch);
      if(title===normalizedQuery)return 0;
      if(aliases.includes(normalizedQuery))return 1;
      if(phraseMatches(title,normalizedQuery))return 2;
      if(aliases.some(alias=>phraseMatches(alias,normalizedQuery)))return 3;
      if(phraseMatches(normalizeSearch(x.summary),normalizedQuery))return 4;
      return 5;
    };
    return score(a)-score(b)||a.code.localeCompare(b.code,"en",{numeric:true});
  });
}
