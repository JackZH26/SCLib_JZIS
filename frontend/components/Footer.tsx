/**
 * Site footer — mirrors asrp.jzis.org's footer structure so the two
 * properties feel like parts of one family.
 *
 * Link set per user request:
 *   - GitHub  → SCLib_JZIS repo
 *   - ASRP    → https://asrp.jzis.org
 *   - JZIS    → https://www.jzis.org
 *   - Join Us → https://jzis.org/#join  (anchor on the main site)
 *
 * Layout: centered row of links over a small copyright line, backed by
 * --card-alt (the pale sage band) + top border for the same visual
 * separation asrp uses.
 */
import Link from "next/link";

const GithubIcon = () => (
  <svg
    width="16"
    height="16"
    viewBox="0 0 24 24"
    fill="currentColor"
    aria-hidden="true"
  >
    <path d="M12 0c-6.626 0-12 5.373-12 12 0 5.302 3.438 9.8 8.207 11.387.599.111.793-.261.793-.577v-2.234c-3.338.726-4.033-1.416-4.033-1.416-.546-1.387-1.333-1.756-1.333-1.756-1.089-.745.083-.729.083-.729 1.205.084 1.839 1.237 1.839 1.237 1.07 1.834 2.807 1.304 3.492.997.107-.775.418-1.305.762-1.604-2.665-.305-5.467-1.334-5.467-5.931 0-1.311.469-2.381 1.236-3.221-.124-.303-.535-1.524.117-3.176 0 0 1.008-.322 3.301 1.23.957-.266 1.983-.399 3.003-.404 1.02.005 2.047.138 3.006.404 2.291-1.552 3.297-1.23 3.297-1.23.653 1.653.242 2.874.118 3.176.77.84 1.235 1.911 1.235 3.221 0 4.609-2.807 5.624-5.479 5.921.43.372.823 1.102.823 2.222v3.293c0 .319.192.694.801.576 4.765-1.589 8.199-6.086 8.199-11.386 0-6.627-5.373-12-12-12z" />
  </svg>
);

export function Footer() {
  return (
    <footer className="mt-16 border-t border-sage-border bg-[rgba(232,240,232,0.6)]">
      <div className="mx-auto max-w-6xl px-6 py-12 text-center">
        <nav className="flex flex-wrap items-center justify-center gap-x-8 gap-y-3 text-sm text-slate-600">
          <a
            href="https://github.com/JackZH26/SCLib_JZIS"
            target="_blank"
            rel="noopener noreferrer"
            className="inline-flex items-center gap-1.5 transition-colors hover:text-accent-deep"
          >
            <GithubIcon />
            GitHub
          </a>
          <a
            href="https://asrp.jzis.org"
            target="_blank"
            rel="noopener noreferrer"
            className="transition-colors hover:text-accent-deep"
          >
            ASRP
          </a>
          <a
            href="https://www.jzis.org"
            target="_blank"
            rel="noopener noreferrer"
            className="transition-colors hover:text-accent-deep"
          >
            JZIS
          </a>
          <a
            href="https://jzis.org/#join"
            target="_blank"
            rel="noopener noreferrer"
            className="transition-colors hover:text-accent-deep"
          >
            Join Us
          </a>
        </nav>
        <p className="mt-5 text-xs text-slate-500">
          SCLib — JZIS Superconductivity Library · Apache 2.0 · Built by{" "}
          <a
            href="https://www.jzis.org"
            target="_blank"
            rel="noopener noreferrer"
            className="underline hover:text-accent-deep"
          >
            JZIS
          </a>
        </p>
      </div>
    </footer>
  );
}
