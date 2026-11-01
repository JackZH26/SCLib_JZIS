// Full-corpus check of the same pure renderer used by Materials (Node >= 22.18).
// Raw source annotations in MathML are excluded from *visible* text checks.
import fs from "node:fs";
import { JSDOM } from "jsdom";
import { renderSourceNotation, sourceNotationLabel } from "../lib/source-notation.ts";

const [input, output] = process.argv.slice(2);
if (!input || !output) throw new Error("Usage: node scripts/audit-materials-display.mjs projected-page.json report.json");
const page = JSON.parse(fs.readFileSync(input, "utf8"));
const dom = new JSDOM("<main></main>");
const holder = dom.window.document.querySelector("main");
const cache = new Map(), failures=[], leaks=[], formulas={};
let fields=0, changed=0;
for (const row of page.items) {
  const values = Object.fromEntries(["formula","sample_label","sample_form","substrate","criterion_raw","method_raw","measurement_context","pressure_raw","paper_title"].map(k=>[k,row.display?.[k] ?? row[k]]));
  values.quantity_raw=row.display?.quantity_raw ?? row.quantity?.raw;
  values.formula_note=row.display?.formula_note;
  row.compositions.forEach((c,i)=>values["composition:"+i]=row.display?.["composition:"+i] ?? c.formula);
  changed+=Object.keys(row.display ?? {}).length;
  for (const [key,value] of Object.entries(values)) {
    if (typeof value !== "string" || !value) continue;
    fields++;
    const math=key==="formula" || key==="quantity_raw" || key.startsWith("composition:");
    const ck=JSON.stringify([value,math]);
    let check=cache.get(ck);
    if (!check) {
      const rendered=renderSourceNotation(value,math);
      holder.innerHTML=rendered.html;
      holder.querySelectorAll(".katex-mathml,annotation").forEach(n=>n.remove());
      const visible=sourceNotationLabel(rendered.html);
      check={unresolved:rendered.unresolved,visible,leak:/\\[A-Za-z]|[\uE000-\uF8FF\uFFFD\x00-\x08\x0b\x0c\x0e-\x1f\x7f]|\$/.test(visible)};
      cache.set(ck,check);
    }
    const item={id:row.id,paper_id:row.paper_id,field:key,text:value};
    if (check.unresolved) failures.push(item);
    if (check.leak) leaks.push({...item,visible:check.visible});
    if (key==="formula" && !check.unresolved) formulas[row.id]=check.visible;
  }
}
const summary={results:page.items.length,fields,unique_inputs:cache.size,source_projected_fields:changed,
  unresolved_fields:failures.length,unresolved_results:new Set(failures.map(x=>x.id)).size,
  unresolved_formulas:failures.filter(x=>x.field==="formula").length,visible_leaks:leaks.length};
fs.writeFileSync(output,JSON.stringify({summary,failures,leaks,formulas},null,2)+"\n");
console.log(JSON.stringify(summary));
