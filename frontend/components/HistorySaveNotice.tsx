import Link from "next/link";

import { knownHistorySave } from "@/lib/answer-history";

/** A successful answer and a confirmed private save are separate outcomes. */
export function HistorySaveNotice({ value }: { value: unknown }) {
  const save = knownHistorySave(value);
  if (!save) return <p role="status" className="mt-3 text-xs text-amber-900">History save status is unavailable. This response does not confirm a saved receipt.</p>;
  if (save.status === "not_requested") return <p className="mt-3 text-xs text-sage-muted">History saving was not requested for this answer.</p>;
  if (save.status === "not_saved") return <p role="status" className="mt-3 text-xs text-amber-900">This answer was not saved to history.</p>;
  return <div className="mt-3 space-y-1 text-xs">
    <p role="status" className={save.status === "unknown" ? "text-amber-900" : "text-sage-muted"}>
      {save.status === "saved" ? "Saved to your private history." : "History save outcome is unknown. Check the receipt before assuming the answer was saved."}
    </p>
    <Link className="text-accent-deep underline" href={`/dashboard/history/${save.history_id}`}>
      {save.status === "saved" ? "View saved receipt" : "Check save outcome"}
    </Link>
    {save.status === "saved" && <p className="text-sage-muted">The receipt preserves recorded output and references; it is not scientific approval or a current source-permission check.</p>}
  </div>;
}
