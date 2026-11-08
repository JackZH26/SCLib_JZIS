"use client";

import { useEffect, useId, useRef, useState } from "react";
import { getSimilar, type SimilarResponse } from "@/lib/api";
import { PaperCard } from "@/components/PaperCard";
import { SourceVisibilityNotice } from "@/components/MaterialVisibilityNotice";

export function SimilarPapers({ paperId }: { paperId: string }) {
  return <VisibleSimilarPapers key={paperId} paperId={paperId} />;
}

function VisibleSimilarPapers({ paperId }: { paperId: string }) {
  const section = useRef<HTMLElement>(null);
  const heading = useId();
  const [requested, setRequested] = useState(false);
  const [result, setResult] = useState<SimilarResponse | null>(null);
  const [failed, setFailed] = useState(false);

  useEffect(() => {
    if (requested || !section.current || typeof IntersectionObserver === "undefined") return;
    const observer = new IntersectionObserver((entries) => {
      if (entries.some((entry) => entry.isIntersecting)) {
        observer.disconnect();
        setRequested(true);
      }
    });
    observer.observe(section.current);
    return () => observer.disconnect();
  }, [requested]);

  useEffect(() => {
    if (!requested) return;
    const controller = new AbortController();
    getSimilar(paperId, 6, controller.signal).then((value) => {
      if (!controller.signal.aborted) setResult(value);
    }).catch(() => {
      if (!controller.signal.aborted) setFailed(true);
    });
    return () => controller.abort();
  }, [paperId, requested]);

  const loading = requested && !result && !failed;
  return (
    <section ref={section} aria-labelledby={heading} aria-busy={loading}>
      <h2 id={heading} className="mb-3 text-sm font-semibold uppercase tracking-wide text-slate-500">
        Similar papers
      </h2>
      {!requested && (
        <button type="button" onClick={() => setRequested(true)}
          className="rounded border border-slate-300 px-3 py-2 text-sm text-slate-700 hover:bg-slate-50 focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2">
          Find similar papers
        </button>
      )}
      {loading && <p role="status" className="text-sm text-slate-500">Loading similar papers…</p>}
      {failed && <p role="status" className="text-sm text-slate-500">Similar papers are unavailable right now.</p>}
      {result && result.results.length === 0 && (
        <p role="status" className="text-sm text-slate-500">No similar papers found.</p>
      )}
      {result && result.results.length > 0 && (
        <div className="grid gap-3 md:grid-cols-2">
          {result.results.map((paper) => (
            <PaperCard key={paper.paper_id} paper_id={paper.paper_id}
              arxiv_id={paper.arxiv_id} title={paper.title} authors={paper.authors}
              year={paper.year} score={paper.similarity} scoreLabel="similarity">
              <SourceVisibilityNotice visibility={null} compact />
            </PaperCard>
          ))}
        </div>
      )}
    </section>
  );
}
