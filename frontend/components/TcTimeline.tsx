"use client";

/**
 * Plotly scatter: Tc (K) vs year, one dot per (material, year, Tc,
 * pressure) measurement. Server-side deduped in routers/timeline.py.
 *
 * Axes + interaction notes:
 *
 * - Y axis defaults to [-30, 250] K. The -30 K bottom is pure
 *   visual padding so dots near Tc=0 don't clip against the axis
 *   line; `minallowed` clamps pan/zoom to that same -30 K floor so
 *   readers can never see deeply negative (and physically nonsense)
 *   Kelvin. Upward zoom is still allowed in case future hydrides
 *   push Tc past 250 K.
 *
 * - X axis auto-ranges to the data, with a small ±1-year pad so the
 *   outermost points aren't glued to the frame edges. Each point's
 *   rendered x position gets a small deterministic jitter (±0.35 yr,
 *   stable per material) so high-volume years (NIMS 1995–2002) don't
 *   stack into solid unreadable columns. The original integer year
 *   is preserved in the hover card.
 *
 * - Markers are small (5 px) and semi-transparent so overlaps remain
 *   legible as density rather than a single opaque blob.
 *
 * - modeBar is ON (pan / box-zoom / reset / download PNG). dragmode
 *   defaults to 'pan' because scrolling a timeline left-right is
 *   more natural than draw-a-box. scrollZoom lets the mouse wheel
 *   zoom both axes in tandem.
 *
 * Loaded dynamically (ssr: false) because plotly.js walks `window`
 * at import time.
 */
import dynamic from "next/dynamic";
import { useState } from "react";
import type { TimelineCoverage, TimelinePoint } from "@/lib/api";

// `loading: () => null` because we render our own overlay below; the
// default would briefly flash plotly's empty inner div before our
// spinner appears.
const Plot = dynamic(() => import("react-plotly.js"), {
  ssr: false,
  loading: () => null,
});

// Color palette for each supported family; unknown family falls back
// to slate. Colors chosen to be discernible on light background and
// colorblind-friendly-ish.
const FAMILY_COLORS: Record<string, string> = {
  cuprate:       "#2563eb",   // blue
  iron_based:    "#ca8a04",   // amber
  nickelate:     "#0891b2",   // cyan — distinct from cuprate blue
  hydride:       "#dc2626",   // red
  mgb2:          "#059669",   // emerald
  heavy_fermion: "#7c3aed",   // violet
  fulleride:     "#db2777",   // pink
  conventional:  "#64748b",   // slate
};

// Label shown in the legend (capitalised / punctuated for humans).
const FAMILY_LABEL: Record<string, string> = {
  cuprate:       "Cuprate",
  iron_based:    "Iron-based",
  nickelate:     "Nickelate",
  hydride:       "Hydride",
  mgb2:          "MgB₂",
  heavy_fermion: "Heavy fermion",
  fulleride:     "Fulleride",
  conventional:  "Conventional",
  unknown:       "Other",
};

const Y_MAX_DEFAULT = 250;
// Visual cushion below 0 K so dots clustered around Tc=0 aren't
// pressed flat against the x-axis. Negative Kelvin is unphysical so
// these K values never carry data — they're whitespace only.
const Y_MIN_DEFAULT = -30;

function pressureLabel(p: number | null | undefined): string {
  if (p == null) return "ambient (unstated)";
  if (p <= 0) return "ambient";
  return `${p.toFixed(1)} GPa`;
}

// Deterministic ±0.35-year horizontal jitter seeded by material +
// Tc so the same point lands in the same spot on every render.
// Cheap 32-bit string hash — good enough for visual spreading.
function jitterYear(material: string, tc: number): number {
  const s = `${material}:${tc}`;
  let h = 2166136261 | 0;
  for (let i = 0; i < s.length; i++) {
    h ^= s.charCodeAt(i);
    h = Math.imul(h, 16777619);
  }
  const frac = ((h >>> 0) % 1000) / 1000; // [0, 1)
  return (frac - 0.5) * 0.7;              // [-0.35, 0.35)
}

export function TcTimeline({
  points,
  coverage,
}: {
  points: TimelinePoint[];
  coverage: TimelineCoverage | null;
}) {
  // Hidden once plotly fires onInitialized (= first paint complete).
  // Covers the gap between "page HTML hydrated" and "chart actually
  // visible" — that gap is several seconds with tens of thousands
  // of markers, and used to show as a blank white box.
  const [isPlotReady, setIsPlotReady] = useState(false);

  if (points.length === 0) {
    return (
      <div className="rounded-lg border border-dashed border-slate-300 bg-slate-50 p-8 text-center text-sm text-slate-500">
        No measurements match this filter yet. Daily aggregates run at
        03:10 UTC; come back tomorrow or pick a different family.
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
      name: FAMILY_LABEL[fam] ?? fam,
      x: subset.map((p) => p.year + jitterYear(p.material, p.tc_kelvin)),
      y: subset.map((p) => p.tc_kelvin),
      customdata: subset.map((p) => [
        // Pressure label is three-state:
        //   explicit >0 → "X GPa"
        //   explicit 0  → "ambient" (the paper confirms ambient P)
        //   null        → "ambient (unstated)" — we have no evidence
        //                 one way or the other; historically the NER
        //                 defaulted to 0.0 for unstated pressures, so
        //                 this bucket is the most honest fallback.
        pressureLabel(p.pressure_gpa),
        p.paper_id ?? "",
        p.year,
      ]),
      text: subset.map((p) => p.material),
      hovertemplate:
        "<b>%{text}</b><br>" +
        "Tc = %{y} K<br>" +
        "P = %{customdata[0]}<br>" +
        "Year = %{customdata[2]}<br>" +
        "%{customdata[1]}<extra></extra>",
      marker: {
        size: 5,
        opacity: 0.55,   // overlaps read as density, not a solid blob
        color: FAMILY_COLORS[fam] ?? "#94a3b8",
        // Dark outline when the record explicitly reports pressure > 0.
        // Lets the reader scan "which dots are high-pressure measurements"
        // at a glance without opening every tooltip.
        line: {
          width: subset.map((p) =>
            p.pressure_gpa != null && p.pressure_gpa > 0 ? 1.2 : 0,
          ),
          color: "#0f172a",
        },
      },
    };
  });

  // X range: pad one year either side so outermost dots aren't on
  // the axis line.
  const xMin = (coverage?.year_min ?? 1990) - 1;
  const xMax = (coverage?.year_max ?? new Date().getUTCFullYear()) + 1;

  return (
    <div
      className="relative w-full overflow-hidden rounded-lg border border-slate-200 bg-white"
      style={{ minHeight: 560 }}
    >
      {!isPlotReady && (
        <div className="absolute inset-0 z-10 flex items-center justify-center bg-white">
          <div className="flex flex-col items-center gap-3">
            <div
              className="h-10 w-10 animate-spin rounded-full border-2 border-slate-200 border-t-slate-900"
              aria-hidden
            />
            <p className="text-sm text-slate-500">Rendering chart…</p>
          </div>
        </div>
      )}
      <Plot
        onInitialized={() => setIsPlotReady(true)}
        data={traces}
        layout={{
          autosize: true,
          height: 560,
          margin: { l: 60, r: 20, t: 24, b: 60 },
          dragmode: "pan",
          hovermode: "closest",
          xaxis: {
            title: { text: "Year" },
            gridcolor: "#eef2ee",
            range: [xMin, xMax],
            // Allow user to scroll beyond the data range a bit if
            // they drag, but stay sane.
            rangeslider: { visible: false },
            showspikes: true,
            spikemode: "across",
            spikecolor: "#cbd5cb",
            spikethickness: 1,
          },
          yaxis: {
            title: { text: "Tc (K)" },
            gridcolor: "#eef2ee",
            range: [Y_MIN_DEFAULT, Y_MAX_DEFAULT],
            autorange: false,
            // Floor at Y_MIN_DEFAULT (= -30 K). Pan/zoom can't drift
            // below it. Auto-ticks handle spacing — at the default
            // [-30, 250] view plotly picks ≥50 K steps so no negative
            // tick label shows; zoomed views keep their fine ticks.
            minallowed: Y_MIN_DEFAULT,
            zeroline: true,
            zerolinecolor: "#d4e4d4",
          },
          legend: { orientation: "h", y: -0.14 },
          paper_bgcolor: "#fff",
          plot_bgcolor: "#fff",
        }}
        config={{
          responsive: true,
          displayModeBar: true,
          scrollZoom: true,
          // Keep only the navigation tools we actually want; drop
          // the noisy plotly logo + select tools.
          modeBarButtonsToRemove: [
            "lasso2d",
            "select2d",
            "autoScale2d",
            "toggleSpikelines",
          ],
          displaylogo: false,
          toImageButtonOptions: {
            filename: "sclib-tc-timeline",
            format: "png",
            scale: 2,
          },
        }}
        style={{ width: "100%", height: "560px" }}
      />
    </div>
  );
}
