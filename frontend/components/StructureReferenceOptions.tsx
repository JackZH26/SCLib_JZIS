import { structureHostContext, structureReferenceLabel, type StructureReference } from "@/lib/discovery-structures";

/** Native grouped options preserve keyboard selection in all coordinate workspaces. */
export function StructureReferenceOptions({ references }: { references: StructureReference[] }) {
  const families = [...new Set(references.map(ref => structureHostContext(ref).family))];
  return <>{families.map(family => <optgroup label={family} key={family}>
    {references.filter(ref => structureHostContext(ref).family === family).map(ref =>
      <option key={ref.id} value={ref.id}>{structureReferenceLabel(ref)}</option>)}
  </optgroup>)}</>;
}
