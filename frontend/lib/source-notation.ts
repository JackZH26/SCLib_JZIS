/** Bounded server-side display of source TeX. Never execute paper macros here. */
import katex from "katex";
import "katex/contrib/mhchem";

const escape = (s: string) => s.replace(/[&<>"']/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c]!);
const WRAPPERS = new Set(["text", "textrm", "textnormal", "textup", "textmd", "textit", "textsl", "textbf", "emph", "mbox", "mathrm", "mathbf", "mathit", "mathsf"]);
const SPACING = new Set(["xspace", "protect", "boldmath", "unboldmath", "rm", "it", "bf", "sl", "sc", "em", "small", "footnotesize", "scriptsize"]);
const ARGS: Record<string, number> = { frac: 2, dfrac: 2, tfrac: 2, sqrt: 1, bar: 1, overline: 1, hat: 1, vec: 1, dot: 1, ddot: 1, ce: 1, mathcal: 1, mathbb: 1 };
const ALIASES: Record<string, string> = { textmu: "\\mu", upmu: "\\mu", upalpha: "\\alpha", textdegree: "^{\\circ}", degree: "^{\\circ}", textcelsius: "^{\\circ}\\mathrm{C}", AA: "\\mathring{\\mathrm{A}}", textless: "<", textgreater: ">", bm: "\\boldsymbol" };
const COMMAND = /^\\([A-Za-z]+|.)/s;

function argument(s: string, start: number): [string, number] {
  let p = start;
  while (/\s/.test(s[p] ?? "") && p < s.length) p++;
  if (p >= s.length) throw new Error("Missing argument");
  if (s[p] !== "{") {
    const token = s.slice(p).match(COMMAND)?.[0] ?? s[p];
    return [token, p + token.length];
  }
  let depth = 1; const begin = ++p;
  for (; p < s.length; p++) {
    if (s[p] === "\\") { p += (s.slice(p).match(COMMAND)?.[0].length ?? 1) - 1; continue; }
    depth += Number(s[p] === "{") - Number(s[p] === "}");
    if (!depth) return [s.slice(begin, p), p + 1];
  }
  throw new Error("Unbalanced group");
}

function cleanMath(s: string): string {
  s = s.replace(/\\ensuremath(?=\s*\{)/g, "")
    .replace(/\\mbox(?![A-Za-z])/g, "\\text")
    .replace(/([_^])\\rm\s*(\{[^{}]*\}|[A-Za-z0-9])/g, "$1{\\mathrm{$2}}")
    .replace(/\\scalebox\s*\{[^{}]*\}/g, "")
    .replace(/\\(?:si|unit)(?![A-Za-z])/g, "\\mathrm")
    .replace(/\\(micro|ohm|kelvin|K|minute|per)(?![A-Za-z])/g, (_, n) => ({ micro: "\\mu ", ohm: "\\Omega ", kelvin: "K", K: "K", minute: "min", per: "/" } as Record<string,string>)[n]!);
  s = s.replace(/\\require\s*\{mhchem\}/g, "");
  if (/(?<!\\)%/.test(s)) throw new Error("Unescaped percent in math");
  // Only standard typography aliases, never material-specific shorthand.
  return s.replace(/\\(textsubscript|textsuperscript)\s*\{/g, (_, kind) => kind === "textsubscript" ? "_{" : "^{")
    .replace(/\\(?:protect|xspace|boldmath|unboldmath)(?![A-Za-z])/g, "")
    .replace(/\\(?:textsl|emph)(?![A-Za-z])/g, "\\textit")
    .replace(/\\(?:textmd|textup|textnormal)(?![A-Za-z])/g, "\\textrm")
    .replace(/\\(?:footnotesize|scriptsize|small)(?![A-Za-z])/g, "")
    .replace(/\\(textmu|upmu|upalpha|textdegree|degree|textcelsius|AA|textless|textgreater|bm)(?![A-Za-z])/g, (_, n) => ALIASES[n]);
}

function mathHtml(s: string): string {
  // KaTeX's explicit failure is caught by the caller; raw commands are never
  // used as a visually broken fallback. HTML and URL macros remain untrusted.
  if (/\\(?:href|url|html[A-Za-z]*|includegraphics|input|write|def|newcommand)(?![A-Za-z])/.test(s)) throw new Error("Unsupported source command");
  const html = '<span class="reported-math">' + katex.renderToString(cleanMath(s), {
    throwOnError: true, trust: false, strict: "ignore", output: "htmlAndMathml",
    maxExpand: 200, maxSize: 10,
  }) + "</span>";
  if (/\\[A-Za-z]/.test(sourceNotationLabel(html))) throw new Error("Unresolved rendered command");
  return html;
}

function prose(s: string, depth = 0): string {
  if (depth > 20) throw new Error("Nesting limit");
  let html = "", p = 0;
  while (p < s.length) {
    let delimiter = "";
    if (s[p] === "$") delimiter = s[p+1] === "$" ? "$$" : "$";
    else if (s.startsWith("\\(", p)) delimiter = "\\(";
    else if (s.startsWith("\\[", p)) delimiter = "\\[";
    if (delimiter) {
      const closing = delimiter === "\\(" ? "\\)" : delimiter === "\\[" ? "\\]" : delimiter;
      const start = p + delimiter.length;
      let end = -1, braces = 0;
      for (let i=start; i<s.length; i++) {
        if (s.startsWith(closing,i) && braces===0) { end=i;break; }
        if (s[i]==="\\") { i+=(s.slice(i).match(COMMAND)?.[0].length ?? 1)-1;continue; }
        braces+=Number(s[i]==="{")-Number(s[i]==="}");
      }
      if (end < 0 && delimiter === "$" && braces === 0) {
        // Extraction often clips one math delimiter. Reclose the same text;
        // no element, number, variable or sign is inserted or removed.
        html += mathHtml(s.slice(start)); p=s.length;continue;
      }
      if (end < 0) throw new Error("Unbalanced math delimiter");
      html += mathHtml(s.slice(start, end)); p = end + closing.length; continue;
    }
    if (s[p] === "{") {
      const [body,end] = argument(s,p); html += prose(body,depth+1); p=end; continue;
    }
    if (s[p] === "}") throw new Error("Unbalanced group");
    const command = s.slice(p).match(COMMAND);
    if (command) {
      const name=command[1]; p+=command[0].length;
      if (SPACING.has(name) || name === "-") continue;
      if (["si", "unit"].includes(name)) { const [body,end]=argument(s,p);p=end;html+=mathHtml(cleanMath(body));continue; }
      if (name === "SI") { const [number,e]=argument(s,p);const [unit,end]=argument(s,e);p=end;html+=mathHtml(number+"\\,"+cleanMath(unit));continue; }
      if (name === "slash") { html+="/";continue; }
      if (["micro", "ohm", "kelvin", "K", "minute", "per"].includes(name)) { html+=mathHtml(cleanMath(command[0]));continue; }
      if (name === "diameter") { html+="⌀";continue; }
      if (name === "scalebox") { const [,e]=argument(s,p); const [body,end]=argument(s,e);p=end;html+=prose(body,depth+1);continue; }
      if (['"', "'", "`", "^", "~"].includes(name)) { const [body,end]=argument(s,p);p=end;html+=mathHtml("\\text{"+command[0]+"{"+body+"}}");continue; }
      if (name === "thinspace") { html += "&thinsp;"; continue; }
      if (["%", "#", "&", "_", "{", "}", "$"].includes(name)) { html+=escape(name);continue; }
      if ([",", ";", "!", " ", "\\", "\n"].includes(name)) { html+=" ";continue; }
      if (WRAPPERS.has(name) || name === "lowercase") {
        const [body,end] = argument(s,p); p=end;
        html += prose(name === "lowercase" ? body.toLowerCase() : body,depth+1); continue;
      }
      if (["ref", "eqref", "figref", "cite", "citep", "citet", "onlinecite"].includes(name)) {
        const [body,end] = argument(s,p); p=end;
        html += escape((name.includes("cite") ? "reference" : "source label") + " [" + body + "]"); continue;
      }
      if (name === "hspace" || name === "vspace") {
        const [,end]=argument(s,p);p=end;html+=" ";continue;
      }
      if (name === "ensuremath" || name === "textsubscript" || name === "textsuperscript") {
        const [body,end]=argument(s,p);p=end;
        html+=mathHtml(name === "ensuremath" ? body : (name === "textsubscript" ? "_{" : "^{")+body+"}");continue;
      }
      let expression = ALIASES[name] ?? command[0];
      for (let i=0; i<(ARGS[name] ?? 0); i++) {
        const [body,end]=argument(s,p);p=end;expression+="{"+body+"}";
      }
      while (s[p] === "_" || s[p] === "^") {
        const operator=s[p++];const [body,end]=argument(s,p);p=end;expression+=operator+"{"+body+"}";
      }
      html+=mathHtml(expression); continue;
    }
    if (s[p] === "_" || s[p] === "^") {
      const operator=s[p++];let [body,end]=argument(s,p);p=end;
      if (/^\\(?:mathrm|text|textrm|rm)$/.test(body)) { const [value,next]=argument(s,p);p=next;body=body+"{"+value+"}"; }
      html+=mathHtml(operator+"{"+body+"}");continue;
    }
    if (s[p] === "\\" && p === s.length-1) { p++;continue; }
    if (s[p] === "\\") throw new Error("Incomplete command");
    if (s.startsWith("--",p)) { html+="–";p+=2;continue; }
    html += s[p] === "~" ? "&nbsp;" : escape(s[p]); p++;
  }
  return html;
}

export function renderSourceNotation(text: string, math = false): { html: string; unresolved: boolean } {
  try {
    if (text.length > 32768 || /[\uE000-\uF8FF\uFFFD\x00-\x08\x0b\x0c\x0e-\x1f\x7f]/.test(text)) throw new Error("Unresolved source glyph");
    const hasTeX = /[\\$]/.test(text) || (math && /[_^]/.test(text));
    if (!hasTeX) return { html: escape(text), unresolved: false };
    // Undelimited formula expressions are a single math run; prose preserves
    // normal word spacing and renders only its embedded scientific notation.
    const html = math && !/[$]|\\[([]/.test(text) && /[\\_^]/.test(text) && !/\\(?:lowercase|textsubscript|textsuperscript)/.test(text)
      ? mathHtml(text) : prose(text);
    return { html, unresolved: false };
  } catch {
    return {
      html: '<span class="materials-notation-pending" data-notation-unresolved="true">Source notation requires review</span>',
      unresolved: true,
    };
  }
}

/** Spoken labels contain rendered notation, never TeX commands or MathML source. */
export function sourceNotationLabel(html: string): string {
  return html.replace(/<span class="katex-mathml">[\s\S]*?<\/math><\/span>/g, "")
    .replace(/<[^>]*>/g, "").replace(/&(?:amp|lt|gt|quot|#39|nbsp|thinsp);/g,
      s => ({ "&amp;": "&", "&lt;": "<", "&gt;": ">", "&quot;": '\"', "&#39;": "'", "&nbsp;": " ", "&thinsp;": " " })[s]!)
    .replace(/[\u200b\u200c\u200d]/g, "").trim();
}
