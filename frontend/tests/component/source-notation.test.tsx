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
