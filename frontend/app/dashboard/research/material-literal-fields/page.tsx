import { MaterialLiteralFieldWorkbench } from "@/components/MaterialLiteralFieldWorkbench";

export default async function MaterialLiteralFieldsPage({ searchParams }: { searchParams: Promise<{ material?: string | string[]; field?: string | string[]; candidate?: string | string[] }> }) {
  const query = await searchParams;
  return <MaterialLiteralFieldWorkbench initialMaterialId={typeof query.material === "string" && query.material.length <= 100 ? query.material : ""} initialField={typeof query.field === "string" && query.field.length <= 100 ? query.field : ""} initialCandidateId={typeof query.candidate === "string" && /^enrichment:[a-f0-9]{64}$/.test(query.candidate) ? query.candidate : ""} />;
}
