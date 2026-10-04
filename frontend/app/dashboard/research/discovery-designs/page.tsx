import { DiscoveryDesignWorkbench } from "@/components/DiscoveryDesignWorkbench";

export default async function DiscoveryDesignsPage({ searchParams }: { searchParams: Promise<{ material?: string | string[]; property?: string | string[] }> }) {
  const query = await searchParams;
  const material = typeof query.material === "string" && query.material.length <= 100 ? query.material : "";
  const property = typeof query.property === "string" && /^[a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12}$/.test(query.property) ? query.property : "";
  return <DiscoveryDesignWorkbench key={`${material}:${property}`} initialMaterialId={material} initialPropertyId={property} />;
}
