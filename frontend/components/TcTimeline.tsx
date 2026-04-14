"use client";

/**
 * Plotly scatter: Tc (K) vs year, one dot per measurement.
 *
 * Loaded dynamically (ssr: false) because plotly.js walks `window`
 * at import time. The page that embeds us passes an already-fetched
 * points array so the chart itself has no data dependencies.
 */
import dynamic from "next/dynamic";
import type { TimelinePoint } from "@/lib/api";

const Plot = dynamic(() => import("react-plotly.js"), { ssr: false });

const FAMILY_COLORS: Record<string, string> = {
  cuprate: "#2563eb",
  iron: "#ca8a04",
  hydride: "#dc2626",
  mgb2: "#059669",
  heavy_fermion: "#7c3aed",
  conventional: "#64748b",
};

export function TcTimeline({ points }: { points: TimelinePoint[] }) {
  if (points.length === 0) {
    return (
      <div className="rounded-lg border border-dashed border-slate-300 bg-slate-50 p-8 text-center text-sm text-slate-500">
        No Tc records available yet — waiting on Phase 5 material aggregation.
      </div>
    );
  }

  const families = Array.from(
    new Set(points.map((p) => p.family ?? "unknown")),
  );

  const traces = families.map((fam) => {
    const subset = points.filter((p) => (p.family ?? "unknown") === fam);
    return {
      type: "scatter" as const,
      mode: "markers" as const,
      name: fam,
      x: subset.map((p) => p.year),
      y: subset.map((p) => p.tc_kelvin),
      text: subset.map(
        (p) =>
          `${p.material}<br>Tc = ${p.tc_kelvin} K${
            p.pressure_gpa ? `<br>p = ${p.pressure_gpa} GPa` : ""
          }`,
      ),
      hovertemplate: "%{text}<extra></extra>",
      marker: {
        size: 10,
        color: FAMILY_COLORS[fam] ?? "#94a3b8",
        line: { width: 1, color: "#fff" },
      },
    };
  });

  return (
    <div className="w-full overflow-hidden rounded-lg border border-slate-200 bg-white">
      <Plot
        data={traces}
        layout={{
          autosize: true,
          height: 520,
          margin: { l: 60, r: 20, t: 20, b: 50 },
          xaxis: { title: "Year", gridcolor: "#eee" },
          yaxis: { title: "Tc (K)", gridcolor: "#eee", rangemode: "tozero" },
          legend: { orientation: "h", y: -0.15 },
          paper_bgcolor: "#fff",
          plot_bgcolor: "#fff",
        }}
        config={{ displayModeBar: false, responsive: true }}
        style={{ width: "100%", height: "520px" }}
      />
    </div>
  );
}
