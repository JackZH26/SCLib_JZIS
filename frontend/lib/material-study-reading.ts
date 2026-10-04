/** Related paper readings for three inspected result identities; no property overlay. */
const readings = [
  {
    materialId: "mat:bitecl",
    resultId: "legacy-result:728957cf5518e15646f532d9d27aedd22bca169618e1ef790265914d1d76bad9",
    paperId: "arxiv:1501.06203",
    href: "/materials/source-observations/pressure-and-tables#study-context-bi-transport",
    label: "Preparation and pressure protocols",
    note: "Transport and Raman use different pressure media. Room temperature describes pressure calibration, rather than a superconducting measurement.",
  },
  {
    materialId: "mat:mo5p1.07b1.93",
    resultId: "legacy-result:01d196800fc62b1527e9166970f10347a5efa220a15a5fa78cc3522a14907038",
    paperId: "arxiv:1603.02892",
    href: "/materials/source-observations/pressure-and-tables#mo-table-heading",
    label: "Original sample columns and Tc criteria",
    note: "Two nominal preparations share a printed refined composition. Their table columns retain different Tc values and measurement criteria.",
  },
  {
    materialId: "mat:bafe1.906pt0.094as2",
    resultId: "legacy-result:1f4b7b62aa3681ab5fe9962e85c0171dcb8714a6d0721d5e4ad429bc60ad18ac",
    paperId: "arxiv:0912.2752",
    href: "/materials/source-observations/followup#study-context-pt-calorimetry-attribution",
    label: "Transition methods and XRD composition",
    note: "The paper caption attributes 23 K to resistivity and magnetic susceptibility. Its calorimetry feature is described separately, around 20 K and below 21 K.",
  },
] as const;

export type MaterialStudyReading = Omit<typeof readings[number], "href"> & { href: string };

export function materialStudyReading(materialId: string, selected: unknown): MaterialStudyReading | null {
  if (!selected || typeof selected !== "object" || Array.isArray(selected)) return null;
  const result = selected as Record<string, unknown>;
  if (!result.source || typeof result.source !== "object" || Array.isArray(result.source)) return null;
  const paperId = (result.source as Record<string, unknown>).paper_id;
  const reading = readings.find(reading => reading.materialId === materialId
    && reading.resultId === result.result_id && reading.paperId === paperId);
  return reading ? { ...reading, href: (process.env.NEXT_PUBLIC_BASE_PATH || "") + reading.href } : null;
}
