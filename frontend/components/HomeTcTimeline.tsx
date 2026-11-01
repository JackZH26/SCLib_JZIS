import Link from "@/components/AppLink";
import { MaterialsTcTimeline } from "@/components/MaterialsTcTimeline";

export function HomeTcTimeline() {
  return <section aria-labelledby="home-timeline-heading" className="mt-14 sm:mt-20">
    <div className="flex flex-wrap items-end justify-between gap-4">
      <div><h2 id="home-timeline-heading" className="text-3xl font-semibold tracking-tight">TcTimeline</h2>
        <p className="mt-3 text-sm text-sage-muted">Explore reported superconducting transition temperatures through time.</p></div>
      <Link href="/timeline" className="site-text-link text-sm font-semibold">Open TcTimeline <span aria-hidden="true">↗</span></Link>
    </div>
    <div className="mt-6 rounded-xl border border-sage-border bg-white p-4 sm:p-6"><MaterialsTcTimeline compact /></div>
  </section>;
}
