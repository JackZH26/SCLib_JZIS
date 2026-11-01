import { render } from "@testing-library/react";
import { expect, it } from "vitest";
import { FormulaDisplay, formulaToHtml } from "@/components/FormulaDisplay";

it.each([
  ["2H-NbSe2", ["2"]],
  ["1T -KMoS2", ["2"]],
  ["4Hb-Nb0.95Ti0.05Se2", ["0.95", "0.05", "2"]],
  ["6R TaS2", ["2"]],
  ["1T′-MoTe2", ["2"]],
  ["Ba(Fe0.92Co0.08)2As2", ["0.92", "0.08", "2", "2"]],
])("keeps the phase label in %s separate from composition subscripts", (formula, expected) => {
  const { container }=render(<FormulaDisplay formula={formula as string} />);
  expect(Array.from(container.querySelectorAll("sub"),n=>n.textContent)).toEqual(expected);
  expect(container.textContent).toBe(formula);
  const alternate=document.createElement("div");alternate.innerHTML=formulaToHtml(formula as string);
  expect(Array.from(alternate.querySelectorAll("sub"),n=>n.textContent)).toEqual(expected);
  expect(alternate.textContent).toBe(formula);
});
