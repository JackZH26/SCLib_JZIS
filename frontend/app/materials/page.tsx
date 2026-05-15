/**
 * /materials — browse the materials DB. Server component; the
 * search params drive the API call so refresh / share preserves
 * the exact filter state.
 *
 * v2 adds filter controls for the boolean flags (ambient_sc,
 * is_unconventional, has_competing_order) plus pairing_symmetry / structure_phase
 * dropdowns. Everything round-trips via URL query params so the
 * page stays SSR-friendly and shareable.
 */
import { listMaterials, type MaterialListParams } from "@/lib/api";
import { MaterialTable } from "@/components/MaterialTable";
import { Pagination } from "@/components/Pagination";
import { FamilyFilterField } from "@/components/FamilyFilterField";

type Sp = {
  family?: string;
  tc_min?: string;
  sort?: string;
  page?: string;
  per_page?: string;
  ambient_sc?: string;
  is_unconventional?: string;
  has_competing_order?: string;
  pairing_symmetry?: string;
  structure_phase?: string;
  include_skeletons?: string;
};

const DEFAULT_PAGE_SIZE = 50;
const ALLOWED_PAGE_SIZES = new Set([25, 50, 100, 200]);

/** Clamp an arbitrary `per_page` URL value to a safe, allowed size. */
function resolvePageSize(raw: string | undefined): number {
  const n = Number(raw);
  if (!Number.isFinite(n) || n <= 0) return DEFAULT_PAGE_SIZE;
  return ALLOWED_PAGE_SIZES.has(n) ? n : DEFAULT_PAGE_SIZE;
}

/** URL "true"/"false"/"" → boolean | undefined. */
function parseTri(v: string | undefined): boolean | undefined {
  if (v === "true") return true;
  if (v === "false") return false;
  return undefined;
}

export default async function MaterialsPage({
  searchParams,
}: {
  searchParams: Sp;
}) {
  const page = Math.max(0, Number(searchParams.page ?? "0"));
  const perPage = resolvePageSize(searchParams.per_page);
  const sort =
    (searchParams.sort as MaterialListParams["sort"]) ?? "tc_max";

  const includeSkeletons = searchParams.include_skeletons === "true";

  const params: MaterialListParams = {
    family: searchParams.family || undefined,
    tc_min: searchParams.tc_min ? Number(searchParams.tc_min) : undefined,
    ambient_sc: parseTri(searchParams.ambient_sc),
    is_unconventional: parseTri(searchParams.is_unconventional),
    has_competing_order: parseTri(searchParams.has_competing_order),
    pairing_symmetry: searchParams.pairing_symmetry || undefined,
    structure_phase: searchParams.structure_phase || undefined,
    sort,
    limit: perPage,
    offset: page * perPage,
    include_skeletons: includeSkeletons,
  };

  const data = await listMaterials(params).catch(() => null);

  // Small helper: render a tri-state select for boolean filters.
  const triOptions = (
    name: keyof Sp,
    label: string,
    current: string | undefined,
  ) => (
    <label key={name} className="flex flex-col gap-1">
      <span className="text-xs font-medium uppercase tracking-wide text-slate-500">
        {label}
      </span>
      <select
        name={name}
        defaultValue={current ?? ""}
        className="rounded border border-sage-border bg-white px-2 py-1"
      >
        <option value="">any</option>
        <option value="true">yes</option>
        <option value="false">no</option>
      </select>
    </label>
  );

  return (
    <main className="space-y-6">
      <div>
        <h1 className="text-3xl font-bold tracking-tight">Materials</h1>
        <p className="mt-1 text-sm text-slate-600">
          Aggregated per-compound records: Tc, pairing, structure phase,
          competing orders, and literature coverage. Filters combine with
          AND semantics.
        </p>
      </div>

      <form className="flex flex-wrap items-end gap-3 rounded-lg border border-sage-border bg-white p-4 text-sm shadow-sage">
        <label className="flex flex-col gap-1">
          <span className="text-xs font-medium uppercase tracking-wide text-slate-500">
            Family
          </span>
          <FamilyFilterField initial={searchParams.family ?? ""} />
        </label>
        <label className="flex flex-col gap-1">
          <span className="text-xs font-medium uppercase tracking-wide text-slate-500">
            Tc ≥ (K)
          </span>
          <input
            type="number"
            name="tc_min"
            defaultValue={searchParams.tc_min ?? ""}
            className="w-24 rounded border border-sage-border px-2 py-1"
          />
        </label>
        <label className="flex flex-col gap-1">
          <span className="text-xs font-medium uppercase tracking-wide text-slate-500">
            Pairing
          </span>
          <select
            name="pairing_symmetry"
            defaultValue={searchParams.pairing_symmetry ?? ""}
            className="rounded border border-sage-border bg-white px-2 py-1"
          >
            <option value="">any</option>
            <option value="s-wave">s-wave</option>
            <option value="s±">s±</option>
            <option value="d-wave">d-wave</option>
            <option value="p-wave">p-wave</option>
            <option value="chiral">chiral</option>
            <option value="nodal">nodal</option>
          </select>
        </label>
        <label className="flex flex-col gap-1">
          <span className="text-xs font-medium uppercase tracking-wide text-slate-500">
            Phase
          </span>
          <input
            name="structure_phase"
            defaultValue={searchParams.structure_phase ?? ""}
            className="rounded border border-sage-border px-2 py-1 w-32"
            placeholder="e.g. RP_n=1, 1212"
          />
        </label>

        {triOptions("ambient_sc", "Ambient", searchParams.ambient_sc)}
        {triOptions(
          "is_unconventional",
          "Unconv.",
          searchParams.is_unconventional,
        )}
        {triOptions(
          "has_competing_order",
          "Comp. order",
          searchParams.has_competing_order,
        )}

        <label className="flex flex-col gap-1">
          <span className="text-xs font-medium uppercase tracking-wide text-slate-500">
            Sort
          </span>
          <select
            name="sort"
            defaultValue={sort}
            className="rounded border border-sage-border bg-white px-2 py-1"
          >
            <option value="tc_max">Tc max</option>
            <option value="tc_ambient">Tc ambient</option>
            <option value="arxiv_year">arXiv year</option>
            <option value="total_papers">Paper count</option>
          </select>
        </label>
        {/*
          Library-only entries are NIMS SuperCon catalog rows that
          arrived with a reference DOI but no measured Tc / pressure /
          structure. Hiding them by default keeps the list feeling
          populated; toggling shows the full index for power users.
        */}
        <label className="flex items-center gap-2 self-end pb-1">
          <input
            type="checkbox"
            name="include_skeletons"
            value="true"
            defaultChecked={includeSkeletons}
            className="h-4 w-4 rounded border-slate-300 accent-[color:var(--accent,#3A7D5C)]"
          />
          <span className="text-xs font-medium text-slate-600">
            Include library-only entries
          </span>
        </label>
        <button type="submit" className="btn-primary">
          Apply
        </button>
      </form>

      {data == null ? (
        <p className="text-sm text-red-600">Failed to load materials.</p>
      ) : (
        <>
          <div className="text-xs text-slate-500">
            {data.total.toLocaleString()} materials
          </div>
          <MaterialTable rows={data.results} />
          <Pagination
            total={data.total}
            limit={perPage}
            offset={page * perPage}
            basePath="/materials"
            searchParams={searchParams}
          />
        </>
      )}
    </main>
  );
}
