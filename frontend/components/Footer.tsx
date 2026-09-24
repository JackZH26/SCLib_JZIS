import Link from "next/link";
import { getVersion } from "@/lib/api";

const groups = [
  { title: "SCLib", links: [["/search", "Search"], ["/materials", "Materials"], ["/timeline", "Reported Tc Timeline"], ["/discovery", "Discovery"]] },
  { title: "Resources", links: [["/stats", "Library statistics"], ["/docs", "Documentation"], ["/docs/data", "Data & methodology"], ["/docs/api", "API reference"]] },
  { title: "JZIS", links: [["/about", "About JZIS"], ["/research", "Research"], ["/about/join", "Join & contribute"], ["/about#contact", "Contact"]] },
  { title: "Policies", links: [["/privacy", "Privacy"], ["/terms", "Terms"], ["/cookies", "Cookie Policy"]] },
];

export async function Footer() {
  const version = await getVersion();
  const siteVersion = version?.site_version !== "dev" ? version?.site_version : null;
  return (
    <footer className="mt-16 border-t border-sage-border bg-white sm:mt-24">
      <div className="mx-auto max-w-7xl px-4 py-10 sm:px-6 sm:py-12">
        <nav aria-label="Footer" className="grid grid-cols-2 gap-x-6 gap-y-8 sm:grid-cols-4">
          {groups.map((group) => (
            <div key={group.title}>
              <h2 className="text-sm font-semibold">{group.title}</h2>
              <ul className="mt-3 space-y-2.5 text-sm">
                {group.links.map(([href, label]) => <li key={href}><Link href={href} className="site-text-link text-sage-muted">{label}</Link></li>)}
              </ul>
            </div>
          ))}
        </nav>
        <div className="mt-9 border-t border-sage-border pt-5 text-xs text-sage-muted">
          <p>SCLib is developed and maintained by <Link href="/about" className="underline">JZ Institute of Science</Link>.</p>
          <p className="mt-2 flex flex-wrap gap-x-4 gap-y-2">
            <a href="https://github.com/JackZH26/SCLib_JZIS" target="_blank" rel="noopener noreferrer" className="underline">Source code</a>
            <a href="https://github.com/JackZH26/SCLib_JZIS/blob/main/LICENSE" target="_blank" rel="noopener noreferrer" className="underline">Code: Apache 2.0</a>
            <a href="https://github.com/JackZH26/SCLib_JZIS/blob/main/LICENSE-DATA" target="_blank" rel="noopener noreferrer" className="underline">Data: CC BY 4.0</a>
          </p>
          {(siteVersion || version?.dataset_version) && <details className="mt-4">
            <summary className="w-fit cursor-pointer py-1 font-medium">Library version &amp; provenance</summary>
            <p className="mt-2 flex flex-wrap gap-x-4 gap-y-1" aria-label="Library version">
              {siteVersion && <span>Site <a href={`https://github.com/JackZH26/SCLib_JZIS/commit/${siteVersion}`} className="font-mono underline" target="_blank" rel="noopener noreferrer">{siteVersion}</a></span>}
              {version?.dataset_version && <span>Data <span className="font-mono">{version.dataset_version}</span></span>}
            </p>
          </details>}
        </div>
      </div>
    </footer>
  );
}
