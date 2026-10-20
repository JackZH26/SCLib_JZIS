import type { TimelineDisplayCluster } from "./timeline-display";
import { FAMILY_COLORS, familyLabel } from "./families";

const xml = (value: unknown) => String(value).replace(/[&<>"']/g, character =>
  ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&apos;" })[character]!);

/** A fixed front view, independent of GPU availability or the current camera. */
export function timelineSvg({
  clusters, xRange, yRange, logarithmic, receivedCount, sourceUrl,
}: {
  clusters: TimelineDisplayCluster[]; xRange: [number, number]; yRange: [number, number];
  logarithmic: boolean; receivedCount: number; sourceUrl: string;
}) {
  const width = 1200, height = 760, left = 85, top = 65, plotWidth = 1060, plotHeight = 470;
  const marks: string[] = [], ticks: string[] = [];
  let shown = 0;
  for (let i = 0; i <= 5; i++) {
    const x = left + i * plotWidth / 5, y = top + plotHeight - i * plotHeight / 5;
    const year = Math.round(xRange[0] + (xRange[1] - xRange[0]) * i / 5);
    const scaled = yRange[0] + (yRange[1] - yRange[0]) * i / 5;
    const tc = new Intl.NumberFormat("en-US", { maximumSignificantDigits: 4 }).format(logarithmic ? 10 ** scaled : scaled);
    ticks.push(`<path d="M${x} ${top}V${top + plotHeight}M${left} ${y}H${left + plotWidth}" stroke="#dce3d8" fill="none"/>`,
      `<text x="${x}" y="${top + plotHeight + 28}" text-anchor="middle">${year}</text>`,
      `<text x="${left - 14}" y="${y + 4}" text-anchor="end">${tc}</text>`);
  }
  for (const cluster of clusters) {
    const value = logarithmic ? Math.log10(cluster.tc_kelvin) : cluster.tc_kelvin;
    if (!Number.isFinite(value) || value < yRange[0] || value > yRange[1] || cluster.year < xRange[0] || cluster.year > xRange[1]) continue;
    shown++;
    const x = left + (cluster.year - xRange[0]) / Math.max(1, xRange[1] - xRange[0]) * plotWidth;
    const y = top + plotHeight - (value - yRange[0]) / Math.max(.000001, yRange[1] - yRange[0]) * plotHeight;
    const color = FAMILY_COLORS[cluster.family] ?? "#536b60";
    const title = `${cluster.year}; ${cluster.tc_kelvin} K; ${cluster.origin}; ${familyLabel(cluster.family)}; ${cluster.members.length} received result(s). ${cluster.members.map(p => `${p.material}; ${p.paper_id ?? "Source unavailable"}`).join(" | ")}`;
    const shape = cluster.origin === "Observed" ? `<circle r="4.5" fill="${color}"/>` :
      cluster.origin === "Computed" ? `<circle r="4.5" fill="white"/>` :
      cluster.origin === "Mixed origins" ? '<rect x="-4.5" y="-4.5" width="9" height="9" fill="white"/>' :
      cluster.origin === "Unknown / conflict" ? '<path d="M-4 -4L4 4M-4 4L4 -4" fill="none"/>' :
      '<path d="M0 -5L5 0L0 5L-5 0Z" fill="white"/>';
    marks.push(`<g transform="translate(${x} ${y})" stroke="${color}" stroke-width="1.3"><title>${xml(title)}</title>${shape}</g>`);
  }
  return `<svg xmlns="http://www.w3.org/2000/svg" width="${width}" height="${height}" viewBox="0 0 ${width} ${height}" role="img" aria-labelledby="title description">
<title id="title">SCLib reported Tc timeline — front view</title>
<desc id="description">${xml(`${receivedCount} received results; ${shown} visible coordinate clusters. Chart ranges: ${xRange.join("–")} years; ${yRange.join("–")} ${logarithmic ? "log10(K)" : "K"}. Display overlaps are not scientific deduplication. Selection may be sampled; omitted records are not represented. Source view: ${sourceUrl}`)}</desc>
<rect width="100%" height="100%" fill="#fbfcf8"/><g font-family="Arial, sans-serif" font-size="13" fill="#192720">
<text x="${left}" y="30" font-size="20" font-weight="bold">Reported transition temperatures</text>${ticks.join("")}${marks.join("")}
<text x="18" y="48">Tc (K)</text><text x="615" y="590" text-anchor="middle">Reported year (basis varies by result)</text>
<text x="${left}" y="625">Observed: filled circle · Computed: open circle · Inferred: diamond · Unknown: cross · Mixed: square</text>
<text x="${left}" y="650">${receivedCount.toLocaleString("en-US")} received results · ${shown.toLocaleString("en-US")} visible coordinate clusters · ${logarithmic ? "Logarithmic" : "Linear"} temperature scale</text>
<text x="${left}" y="675">Overlaps are display groups. Colours identify material families. Results are source reports, not scientific approval.</text>
<text x="${left}" y="700">The received selection may be sampled. Out-of-view records remain in the website table.</text>
<text x="${left}" y="725">Filters and source view are recorded in this SVG description. SCLib · jzis.org</text></g></svg>`;
}
