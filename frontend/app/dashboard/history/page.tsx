import { ComingSoon } from "@/components/dashboard/ComingSoon";

export default function HistoryPage() {
  return (
    <ComingSoon
      title="Ask history"
      blurb="Every /ask question you run while signed in is saved here (rolling 90 days). The backend is already recording; the browsable list lands in the next release."
    />
  );
}
