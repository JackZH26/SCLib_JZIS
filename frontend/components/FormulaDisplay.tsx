/**
 * Renders a chemical formula with proper subscript formatting.
 *
 * Splits the formula string on digit sequences (including decimals)
 * and wraps them in <sub> tags, so "YBa2Cu3O7-δ" becomes
 * Y<sub>Ba2</sub>Cu<sub>3</sub>O<sub>7</sub>-δ visually.
 *
 * Handles:
 *   - Simple formulas: H2S → H₂S
 *   - Complex oxides: YBa2Cu3O7 → YBa₂Cu₃O₇
 *   - Doping notation: La1.85Sr0.15CuO4 → La₁.₈₅Sr₀.₁₅CuO₄
 *   - Signed deltas: Bi2Sr2CaCu2O8+δ (subscripts on numbers only)
 *   - Parenthetical: Ba(Fe0.92Co0.08)2As2
 *   - Interface slash: LaAlO3/SrTiO3 (both sides get subscripts)
 */

/**
 * Parse a formula string into an array of { text, sub } segments.
 * `sub: true` means the segment should be rendered as <sub>.
 */
function parseFormula(formula: string): { text: string; sub: boolean }[] {
  // Match digit sequences (with optional decimal point and trailing digits).
  // E.g. "2", "0.15", "10", "6.95"
  const parts = formula.split(/(\d+\.?\d*)/);
  const result: { text: string; sub: boolean }[] = [];

  for (const part of parts) {
    if (!part) continue;
    if (/^\d+\.?\d*$/.test(part)) {
      result.push({ text: part, sub: true });
    } else {
      result.push({ text: part, sub: false });
    }
  }

  return result;
}

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
