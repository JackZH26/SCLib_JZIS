import { MaterialFieldCaseWorkbench } from "@/components/MaterialFieldCaseWorkbench";

export default async function MaterialFieldCasesPage({ searchParams }: { searchParams: Promise<{ material?: string | string[] }> }) {
  const query = await searchParams;
  const material = typeof query.material === "string" && query.material.length <= 100 ? query.material : "";
  return <MaterialFieldCaseWorkbench initialMaterialId={material} />;
}
