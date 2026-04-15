/**
 * Skeleton shown while the Server Component for /materials is
 * fetching the list from the API. Next renders this automatically
 * via the nearest loading.tsx during navigation.
 */
export default function Loading() {
  return (
    <div className="mx-auto max-w-6xl p-6">
      <div className="h-8 w-48 animate-pulse rounded bg-slate-200" />
      <div className="mt-6 grid grid-cols-1 gap-3">
        {Array.from({ length: 8 }).map((_, i) => (
          <div
            key={i}
            className="h-16 animate-pulse rounded-lg border border-slate-200 bg-white"
          />
        ))}
      </div>
    </div>
  );
}
