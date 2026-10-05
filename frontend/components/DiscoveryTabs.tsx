"use client";

import { useEffect, useRef, useState, type ReactNode } from "react";

const tabs = [
  { key: "candidates", panel: "discovery-candidates", label: "Candidates" },
  { key: "research", panel: "discovery-research", label: "Research & tools" },
] as const;
type Tab = typeof tabs[number]["key"];
type View = { active: Tab; anchor: string | null };

/** Both panels stay mounted so switching tabs preserves drafts and frozen selections. */
export function DiscoveryTabs({ candidates, research }: { candidates: ReactNode; research: ReactNode }) {
  const [view, setView] = useState<View>({ active: "candidates", anchor: null });
  const container = useRef<HTMLDivElement>(null);
  const links = useRef<Partial<Record<Tab, HTMLAnchorElement | null>>>({});

  useEffect(() => {
    const reveal = (hash: string) => {
      if (!hash) { setView({ active: "candidates", anchor: null }); return; }
      let id: string;
      try { id = decodeURIComponent(hash.slice(1)); } catch { return; }
      const target = document.getElementById(id);
      if (!target || !container.current?.contains(target)) return;
      const tab = tabs.find(item => document.getElementById(item.panel)?.contains(target));
      if (tab) setView({ active: tab.key, anchor: id });
    };
    const restore = () => reveal(window.location.hash);
    const followLink = (event: MouseEvent) => {
      if (event.defaultPrevented || event.button !== 0 || event.metaKey || event.ctrlKey || event.altKey || event.shiftKey) return;
      const link = event.target instanceof Element ? event.target.closest<HTMLAnchorElement>("a[href]") : null;
      if (!link || link.hasAttribute("download") || link.target && link.target !== "_self") return;
      const url = new URL(link.href, window.location.href);
      if (url.origin === window.location.origin && url.pathname === window.location.pathname && url.search === window.location.search && url.hash) reveal(url.hash);
    };
    restore();
    window.addEventListener("hashchange", restore); window.addEventListener("popstate", restore);
    document.addEventListener("click", followLink);
    return () => {
      window.removeEventListener("hashchange", restore); window.removeEventListener("popstate", restore);
      document.removeEventListener("click", followLink);
    };
  }, []);

  useEffect(() => {
    // Run after the panel's hidden attribute changes, including repeated links to the same fragment.
    if (view.anchor) {
      const target = document.getElementById(view.anchor);
      const panel = document.getElementById(`discovery-${view.active}`);
      if (target && panel?.contains(target)) {
        for (let parent: HTMLElement | null = target; parent && panel.contains(parent); parent = parent.parentElement) {
          if (parent instanceof HTMLDetailsElement) parent.open = true;
        }
        target.scrollIntoView?.({ block: "start", behavior: "auto" });
      }
    }
    const focused = document.activeElement;
    if (tabs.some(tab => tab.key !== view.active && focused && document.getElementById(tab.panel)?.contains(focused))) links.current[view.active]?.focus();
  }, [view]);

  const activate = (key: Tab, focus = false) => {
    const tab = tabs.find(item => item.key === key)!;
    const url = new URL(window.location.href); url.hash = tab.panel;
    if (url.href !== window.location.href) window.history.pushState(window.history.state, "", url);
    setView({ active: key, anchor: null });
    if (focus) links.current[key]?.focus();
  };

  return <div ref={container} className="min-w-0 space-y-4">
    <div role="tablist" aria-label="Discovery views" className="flex border-b border-sage-border">
      {tabs.map((tab, index) => <a key={tab.key} ref={node => { links.current[tab.key] = node; }} id={`discovery-tab-${tab.key}`}
        href={`#${tab.panel}`} role="tab" aria-controls={tab.panel} aria-selected={view.active === tab.key} tabIndex={view.active === tab.key ? 0 : -1}
        className={`inline-flex min-h-11 items-center border-b-2 px-4 py-2 text-sm font-semibold focus-visible:outline focus-visible:outline-2 focus-visible:outline-accent ${view.active === tab.key ? "border-accent text-accent" : "border-transparent text-sage-muted"}`}
        onClick={event => { if (event.button === 0 && !event.metaKey && !event.ctrlKey && !event.altKey && !event.shiftKey) { event.preventDefault(); activate(tab.key); } }}
        onKeyDown={event => {
          if (event.metaKey || event.ctrlKey || event.altKey || event.shiftKey) return;
          const next = event.key === "ArrowRight" ? (index + 1) % tabs.length : event.key === "ArrowLeft" ? (index + tabs.length - 1) % tabs.length
            : event.key === "Home" ? 0 : event.key === "End" ? tabs.length - 1 : ["Enter", " "].includes(event.key) ? index : null;
          if (next !== null) { event.preventDefault(); activate(tabs[next].key, true); }
        }}>{tab.label}</a>)}
    </div>
    <section id="discovery-candidates" role="tabpanel" aria-labelledby="discovery-tab-candidates" tabIndex={0} hidden={view.active !== "candidates"}
      className="min-w-0 scroll-mt-24 space-y-4 focus-visible:outline focus-visible:outline-2 focus-visible:outline-accent">{candidates}</section>
    <section id="discovery-research" role="tabpanel" aria-labelledby="discovery-tab-research" tabIndex={0} hidden={view.active !== "research"}
      className="min-w-0 scroll-mt-24 space-y-4 focus-visible:outline focus-visible:outline-2 focus-visible:outline-accent">{research}</section>
  </div>;
}
