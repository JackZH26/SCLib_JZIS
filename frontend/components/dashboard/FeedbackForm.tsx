"use client";

/**
 * Dashboard feedback form.
 *
 * Two-state view: a form by default, a green confirmation card after
 * a successful POST. The "Write another" button on the confirmation
 * resets everything back to the empty form — nothing carries over, so
 * a user who submitted by mistake can restart cleanly.
 *
 * We do not render the submitter's identity in the form; the server
 * attaches it from the JWT on our behalf (see api/routers/feedback.py).
 * The optional contact_email field is purely a hint to the recipient
 * for replies.
 */
import { useState } from "react";

import {
  ApiError,
  submitFeedback,
  type FeedbackCategory,
  type FeedbackPayload,
} from "@/lib/api";
import { loadToken } from "@/lib/auth-storage";
import { useDashboardUser } from "@/components/dashboard/user-context";

const CATEGORIES: { value: FeedbackCategory; label: string; blurb: string }[] = [
  { value: "bug", label: "Bug report", blurb: "Something is broken or produces wrong output." },
  { value: "feature_request", label: "Feature request", blurb: "An idea for something the site could do." },
  { value: "data_issue", label: "Data issue", blurb: "A paper or material record is wrong / missing / mis-classified." },
  { value: "other", label: "Other", blurb: "Anything else you want the JZIS team to know." },
];

const MIN_LEN = 5;
const MAX_LEN = 2000;

export function FeedbackForm() {
  const { user } = useDashboardUser();

  const [category, setCategory] = useState<FeedbackCategory>("bug");
  const [message, setMessage] = useState("");
  const [contactEmail, setContactEmail] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [submitted, setSubmitted] = useState(false);

  const msgLen = message.trim().length;
  const valid = msgLen >= MIN_LEN && msgLen <= MAX_LEN;

  async function onSubmit(e: React.FormEvent) {
    e.preventDefault();
    if (!valid) return;
    const token = loadToken();
    if (!token) return;
    setBusy(true);
    setError(null);
    const payload: FeedbackPayload = {
      category,
      message: message.trim(),
      contact_email: contactEmail.trim() || null,
    };
    try {
      await submitFeedback(token, payload);
      setSubmitted(true);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Failed to submit");
    } finally {
      setBusy(false);
    }
  }

  function reset() {
    setMessage("");
    setContactEmail("");
    setCategory("bug");
    setError(null);
    setSubmitted(false);
  }

  if (submitted) {
    return (
      <section className="rounded-lg border border-green-200 bg-green-50 p-6 shadow-sage">
        <h2 className="text-base font-semibold text-green-900">
          Thanks — we read every message.
        </h2>
        <p className="mt-2 text-sm text-green-800">
          Your feedback is on its way to the JZIS team. If you left a contact
          email we might reply directly; otherwise expect follow-ups at{" "}
          <strong>{user.email}</strong> when appropriate.
        </p>
        <div className="mt-4">
          <button
            onClick={reset}
            className="rounded-md bg-accent-deep px-4 py-2 text-sm font-medium text-white hover:bg-accent"
          >
            Write another
          </button>
        </div>
      </section>
    );
  }

  return (
    <section className="rounded-lg border border-sage-border bg-white p-5 shadow-sage">
      <form onSubmit={onSubmit} className="space-y-5">
        <fieldset className="space-y-2">
          <legend className="text-xs font-medium uppercase tracking-wide text-sage-tertiary">
            Category
          </legend>
          <div className="grid grid-cols-1 gap-2 sm:grid-cols-2">
            {CATEGORIES.map((c) => (
              <label
                key={c.value}
                className={[
                  "cursor-pointer rounded-md border p-3 text-sm transition-colors",
                  category === c.value
                    ? "border-accent bg-[rgba(58,125,92,0.08)] text-accent-deep"
                    : "border-sage-border bg-white text-sage-muted hover:border-accent-light",
                ].join(" ")}
              >
                <input
                  type="radio"
                  name="category"
                  value={c.value}
                  checked={category === c.value}
                  onChange={() => setCategory(c.value)}
                  className="sr-only"
                />
                <span className="block font-medium">{c.label}</span>
                <span className="mt-0.5 block text-xs font-normal text-sage-tertiary">
                  {c.blurb}
                </span>
              </label>
            ))}
          </div>
        </fieldset>

        <label className="block">
          <span className="text-xs font-medium uppercase tracking-wide text-sage-tertiary">
            Message
          </span>
          <textarea
            className="mt-1 block w-full rounded-md border border-sage-border px-3 py-2 text-sm focus:border-accent focus:outline-none focus:ring-1 focus:ring-accent"
            rows={8}
            value={message}
            onChange={(e) => setMessage(e.target.value)}
            maxLength={MAX_LEN}
            required
            placeholder={
              category === "data_issue"
                ? "Please include the paper / material ID or URL and what looks off."
                : category === "bug"
                  ? "What you did, what happened, what you expected. Browser version helps too."
                  : "Tell us what's on your mind."
            }
          />
          <div className="mt-1 flex items-center justify-between text-xs">
            <span
              className={
                msgLen > 0 && msgLen < MIN_LEN
                  ? "text-amber-700"
                  : "text-sage-tertiary"
              }
            >
              {msgLen < MIN_LEN
                ? `At least ${MIN_LEN} characters`
                : "Looking good."}
            </span>
            <span
              className={
                msgLen > MAX_LEN - 100 ? "text-amber-700" : "text-sage-tertiary"
              }
            >
              {msgLen.toLocaleString()} / {MAX_LEN.toLocaleString()}
            </span>
          </div>
        </label>

        <label className="block">
          <span className="text-xs font-medium uppercase tracking-wide text-sage-tertiary">
            Reply to a different address{" "}
            <span className="font-normal text-slate-400">(optional)</span>
          </span>
          <input
            type="email"
            className="mt-1 block w-full rounded-md border border-sage-border px-3 py-2 text-sm focus:border-accent focus:outline-none focus:ring-1 focus:ring-accent"
            value={contactEmail}
            onChange={(e) => setContactEmail(e.target.value)}
            placeholder={user.email}
            maxLength={255}
          />
          <p className="mt-1 text-xs text-sage-tertiary">
            Leave blank to reply to your account email ({user.email}).
          </p>
        </label>

        {error && (
          <p className="rounded-md bg-red-50 px-3 py-2 text-sm text-red-700" role="alert">
            {error}
          </p>
        )}

        <div className="flex items-center gap-3">
          <button
            type="submit"
            disabled={!valid || busy}
            className="rounded-md bg-accent-deep px-4 py-2 text-sm font-medium text-white hover:bg-accent disabled:opacity-60"
          >
            {busy ? "Sending…" : "Send feedback"}
          </button>
          <span className="text-xs text-sage-tertiary">
            We see <strong>{user.name}</strong> &lt;{user.email}&gt; on our end.
          </span>
        </div>
      </form>
    </section>
  );
}
