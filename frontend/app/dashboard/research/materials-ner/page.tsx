import type { Metadata } from "next";
import { MaterialsProposalReview } from "@/components/MaterialsProposalReview";

export const metadata: Metadata = { title: "Materials paper assertions", robots: { index: false, follow: false, noarchive: true } };
export default async function MaterialsNerPage({ searchParams }: { searchParams: Promise<{ work_id?: string | string[] }> }) {
  const query = await searchParams;
  const work = typeof query.work_id === "string" && query.work_id.length <= 100 ? query.work_id : "";
  return <MaterialsProposalReview initialWorkId={work} />;
}
