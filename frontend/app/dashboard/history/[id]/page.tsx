import { AskHistoryDetail } from "@/components/dashboard/AskHistoryDetail";

export default async function HistoryReceiptPage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  return <AskHistoryDetail historyId={id} />;
}
