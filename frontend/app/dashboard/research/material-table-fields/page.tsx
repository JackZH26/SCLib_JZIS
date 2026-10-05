import { MaterialTableFieldWorkbench } from "@/components/MaterialTableFieldWorkbench";

export default async function MaterialTableFieldsPage({ searchParams }: { searchParams: Promise<{ material?: string | string[]; field?: string | string[] }> }) {
  const query = await searchParams;
  return <MaterialTableFieldWorkbench initialMaterialId={typeof query.material === "string" && query.material.length <= 100 ? query.material : ""} initialField={typeof query.field === "string" && query.field.length <= 100 ? query.field : ""} />;
}
