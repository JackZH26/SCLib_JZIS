import Link from "@/components/AppLink";
import { researchCollection } from "@/lib/scwiki/research";
import { formatResearchDate } from "@/lib/scwiki/home";
import { ResearchCards } from "@/components/scwiki/ResearchCards";

/** Read the independent editorial store at request time, without a site release. */
export function HomeResearch() {
  let research: ReturnType<typeof researchCollection> | null = null;
  try { research = researchCollection(); } catch { /* Keep the rest of Home usable. */ }
  const latest = research?.issues[0];
  return <section className="scwiki home-research" aria-labelledby="home-research-heading">
    <div className="scwiki-section-heading">
      <div><p className="section-kicker">Selected from the literature</p><h2 id="home-research-heading">Latest research</h2></div>
      <Link href="/scwiki/research" className="site-text-link">All editions <span aria-hidden>↗</span></Link>
    </div>
    {latest && <p className="research-edition-date">{latest.id} · Selected {formatResearchDate(latest.selectedAt)} · Sources checked {formatResearchDate(latest.checkedAt)}</p>}
    {research?.warning && <p role="status">{research.warning}</p>}
    {!latest ? <p role="status">Research selections are temporarily unavailable.</p> :
      latest.outcome === "no-new-selection" ? <p>No new selections in this edition. {latest.editorialNote}</p> :
      <ResearchCards items={latest.items.slice(0, 3)} notices={research?.notices} />}
    <p className="scwiki-selection-note">Editorial selections with original sources and stated review limits.</p>
  </section>;
}
