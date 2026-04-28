/**
 * Shown while the /timeline server component is fetching the
 * Tc-vs-year dataset. The dataset is large (tens of thousands of
 * points) so the fetch can take a few seconds — a centred spinner
 * is more honest than a skeleton box that suggests imminent paint.
 */
export default function Loading() {
  return (
    <main className="space-y-6">
      <div>
        <h1 className="text-3xl font-bold tracking-tight">Tc timeline</h1>
        <p className="mt-1 text-sm text-slate-600">
          Transition temperature versus year, one dot per reported
          measurement.
        </p>
      </div>
      <div className="flex h-[560px] items-center justify-center rounded-lg border border-slate-200 bg-white">
        <div className="flex flex-col items-center gap-3">
          <div
            className="h-10 w-10 animate-spin rounded-full border-2 border-slate-200 border-t-slate-900"
            aria-hidden
          />
          <p className="text-sm text-slate-500">Loading timeline data…</p>
        </div>
      </div>
    </main>
  );
}
