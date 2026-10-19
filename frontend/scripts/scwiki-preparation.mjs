// Preparation conditions never replace a material record's observation conditions.
export function validatePreparation(value, sourceIds) {
 if(value===undefined)return;
 const fail=()=>{throw new Error("SCWiki: invalid material preparation")};
 if(!value||typeof value!=="object"||Array.isArray(value))fail();
 const keys=["method","pressureGPa","temperatureK","releaseRateGPaPerSecond","sourceId","sourceLocation","notes"];
 if(keys.some(k=>!(k in value))||Object.keys(value).some(k=>!keys.includes(k)))fail();
 if(value.method!=="pressure-quench"||!sourceIds.has(value.sourceId))fail();
 const p=value.pressureGPa;
 if(p!==null&&(!p||typeof p!=="object"||Array.isArray(p)||Object.keys(p).sort().join(",")!=="max,min"||!Number.isFinite(p.min)||!Number.isFinite(p.max)||p.min<0||p.max<p.min))fail();
 for(const k of ["temperatureK","releaseRateGPaPerSecond"])if(value[k]!==null&&(!Number.isFinite(value[k])||value[k]<0))fail();
 for(const k of ["sourceLocation","notes"])if(typeof value[k]!=="string"||!value[k].trim()||value[k].length>2000||/[<>|\r\n]/.test(value[k])||/\p{Script=Han}/u.test(value[k]))fail();
}

export function preparationMarkdown(records) {
 const prepared=records.filter(r=>r.preparation);
 if(!prepared.length)return "";
 return "\n\n### Preparation history\n\nThe pressure column above describes measurement conditions. Preparation pressure and temperature below describe an earlier step; they are not measurement pressure or superconducting transition temperature. Unknown release rate is not zero.\n\n"+
 "| Sample | Preparation pressure | Preparation temperature | Pressure release rate | Source and limits |\n|---|---|---|---|---|\n"+
 prepared.map(r=>{const p=r.preparation;return "| "+r.sample+" | "+(p.pressureGPa?p.pressureGPa.min+" to "+p.pressureGPa.max+" GPa":"Unknown")+" | "+(p.temperatureK===null?"Unknown":p.temperatureK+" K")+" | "+(p.releaseRateGPaPerSecond===null?"Unknown":p.releaseRateGPaPerSecond+" GPa/s")+" | "+p.sourceLocation+". "+p.notes+" [source](#ref-"+p.sourceId+") |"}).join("\n");
}
