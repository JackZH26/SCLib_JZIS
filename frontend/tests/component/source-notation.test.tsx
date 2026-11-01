import { render } from "@testing-library/react";
import { expect, it } from "vitest";
import { LatexText } from "@/components/LatexText";
import { renderSourceNotation, sourceNotationLabel } from "@/lib/source-notation";

it.each([
  ["Pr$_{1.85}$Ce$_{0.15}$CuO$_4$\\xspace", "Pr1.85Ce0.15CuO4"],
  ["BaFe$\\ensuremath{_{\\rm 1.8}}$Co$\\ensuremath{_{\\rm 0.2}}$As$\\ensuremath{_{\\rm 2}}$", "BaFe1.8Co0.2As2"],
  ["YBa$_2$Cu$_3$O$_{7-\\delta}", "YBa2Cu3O7−δ"],
  ["C\\lowercase{e}R\\lowercase{h}\\textsubscript{2}A\\lowercase{s}\\textsubscript{2}", "CeRh2As2"],
])("renders the actual source case %s without losing composition symbols", (raw, label) => {
  const r=renderSourceNotation(raw,true);
  expect(r.unresolved).toBe(false);
  expect(sourceNotationLabel(r.html)).toBe(label);
});

it("renders prose, escaped percentages, units and nested text math", () => {
  const raw="Reduced \\emph{samples}; 10\\%; $\\text{LaSrGaO$_4$}$; \\SI{0.7}{\\kelvin \\per \\minute}; $\\rho_\\mathrm{n}$";
  const r=renderSourceNotation(raw);
  expect(r.unresolved).toBe(false);
  const { container }=render(<LatexText>{raw}</LatexText>);
  container.querySelectorAll(".katex-mathml").forEach(n=>n.remove());
  expect(container.textContent).toContain("10%");
  expect(container.textContent).not.toMatch(/[\\$]/);
});

it.each([
  ["Properties of La_{3}Pd_{4}Ge_{4} with U_{3}Ni_{4}Si_{4}-type structure", "Properties of La3Pd4Ge4 with U3Ni4Si4-type structure"],
  ["Superconductivity in MgB_2 above T_c", "Superconductivity in MgB2 above Tc"],
  ["Upper critical field of Na_{x}(H_{3}O)_{z}CoO_{2}\\cdot yH_{2}O", "Upper critical field of Nax(H3O)zCoO2⋅ yH2O"],
])("renders scripts in undelimited evidence prose: %s", (raw, label) => {
  const r=renderSourceNotation(raw);
  expect(r.unresolved).toBe(false);
  expect(sourceNotationLabel(r.html)).toBe(label);
  expect(r.html).toContain("msupsub");
});

it("keeps ordinary sample and file identifiers literal", () => {
  for (const raw of ["sample_A", "sample_01", "archive_member:paper_v1.tex"]) {
    expect(renderSourceNotation(raw)).toEqual({html:raw,unresolved:false});
  }
});

it.each([
  "\\macroNotDefined{1.85}", "\uf064", "\u007f",
  "\\href{javascript:alert(1)}{link}", "\\htmlClass{unsafe}{x}",
  "\\input{/etc/passwd}",
])("does not leak unresolved source or execute %s", raw => {
  const r=renderSourceNotation(raw,true);
  expect(r.unresolved).toBe(true);
  expect(r.html).not.toContain("javascript:");
  expect(sourceNotationLabel(r.html)).toBe("Source notation requires review");
});

it("escapes literal HTML and preserves uncertainty / inequality in quantities", () => {
  expect(renderSourceNotation('<img src=x onerror="attack()">').html).toContain("&lt;img");
  const r=renderSourceNotation("\\leq 24 \\pm 0.5\\,\\mathrm{K}",true);
  expect(r.unresolved).toBe(false);
  expect(sourceNotationLabel(r.html)).toContain("≤24±0.5K");
});

it("keeps HTML-like source text inert when deriving an accessible plain-text label", () => {
  const raw='<scr<script>ipt>alert(1)</scr</script>ipt><img src=x onerror=attack()>';
  const rendered=renderSourceNotation(raw);
  const label=sourceNotationLabel(rendered.html);
  expect(label).toBe(raw);
  const { container }=render(<span aria-label={label} dangerouslySetInnerHTML={{__html:rendered.html}} />);
  expect(container.querySelector('script,img')).toBeNull();
  expect(container.textContent).toBe(raw);
});
