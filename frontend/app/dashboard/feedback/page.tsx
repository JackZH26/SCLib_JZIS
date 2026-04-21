"use client";

/**
 * /dashboard/feedback — Feedback tab.
 *
 * Thin wrapper around FeedbackForm. The form itself owns category,
 * message, submitted-state, and the post-submission confirmation.
 */
import { FeedbackForm } from "@/components/dashboard/FeedbackForm";

export default function FeedbackPage() {
  return (
    <div className="space-y-5">
      <div>
        <h2 className="text-lg font-semibold text-sage-ink">Feedback</h2>
        <p className="mt-1 text-sm text-sage-muted">
          Bug report, feature request, or a data correction — it all goes
          to the JZIS team at <code>info@jzis.org</code>. Submitted while
          signed in, so we know who sent it and can reply.
        </p>
      </div>
      <FeedbackForm />
    </div>
  );
}
