import { cleanup, render } from "@testing-library/react";
import { afterEach, expect, it } from "vitest";
import { LatexText } from "@/components/LatexText";

afterEach(cleanup);
it.each([String.raw`$T_{\rm c}$`, String.raw`\(C_p(T)\)`, String.raw`\[\mu_0H\]`,
  String.raw`\mathrm{Bi_{2-x}Pb_xSr_2CaCu_2O_{8+\delta}}`, String.raw`\ce{FeSe}`])("renders supported notation: %s", text => {
  const { container } = render(<LatexText math>{text}</LatexText>);
  expect(container.querySelector(".katex")).not.toBeNull();
  expect(container.querySelector('.katex-html')!.textContent).not.toMatch(/\\|\$|_/);
  expect(container.querySelector('math')).not.toBeNull();
});
it("flags unresolved source notation and escapes untrusted markup", () => {
  const source = String.raw`$\unknown{FeSe}$ <img src=x onerror=alert(1)>`;
  const { container } = render(<LatexText>{source}</LatexText>);
  expect(container.textContent).toBe("Source notation requires review");
  expect(container.querySelector("[data-notation-unresolved]")).not.toBeNull();
  expect(container.querySelector("img")).toBeNull();
  expect(container.querySelector(".katex-error")).toBeNull();
});
it("does not trust TeX hyperlinks or render ordinary prose as math", () => {
  const { container } = render(<LatexText>{String.raw`Cost \$5; $\href{javascript:alert(1)}{click}$`}</LatexText>);
  expect(container.querySelector("a")).toBeNull();
  expect(container.textContent).toBe("Source notation requires review");
});
