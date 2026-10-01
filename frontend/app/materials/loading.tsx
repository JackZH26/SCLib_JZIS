/** Match the compact browser geometry during a server navigation. */
export default function Loading() {
  return <div aria-busy="true" aria-label="Loading materials" className="space-y-4">
    <div className="h-9 w-48 rounded bg-sage-tint" /><div className="h-5 w-80 max-w-full rounded bg-sage-tint" />
    <div className="h-32 rounded-lg border border-sage-border bg-white" />
    <div className="h-9 rounded border border-sage-border bg-white" />
    <div className="overflow-hidden rounded-lg border border-sage-border bg-white">{Array.from({ length: 8 }, (_, i) => <div key={i} className="h-16 border-b border-sage-border last:border-b-0" />)}</div>
    <span className="sr-only">Loading reported materials and source evidence.</span>
  </div>;
}
