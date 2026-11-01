"use client";

import { useCallback, useEffect, useId, useMemo, useRef, useState } from "react";
import Link from "@/components/AppLink";
import { FormulaDisplay } from "@/components/FormulaDisplay";
import { LatexText } from "@/components/LatexText";
import { getMaterialsTimeline } from "@/lib/api";
import { tcCriteria } from "@/lib/materials-vnext";
import { tcDisplayExclusion } from "@/lib/tc-display-policy";
import { timelineDate, timelineFamilies, timelinePressure, timelineTc, timelineValue, type NerTimelineData, type NerTimelinePoint } from "@/lib/materials-timeline";
import "./materials-timeline.css";

type Placed = { point: NerTimelinePoint; x: number; y: number };
const format = (value: number) => value.toLocaleString("en-US");

function drawMark(ctx: CanvasRenderingContext2D, shape: string, x: number, y: number, r=3.2) {
  ctx.beginPath();
  if(shape==="square")ctx.rect(x-r*.85,y-r*.85,r*1.7,r*1.7);
  else if(shape==="diamond"){ctx.moveTo(x,y-r*1.35);ctx.lineTo(x+r*.9,y);ctx.lineTo(x,y+r*1.35);ctx.lineTo(x-r*.9,y);ctx.closePath();}
  else if(shape==="triangle"){ctx.moveTo(x,y-r*1.3);ctx.lineTo(x+r*1.12,y+r*.7);ctx.lineTo(x-r*1.12,y+r*.7);ctx.closePath();}
  else if(shape==="star"){for(let i=0;i<10;i++){const a=-Math.PI/2+i*Math.PI/5,rr=i%2?r*.55:r*1.3;const xx=x+Math.cos(a)*rr,yy=y+Math.sin(a)*rr;i?ctx.lineTo(xx,yy):ctx.moveTo(xx,yy);}ctx.closePath();}
  else if(shape==="cross"||shape==="wye"){const angles=shape==="cross"?[0,Math.PI/2,Math.PI,Math.PI*1.5]:[-Math.PI/2,Math.PI/6,Math.PI*5/6];for(const a of angles){ctx.moveTo(x,y);ctx.lineTo(x+Math.cos(a)*r*1.2,y+Math.sin(a)*r*1.2);}ctx.lineWidth=1.8;ctx.stroke();return;}
  else ctx.arc(x,y,r,0,Math.PI*2);
  if(shape==="open"){ctx.lineWidth=1;ctx.stroke();}else ctx.fill();
}

export function MaterialsTcTimeline({ compact=false, initialData }: { compact?: boolean; initialData?: NerTimelineData }) {
  const root=useRef<HTMLDivElement>(null), canvas=useRef<HTMLCanvasElement>(null), stage=useRef<HTMLDivElement>(null);
  const [data,setData]=useState<NerTimelineData|null>(initialData??null), [error,setError]=useState(false), [retry,setRetry]=useState(0);
  const [width,setWidth]=useState(680), [mode,setMode]=useState("all"), [year,setYear]=useState(2019), [range,setRange]=useState("300");
  const [family,setFamily]=useState<string|null>(null), [selected,setSelected]=useState<string|null>(null), [pinned,setPinned]=useState(false);
  const [legendOpen,setLegendOpen]=useState(!compact);
  const chartId=useId();
  const dismiss=useCallback(()=>{setPinned(false);setSelected(null);},[]);
  useEffect(()=>{
    if(initialData)return;
    const controller=new AbortController();let observer:IntersectionObserver|undefined;
    const load=()=>{setError(false);getMaterialsTimeline(compact?2000:20000,controller.signal).then(setData).catch(()=>{if(!controller.signal.aborted){setData(null);setError(true);}});};
    if(compact && typeof IntersectionObserver!=="undefined" && root.current){observer=new IntersectionObserver(entries=>{if(entries.some(e=>e.isIntersecting)){observer?.disconnect();load();}},{rootMargin:"300px"});observer.observe(root.current);}
    else load();
    return()=>{controller.abort();observer?.disconnect();};
  },[compact,initialData,retry]);
  useEffect(()=>{
    if(!stage.current)return;
    const measure=()=>setWidth(stage.current?.clientWidth || 680);measure();
    if(typeof ResizeObserver==="undefined")return;
    const observer=new ResizeObserver(measure);observer.observe(stage.current);return()=>observer.disconnect();
  },[data]);
  useEffect(()=>{
    const key=(event:KeyboardEvent)=>{if(event.key==="Escape")dismiss();};
    const outside=(event:PointerEvent)=>{if(root.current && !root.current.contains(event.target as Node))dismiss();};
    document.addEventListener("keydown",key);document.addEventListener("pointerdown",outside);
    return()=>{document.removeEventListener("keydown",key);document.removeEventListener("pointerdown",outside);};
  },[dismiss]);
  const height=compact?355:470, left=60, right=16, top=24, bottom=55;
  const dated=useMemo(()=>data?.points.filter(p=>!tcDisplayExclusion(p)&&Number.isFinite(timelineDate(p)))??[],[data]);
  const years=useMemo(()=>Array.from(new Set(dated.map(p=>new Date(timelineDate(p)).getUTCFullYear()))).sort((a,b)=>a-b),[dated]);
  const activeYear=years.includes(year)?year:(years.at(-1)??year);
  const view=useMemo(()=>dated.filter(p=>(family===null||p.family===family)&&(mode==="all"||new Date(timelineDate(p)).getUTCFullYear()===activeYear)),[dated,family,mode,activeYear]);
  const ymax=Number(range);
  const start=Date.UTC(mode==="month"?activeYear:(years[0]??1994),0,1);
  const end=Date.UTC(mode==="month"?activeYear+1:(years.at(-1)??2026)+1,0,1);
  const scaleX=(date:number)=>left+5+(date-start)/(end-start)*Math.max(1,width-left-right-10);
  const scaleY=(value:number)=>height-bottom-5-value/ymax*(height-top-bottom-10);
  const placed=useMemo(()=>view.filter(p=>timelineValue(p)<=ymax && timelineValue(p)>=0).map(point=>({point,x:scaleX(timelineDate(point)),y:scaleY(timelineValue(point))})),[view,width,ymax,start,end,height]);
  const current=placed.find(p=>p.point.id===selected);
  const grid=useMemo(()=>{const map=new Map<string,Placed[]>();for(const p of placed){const key=Math.floor(p.x/20)+":"+Math.floor(p.y/20);map.set(key,[...(map.get(key)??[]),p]);}return map;},[placed]);
  const near=(x:number,y:number,radius=20)=>{let best:Placed|undefined,distance=radius;const col=Math.floor(x/20),row=Math.floor(y/20);for(let i=-2;i<=2;i++)for(let j=-2;j<=2;j++)for(const p of grid.get((col+i)+":"+(row+j))??[]){const d=Math.hypot(p.x-x,p.y-y);if(d<distance){distance=d;best=p;}}return best;};
  const overlaps=current?placed.filter(p=>Math.abs(p.x-current.x)<1&&Math.abs(p.y-current.y)<1):[];
  useEffect(()=>{
    if(!canvas.current)return;
    const ctx=canvas.current.getContext("2d");if(!ctx)return;
    const ratio=Math.min(window.devicePixelRatio||1,2);canvas.current.width=width*ratio;canvas.current.height=height*ratio;
    ctx.setTransform(ratio,0,0,ratio,0,0);ctx.clearRect(0,0,width,height);
    ctx.save();ctx.beginPath();ctx.rect(left,top,width-left-right,height-top-bottom);ctx.clip();
    ctx.globalAlpha=.77;
    for(const {point:p,x,y} of placed){
      const f=timelineFamilies[p.family]??timelineFamilies.unclassified;ctx.fillStyle=f.color;ctx.strokeStyle=f.color;
      if(p.value_relation==="interval"){
        const upper=scaleY(Math.min(p.value_upper_kelvin!,ymax));ctx.lineWidth=1.2;ctx.beginPath();ctx.moveTo(x,y);ctx.lineTo(x,upper);ctx.moveTo(x-3,y);ctx.lineTo(x+3,y);ctx.moveTo(x-3,upper);ctx.lineTo(x+3,upper);ctx.stroke();
      }else{
        drawMark(ctx,f.shape,x,y);
        if(p.value_relation!=="exact"){const direction=["gt","ge"].includes(p.value_relation)?-1:1;ctx.lineWidth=1;ctx.beginPath();ctx.moveTo(x,y);ctx.lineTo(x,y+direction*11);ctx.moveTo(x-3,y+direction*8);ctx.lineTo(x,y+direction*11);ctx.lineTo(x+3,y+direction*8);ctx.stroke();}
      }
    }
    ctx.restore();
  },[placed,width,height,ymax]);
  const ticks=Array.from({length:7},(_,i)=>ymax*i/6);
  const xticks=mode==="month"?Array.from({length:12},(_,m)=>Date.UTC(activeYear,m,1)).filter((_,i)=>width>600||i%3===0):
    years.filter(y=>y%(width<500?10:5)===0).map(y=>Date.UTC(y,0,1));
  const controlsChanged=()=>dismiss();
  const read=()=>{if(!current&&placed[0])setSelected(placed[0].point.id);setPinned(true);};
  const familyNames=Object.keys(timelineFamilies).filter(key=>(data?.families[key]??0)>0);
  return <div ref={root} className={"ner-timeline"+(compact?" ner-timeline-compact":"")}>
    {!data ? <div className="ner-timeline-loading" role={error?"alert":"status"}>{error?<><p>TcTimeline could not be loaded.</p><button type="button" className="site-text-link" onClick={()=>setRetry(r=>r+1)}>Try again</button></>:<p>Loading reported Tc data…</p>}</div> : <>
      <div className="ner-timeline-toolbar">
        <p><strong>{format(data.total_results)}</strong> reported results · {format(data.total_papers)} papers</p>
        <div className="ner-timeline-controls">
          <label>Time view<select value={mode} onChange={e=>{setMode(e.target.value);controlsChanged();}}><option value="all">All years</option><option value="month">By month</option></select></label>
          {mode==="month"&&<label>Year<select value={activeYear} onChange={e=>{setYear(Number(e.target.value));controlsChanged();}}>{years.map(y=><option key={y} value={y}>{y}</option>)}</select></label>}
          <label>Tc range<select value={range} onChange={e=>{setRange(e.target.value);controlsChanged();}}><option value="300">0–300 K</option><option value="50">0–50 K</option></select></label>
        </div>
      </div>
      <div ref={stage} className="ner-timeline-stage" onPointerMove={event=>{if(pinned||event.pointerType==="touch")return;const r=event.currentTarget.getBoundingClientRect();setSelected(near(event.clientX-r.left,event.clientY-r.top)?.point.id??null);}} onPointerLeave={()=>{if(!pinned)setSelected(null);}}
        onClick={event=>{const r=event.currentTarget.getBoundingClientRect(),p=near(event.clientX-r.left,event.clientY-r.top,28);if(p){setSelected(p.point.id);setPinned(true);}else dismiss();}}>
        <canvas ref={canvas} style={{height}} role="img" tabIndex={0} aria-label="Two-dimensional reported Tc versus paper submission date. Use left and right arrows to select reports; Enter pins details; Escape closes details."
          onKeyDown={event=>{if(["ArrowLeft","ArrowRight"].includes(event.key)){event.preventDefault();const i=placed.findIndex(p=>p.point.id===selected),next=(i+(event.key==="ArrowRight"?1:-1)+placed.length)%placed.length;setSelected(placed[next]?.point.id??null);setPinned(true);}if(event.key==="Enter"){event.preventDefault();read();}}} />
        <svg className="ner-timeline-axes" width={width} height={height} viewBox={`0 0 ${width} ${height}`} aria-hidden="true">
          {ticks.map(v=><g key={v}><line x1={left} x2={width-right} y1={scaleY(v)} y2={scaleY(v)} className="ner-timeline-grid"/><text x={left-10} y={scaleY(v)+4} textAnchor="end">{Number(v.toFixed(1)).toLocaleString("en-US")}</text></g>)}
          <text x={left} y={13}>Tc (K)</text>
          <line x1={left} x2={width-right} y1={height-bottom} y2={height-bottom} className="ner-timeline-axis"/>
          {xticks.map(v=><g key={v}><line x1={scaleX(v)} x2={scaleX(v)} y1={height-bottom} y2={height-bottom+5} className="ner-timeline-axis"/><text x={scaleX(v)} y={height-bottom+22} textAnchor="middle">{mode==="month"?new Intl.DateTimeFormat("en-US",{month:"short",timeZone:"UTC"}).format(v):new Date(v).getUTCFullYear()}</text></g>)}
          <text x={(left+width-right)/2} y={height-7} textAnchor="middle">{mode==="month"?"Paper submission month · "+activeYear:"Paper submission date"}</text>
          {current&&<circle cx={current.x} cy={current.y} r={7} fill="none" stroke={(timelineFamilies[current.point.family]??timelineFamilies.unclassified).color} strokeWidth={1.5}/>}
        </svg>
        {current&&<div className="ner-timeline-tip" role={pinned?"dialog":"tooltip"} aria-label="Reported Tc details" style={{left:Math.max(8,Math.min(width-258,current.x+(current.x>width*.6?-255:15))),top:Math.max(28,Math.min(height-205,current.y-40)),borderTopColor:(timelineFamilies[current.point.family]??timelineFamilies.unclassified).color}}
          onPointerMove={e=>e.stopPropagation()} onClick={e=>e.stopPropagation()}>
          <div className="ner-timeline-tip-head"><span>{(timelineFamilies[current.point.family]??timelineFamilies.unclassified).label}</span><span>{pinned?"Pinned":"Click to pin"}</span>{pinned&&<button type="button" aria-label="Close pinned report" onClick={dismiss}>×</button>}</div>
          <div className="ner-timeline-tip-main"><strong>{/[$\\_^\uE000-\uF8FF\uFFFD]/.test(current.point.formula)?<LatexText math>{current.point.formula}</LatexText>:<FormulaDisplay formula={current.point.formula}/>}</strong><span>{timelineTc(current.point)}</span></div>
          <p>{new Intl.DateTimeFormat("en-GB",{month:"short",year:"numeric",...(current.point.date_precision==="day"?{day:"numeric" as const}:{}),timeZone:"UTC"}).format(timelineDate(current.point))} · {timelinePressure(current.point)}</p>
          <p>{tcCriteria[current.point.criterion]??current.point.criterion} · {current.point.paper_id.replace("arxiv:","arXiv ")}</p>
          {current.point.date_precision==="month"&&<p>Month precision · arXiv identifier</p>}
          {pinned&&<Link href={`/materials/${encodeURIComponent(current.point.material_id)}`} prefetch={false} className="site-text-link ner-timeline-material-link">View material data <span aria-hidden="true">↗</span></Link>}
          {pinned&&overlaps.length>1&&<div className="ner-timeline-overlaps"><span>{overlaps.findIndex(p=>p.point.id===selected)+1} / {overlaps.length} overlapping reports</span><button type="button" aria-label="Previous overlapping report" onClick={()=>setSelected(overlaps[(overlaps.findIndex(p=>p.point.id===selected)-1+overlaps.length)%overlaps.length].point.id)}>‹</button><button type="button" aria-label="Next overlapping report" onClick={()=>setSelected(overlaps[(overlaps.findIndex(p=>p.point.id===selected)+1)%overlaps.length].point.id)}>›</button></div>}
        </div>}
      </div>
      <div className="ner-timeline-foot"><span>{format(placed.length)} displayed{data.sampled?" · Sampled from "+format(data.plotted_results)+" plottable results":""}{family?" · "+(timelineFamilies[family]?.label??family):""}</span>
        <button type="button" className="site-text-link" onClick={read} disabled={!placed.length}>Read a point</button>
      </div>
      {!placed.length&&<p role="status">No reported results in this view. Choose another year, family or Tc range.</p>}
      <details className="ner-timeline-legend" open={legendOpen} onToggle={e=>setLegendOpen(e.currentTarget.open)}><summary aria-controls={chartId}>Material families ({familyNames.length}) <span>{legendOpen?"Collapse":"Expand"}</span></summary>
        <div id={chartId} className="ner-timeline-family-grid">{familyNames.map(key=>{const f=timelineFamilies[key];return <button key={key} type="button" aria-pressed={family===null||family===key} onClick={()=>{setFamily(family===key?null:key);dismiss();}}><span className="ner-timeline-family-mark" style={{color:f.color}} aria-hidden="true">{f.glyph}</span>{f.label}</button>;})}</div>
        {family&&<button type="button" className="site-text-link" onClick={()=>{setFamily(null);dismiss();}}>Show all families</button>}
      </details>
      <p className="ner-timeline-note">Dates refer to paper submission, not measurement or discovery. Month-only dates are labelled in the detail card. Intervals and bounds retain their reported form.</p>
      {(data.omitted_without_date>0||data.omitted_invalid_quantity>0)&&<p className="ner-timeline-note">{format(data.omitted_without_date)} results without a usable date and {format(data.omitted_invalid_quantity)} without a plottable Tc remain outside this chart.</p>}
    </>}
  </div>;
}
