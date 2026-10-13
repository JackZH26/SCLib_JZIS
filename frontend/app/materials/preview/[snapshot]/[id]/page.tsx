import type { Metadata } from "next";
import { notFound } from "next/navigation";
import Link from "@/components/AppLink";
import { MaterialReports } from "@/components/MaterialReports";

export const dynamic = "force-dynamic";
export const metadata: Metadata = {
  title: "Material candidate preview",
  robots: { index: false, follow: false, noarchive: true, googleBot: { index: false, follow: false, noarchive: true } },
};

export default async function MaterialCandidatePreview({ params }: {
  params: Promise<{ snapshot: string; id: string }>;
}) {
  const { snapshot, id } = await params;
  if (!/^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i.test(snapshot)) notFound();
  const materialId = decodeURIComponent(id);
  return <main id="main-content" className="mx-auto max-w-7xl space-y-6 px-4 py-8 sm:px-6">
    <header className="space-y-2">
      <Link href={`/materials/${encodeURIComponent(materialId)}`} className="text-sm text-accent-deeper underline">Open material catalogue entry</Link>
      <h1 className="text-2xl font-semibold text-accent-deeper">Material candidate preview</h1>
      <p className="max-w-3xl text-sm text-mute">Inspect selected extraction results by paper, sample and conditions. Reviewer access is required.</p>
    </header>
    <MaterialReports key={`${snapshot}:${materialId}`} materialId={materialId} snapshotId={snapshot} initiallyOpen />
  </main>;
}
