/**
 * Placeholder card for dashboard tabs whose UI ships in a later phase.
 * The backend is already live — only the UI is pending — so we frame
 * it as "in progress" rather than "unavailable".
 */
export function ComingSoon({
  title,
  blurb,
}: {
  title: string;
  blurb: string;
}) {
  return (
    <section className="rounded-lg border border-dashed border-sage-border bg-white p-10 text-center shadow-sage">
      <h2 className="text-base font-semibold text-sage-ink">{title}</h2>
      <p className="mx-auto mt-2 max-w-md text-sm text-sage-muted">{blurb}</p>
      <p className="mt-4 text-xs font-medium uppercase tracking-wide text-sage-tertiary">
        UI coming in a follow-up release
      </p>
    </section>
  );
}
