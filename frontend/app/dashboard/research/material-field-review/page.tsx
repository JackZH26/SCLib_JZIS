import { MaterialFieldReviewWorkbench } from "@/components/MaterialFieldReviewWorkbench";
import { FIELD_REVIEW_FIELDS, type ReviewField } from "@/lib/material-field-review";

export default async function MaterialFieldReviewPage({ searchParams }: { searchParams: Promise<{ target?: string | string[]; expression?: string | string[]; association?: string | string[]; field?: string | string[]; kind?: string | string[]; index?: string | string[] }> }) {
  const query = await searchParams;
  const bounded = (value: string | string[] | undefined) => typeof value === "string" && value.length <= 100 ? value : "";
  const field = FIELD_REVIEW_FIELDS.some(f => f === query.field) ? query.field as ReviewField : "tc_criterion";
  const kind = field === "measurement_method" && query.kind === "value" ? "value" : "condition";
  const index = typeof query.index === "string" && /^[0-7]$/.test(query.index) ? query.index : "0";
  return <MaterialFieldReviewWorkbench initialTargetId={bounded(query.target)} initialExpressionId={bounded(query.expression)} initialAssociationId={bounded(query.association)} initialField={field} initialKind={kind} initialIndex={index} />;
}
