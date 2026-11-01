/** Shared plain-formula layout for React, exports and the corpus audit. */
export function parseFormula(formula: string): { text: string; sub: boolean }[] {
  // Polytype labels are part of the phase name, not stoichiometry. Preserve
  // their exact prefix (including prime and separator) on the text baseline.
  const prefix=formula.match(/^(\d+(?:Hb?|T['′]?|R|C)(?:\s*[-−–]\s*|\s+))/)?.[0] ?? "";
  // Match digit sequences (with optional decimal point and trailing digits).
  // E.g. "2", "0.15", "10", "6.95"
  const parts = formula.slice(prefix.length).split(/(\d+\.?\d*)/);
  const result: { text: string; sub: boolean }[] = prefix ? [{ text: prefix, sub: false }] : [];

  let consumed = prefix;
  for (const part of parts) {
    if (!part) continue;
    if (/^\d+\.?\d*$/.test(part)) {
      // A hydrate/adduct multiplier belongs on the baseline, e.g. ·1.3H2O.
      result.push({ text: part, sub: !/[·⋅∙×]\s*$/.test(consumed) });
    } else {
      result.push({ text: part, sub: false });
    }
    consumed += part;
  }

  return result;
}

/**
 * Same subscript rule as <FormulaDisplay>, but returns a plain HTML
 * string instead of JSX — for non-React renderers (e.g. Plotly's
 * hovertemplate, which accepts a limited HTML subset incl. <sub>).
 */
export function formulaToHtml(formula: string): string {
  const escape = (text: string) => text.replace(/[&<>"']/g, character => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[character]!);
  return parseFormula(formula)
    .map((seg) => (seg.sub ? `<sub>${escape(seg.text)}</sub>` : escape(seg.text)))
    .join("");
}

