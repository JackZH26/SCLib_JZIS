import { parseFormula } from "@/lib/chemical-formula";
export { formulaToHtml } from "@/lib/chemical-formula";

/**
 * Renders a chemical formula with proper subscript formatting.
 *
 * Splits the formula string on digit sequences (including decimals)
 * and wraps them in <sub> tags, so "YBa2Cu3O7-δ" becomes
 * YBa<sub>2</sub>Cu<sub>3</sub>O<sub>7</sub>-δ visually.
 *
 * Handles:
 *   - Simple formulas: H2S → H₂S
 *   - Complex oxides: YBa2Cu3O7 → YBa₂Cu₃O₇
 *   - Doping notation: La1.85Sr0.15CuO4 → La₁.₈₅Sr₀.₁₅CuO₄
 *   - Signed deltas: Bi2Sr2CaCu2O8+δ (subscripts on numbers only)
 *   - Parenthetical: Ba(Fe0.92Co0.08)2As2
 *   - Interface slash: LaAlO3/SrTiO3 (both sides get subscripts)
 */
export function FormulaDisplay({
  formula,
  className,
}: {
  formula: string;
  className?: string;
}) {
  const segments = parseFormula(formula);

  // Fast path: no subscripts needed (e.g. "FeSe", "Nb")
  if (segments.every((s) => !s.sub)) {
    return <span className={className}>{formula}</span>;
  }

  return (
    <span className={className}>
      {segments.map((seg, i) =>
        seg.sub ? (
          <sub key={i} className="relative -bottom-[0.15em] text-[0.75em]">
            {seg.text}
          </sub>
        ) : (
          <span key={i}>{seg.text}</span>
        ),
      )}
    </span>
  );
}
