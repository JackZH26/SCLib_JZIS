"use client";

import {Children, type ReactNode, useEffect, useRef} from "react";

/** Keep reading/tab order while allowing shorter topics to fill the next space. */
export function TopicGrid({children}: {children: ReactNode}) {
 const ref = useRef<HTMLDivElement>(null);
 useEffect(() => {
  const grid = ref.current;
  if (!grid || typeof ResizeObserver === "undefined") return;
  const items = Array.from(grid.children) as HTMLElement[];
  const measure = () => {
   const narrow = window.matchMedia("(max-width: 640px)").matches;
   grid.dataset.packed = narrow ? "false" : "true";
   for (const item of items) {
    const content = item.firstElementChild as HTMLElement;
    item.style.gridRowEnd = narrow ? "auto" : `span ${Math.ceil((content.getBoundingClientRect().height + 32) / 8)}`;
   }
  };
  const observer = new ResizeObserver(measure);
  items.forEach(item => observer.observe(item.firstElementChild!));
  window.addEventListener("resize", measure);
  measure();
  return () => { observer.disconnect(); window.removeEventListener("resize", measure); };
 }, []);
 return <div className="scwiki-topic-grid" ref={ref}>{Children.map(children, child => <div className="scwiki-topic-slot">{child}</div>)}</div>;
}
