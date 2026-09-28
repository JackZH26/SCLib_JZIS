import { knownVisibility, visibilityLabel } from "@/lib/material-visibility";
import { pressureLabel } from "@/lib/pressure-semantics";
import { escapePlotlyHtml, formatTimelineTc, type TimelineDisplayCluster } from "@/lib/timeline-display";

/** Wrap before escaping so neither source HTML nor a split entity becomes markup. */
function hoverLines(value: string, width = 38): string {
  const characters = Array.from(value.replace(/\s+/g, " ").trim());
  const lines: string[] = [];
  while (characters.length > width) {
    // Balance the final two lines instead of leaving a one-word last line.
    const target = characters.length <= width * 2 ? Math.ceil(characters.length / 2) : width;
    const space = characters.slice(0, target + 1).lastIndexOf(" ");
    const split = space > target / 2 ? space : target;
    lines.push(characters.splice(0, split).join(""));
    if (characters[0] === " ") characters.shift();
  }
  lines.push(characters.join(""));
  return lines.map(escapePlotlyHtml).join("<br>");
}

/** A bounded preview; exact identities, dates, sources and every member stay in the table. */
export function timelineHoverSummary(cluster: TimelineDisplayCluster): string {
  const single = cluster.members.length === 1 ? cluster.members[0] : null;
  const material = single ? Array.from(single.material.trim()) : [];
  const title = single
    ? material.length > 68 ? `${material.slice(0, 67).join("")}…` : material.join("")
    : `${cluster.members.length.toLocaleString("en-US")} overlapping received results`;
  const lines = [
    `<b>${hoverLines(title)}</b>`,
    `<b>${escapePlotlyHtml(formatTimelineTc(cluster.tc_kelvin))}</b> · ${cluster.year}`,
    hoverLines(`Origin: ${cluster.origin}`),
  ];
  if (single) {
    lines.push(hoverLines(pressureLabel(single.pressure_semantics, single.pressure_gpa)));
  } else {
    lines.push(`${cluster.sourceCount.toLocaleString("en-US")} linked ${cluster.sourceCount === 1 ? "source" : "sources"} · received selection`);
  }

  // Never use the first member's eligibility to describe a mixed cluster.
  const statuses = [...new Set(cluster.members.map(point => visibilityLabel(point.visibility)))];
  if (statuses.length <= 2) {
    lines.push(...statuses.map(status => hoverLines(status)));
  } else {
    const eligible = cluster.members.filter(point => knownVisibility(point.visibility)?.public_catalogue_eligible).length;
    lines.push("Mixed visibility statuses", `${eligible} catalogue eligible`,
      `${cluster.members.length - eligible} Archive / unverified`, "Not scientific approval");
  }
  lines.push('<span style="color:#58675e">Click for source &amp; result details</span>');
  return lines.join("<br>");
}
