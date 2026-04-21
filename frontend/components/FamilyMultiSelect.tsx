"use client";

/**
 * Material-family multi-select dropdown.
 *
 * Button shows the current selection ("All families" when empty; a
 * short label when one picked; "N families" when two or more). Panel
 * is a plain checkbox list that supports single or multi-select in
 * one affordance — click any to toggle. "Clear all" resets.
 *
 * Click-outside closes the panel. The family taxonomy matches the
 * aggregator slugs in ingestion/.../nims.py::classify_family() and
 * the backend's SearchFilters.material_family[] shape.
 */
import { useEffect, useRef, useState } from "react";

export const FAMILY_OPTIONS: { slug: string; label: string }[] = [
  { slug: "cuprate",       label: "Cuprate" },
  { slug: "iron_based",    label: "Iron-based" },
  { slug: "nickelate",     label: "Nickelate" },
  { slug: "hydride",       label: "Hydride" },
  { slug: "mgb2",          label: "MgB₂" },
  { slug: "heavy_fermion", label: "Heavy fermion" },
  { slug: "fulleride",     label: "Fulleride" },
  { slug: "conventional",  label: "Conventional" },
];

const LABEL_BY_SLUG: Record<string, string> = Object.fromEntries(
  FAMILY_OPTIONS.map((o) => [o.slug, o.label]),
);

export function FamilyMultiSelect({
  value,
  onChange,
}: {
  value: string[];
  onChange: (v: string[]) => void;
}) {
  const [open, setOpen] = useState(false);
  const rootRef = useRef<HTMLDivElement | null>(null);

  // Close when clicking anywhere outside the component.
  useEffect(() => {
    if (!open) return;
    function onDown(e: MouseEvent) {
      if (!rootRef.current) return;
      if (!rootRef.current.contains(e.target as Node)) setOpen(false);
    }
    function onKey(e: KeyboardEvent) {
      if (e.key === "Escape") setOpen(false);
    }
    document.addEventListener("mousedown", onDown);
    document.addEventListener("keydown", onKey);
    return () => {
      document.removeEventListener("mousedown", onDown);
      document.removeEventListener("keydown", onKey);
    };
  }, [open]);

  function toggle(slug: string) {
    if (value.includes(slug)) {
      onChange(value.filter((s) => s !== slug));
    } else {
      onChange([...value, slug]);
    }
  }

  const label =
    value.length === 0
      ? "All families"
      : value.length === 1
        ? LABEL_BY_SLUG[value[0]] ?? value[0]
        : `${value.length} families`;

  return (
    <div ref={rootRef} className="relative">
      <button
        type="button"
        onClick={() => setOpen((o) => !o)}
        aria-haspopup="listbox"
        aria-expanded={open}
        className="flex w-44 items-center justify-between gap-2 rounded border border-slate-300 bg-white px-2 py-1 text-left text-sm"
      >
        <span className={value.length === 0 ? "text-slate-500" : "text-slate-900"}>
          {label}
        </span>
        <Chevron open={open} />
      </button>
      {open && (
        <div
          role="listbox"
          className="absolute z-20 mt-1 w-56 rounded-md border border-sage-border bg-white p-2 shadow-sage-lg"
        >
          <ul className="max-h-64 overflow-y-auto">
            {FAMILY_OPTIONS.map((opt) => {
              const checked = value.includes(opt.slug);
              return (
                <li key={opt.slug}>
                  <label className="flex cursor-pointer items-center gap-2 rounded-md px-2 py-1.5 text-sm hover:bg-[rgba(58,125,92,0.06)]">
                    <input
                      type="checkbox"
                      checked={checked}
                      onChange={() => toggle(opt.slug)}
                      className="h-4 w-4 rounded border-slate-300 accent-[color:var(--accent,#3A7D5C)]"
                    />
                    <span className="text-sage-ink">{opt.label}</span>
                  </label>
                </li>
              );
            })}
          </ul>
          {value.length > 0 && (
            <button
              type="button"
              onClick={() => onChange([])}
              className="mt-1 w-full rounded-md border-t border-sage-border pt-2 text-xs text-sage-muted hover:text-accent-deep"
            >
              Clear ({value.length})
            </button>
          )}
        </div>
      )}
    </div>
  );
}

function Chevron({ open }: { open: boolean }) {
  return (
    <svg
      viewBox="0 0 16 16"
      width="12"
      height="12"
      aria-hidden="true"
      className={`text-slate-500 transition-transform ${open ? "rotate-180" : ""}`}
    >
      <path
        d="M4 6l4 4 4-4"
        fill="none"
        stroke="currentColor"
        strokeWidth="1.5"
        strokeLinecap="round"
        strokeLinejoin="round"
      />
    </svg>
  );
}
