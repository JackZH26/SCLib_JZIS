const basePath = process.env.NEXT_PUBLIC_BASE_PATH || "";

/** Approved SC monogram A; the wordmark is embedded in the supplied SVG. */
export function Brand({ reversed = false }: { reversed?: boolean }) {
  return <img src={`${basePath}/brand/${reversed ? "logo-reversed" : "logo"}.svg`}
    width={196} height={56} alt="SCLib" className="sclib-brand" />;
}
