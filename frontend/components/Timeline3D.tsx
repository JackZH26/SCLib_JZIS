"use client";

import Link from "@/components/AppLink";
import { useEffect, useRef, useState } from "react";
import type { AxisLabel, TimelineScene, TimelineSceneInput } from "@/lib/timeline-webgpu";
import type { TimelineDisplayCluster } from "@/lib/timeline-display";
import { formatTimelineTc, timelineYearBasis } from "@/lib/timeline-display";
import { pressureLabel } from "@/lib/pressure-semantics";
import { FAMILY_COLORS, familyLabel } from "@/lib/families";
import { visibilityLabel } from "@/lib/material-visibility";

type Props = Omit<TimelineSceneInput, "width" | "height"> & {
  onError: () => void; onReady: () => void; onSelect: (id: string) => void;
};
export default function Timeline3D({ clusters, xRange, yRange, logarithmic, onError, onReady, onSelect }: Props) {
  const host = useRef<HTMLDivElement>(null), canvas = useRef<HTMLCanvasElement>(null);
  const engine = useRef<TimelineScene | null>(null);
  const [width, setWidth] = useState(0), [labels, setLabels] = useState<AxisLabel[]>([]);
  const [perspective, setPerspective] = useState(false);
  const [tip, setTip] = useState<TimelineDisplayCluster | null>(null), [pinned, setPinned] = useState(false);
  const gesture = useRef<{ x: number; y: number; moved: boolean } | null>(null);
  const suppressClick = useRef(false);
  const pickFrame = useRef(0);
  const height = 500;
  useEffect(() => {
    const close = (event: KeyboardEvent) => { if (event.key === "Escape") { setTip(null); setPinned(false); } };
    window.addEventListener("keydown", close);
    return () => window.removeEventListener("keydown", close);
  }, []);
  useEffect(() => {
    if (!host.current) return;
    const element = host.current;
    const resize = () => setWidth(Math.max(280, Math.round(element.clientWidth)));
    resize(); const observer = new ResizeObserver(resize); observer.observe(element);
    return () => observer.disconnect();
  }, []);
  useEffect(() => {
    if (!canvas.current || !width) return;
    let cancelled = false;
    setTip(null); setPinned(false); setPerspective(false); setLabels([]);
    import("@/lib/timeline-webgpu").then(async ({ createTimelineScene }) => {
      if (cancelled) return;
      const scene = await createTimelineScene(canvas.current!, { width, height, clusters, xRange, yRange, logarithmic },
        next => { if (!cancelled) setLabels(next); }, () => { if (!cancelled) onError(); });
      if (cancelled) scene.dispose(); else { engine.current = scene; onReady(); }
    }).catch(() => { if (!cancelled) onError(); });
    return () => { cancelled = true; cancelAnimationFrame(pickFrame.current); engine.current?.dispose(); engine.current = null; };
  }, [width, clusters, xRange[0], xRange[1], yRange[0], yRange[1], logarithmic, onError, onReady]);
  const point = tip?.members[0];
  return <div className="timeline-three">
    <div className="timeline-view-controls">
      <span className="section-kicker">Reported results</span>
      <button type="button" aria-pressed={!perspective} onClick={() => { engine.current?.perspective(false); setPerspective(false); }}>Front view</button>
      <button type="button" aria-pressed={perspective} onClick={() => { engine.current?.perspective(true); setPerspective(true); }}>3D perspective</button>
      <button type="button" aria-label="Zoom in" onClick={() => engine.current?.zoom(1.15)}>+</button>
      <button type="button" aria-label="Zoom out" onClick={() => engine.current?.zoom(1 / 1.15)}>−</button>
    </div>
    <div ref={host} className="timeline-stage" style={{ height }}>
      <canvas ref={canvas} aria-label="Three-dimensional reported Tc chart. Use the results table to inspect every record."
        onPointerDown={event => { suppressClick.current = false; gesture.current = { x: event.clientX, y: event.clientY, moved: false }; if (event.pointerType === "mouse") event.currentTarget.setPointerCapture(event.pointerId); }}
        onPointerUp={() => { suppressClick.current = gesture.current?.moved ?? false; gesture.current = null; }}
        onPointerCancel={() => { gesture.current = null; }}
        onPointerMove={event => {
          if (gesture.current && event.pointerType === "mouse") {
            const { x, y } = gesture.current;
            if (Math.abs(event.clientX - x) + Math.abs(event.clientY - y) > 2) gesture.current.moved = true;
            if (perspective && !event.shiftKey) engine.current?.rotate(event.clientX - x, event.clientY - y);
            else engine.current?.pan(event.clientX - x, event.clientY - y);
            gesture.current.x = event.clientX; gesture.current.y = event.clientY; return;
          }
          if (pinned || event.pointerType !== "mouse") return;
          const rect = event.currentTarget.getBoundingClientRect(), x = event.clientX - rect.left, y = event.clientY - rect.top;
          cancelAnimationFrame(pickFrame.current);
          pickFrame.current = requestAnimationFrame(() => setTip(engine.current?.pick(x, y) ?? null));
        }}
        onClick={event => {
          if (suppressClick.current) return;
          const rect = event.currentTarget.getBoundingClientRect(), result = engine.current?.pick(event.clientX - rect.left, event.clientY - rect.top);
          if (result) { setTip(result); setPinned(true); onSelect(result.id); }
        }}
        onPointerLeave={() => { if (!pinned) setTip(null); }} />
      <svg className="timeline-axis-labels" width="100%" height={height} aria-hidden="true">
        {labels.map((label, i) => <text key={i} x={label.x} y={label.y} textAnchor={label.axis === "x" ? "middle" : "end"}>{label.text}</text>)}
        <text x="50%" y={height - 10} textAnchor="middle">Reported year (basis shown per result)</text>
        <text x="18" y="20">Tc (K)</text>
      </svg>
      {tip && point && <aside className="timeline-tip" aria-label="Selected result details" onKeyDown={event => { if (event.key === "Escape") { setTip(null); setPinned(false); } }}>
        <button type="button" aria-label="Close result details" onClick={() => { setTip(null); setPinned(false); }}>×</button>
        <strong>{point.material}</strong><p>{formatTimelineTc(tip.tc_kelvin)} · {tip.year}</p>
        <p>{timelineYearBasis(point)} · Criterion: {point.result_metadata?.tc_criterion ?? "unknown"}</p>
        <p>{pressureLabel(point.pressure_semantics, point.pressure_gpa)} · {tip.origin}</p>
        <p>{familyLabel(point.family)} · {visibilityLabel(point.visibility)}</p>
        <p>{point.result_metadata?.review_status === "legacy_unreviewed" ? "Legacy result · unreviewed" : "Result-level review unavailable"}. No scientific acceptance asserted.</p>
        <p>{tip.members.length} received result{tip.members.length === 1 ? "" : "s"} at these coordinates. Inspect all members in the table.</p>
        {point.paper_id && <Link href={`/paper/${encodeURIComponent(point.paper_id)}`} className="site-text-link">Source record →</Link>}
      </aside>}
    </div>
    <div className="timeline-family-legend" aria-label="Material families">{Array.from(new Set(clusters.map(c => c.family))).map(family => <span key={family}><i style={{ background: FAMILY_COLORS[family] ?? "#536b60" }} />{family === "mixed" ? "Mixed families" : familyLabel(family)}</span>)}</div>
    <p className="timeline-view-note">Choose a point for details. Drag to pan in Front view; drag to rotate in 3D perspective, or Shift-drag to pan. Front view resets the camera. Depth is visual only; it does not encode a scientific quantity.</p>
  </div>;
}
