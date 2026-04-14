/**
 * /materials — browse the materials DB. Server component; the
 * search params drive the API call so refresh / share preserves
 * the exact filter state.
 */
import { listMaterials } from "@/lib/api";
import { MaterialTable } from "@/components/MaterialTable";

type Sp = { family?: string; tc_min?: string; sort?: string; page?: string };

const PAGE_SIZE = 50;

export default async function MaterialsPage({
  searchParams,
}: {
  searchParams: Sp;
}) {
  const page = Math.max(0, Number(searchParams.page ?? "0"));
  const sort =
    (searchParams.sort as "tc_max" | "discovery_year" | "total_papers") ??
    "tc_max";

  const data = await listMaterials({
    family: searchParams.family || undefined,
    tc_min: searchParams.tc_min ? Number(searchParams.tc_min) : undefined,
    sort,
    limit: PAGE_SIZE,
    offset: page * PAGE_SIZE,
  }).catch(() => null);

  return (
    <main className="space-y-6">
      <div>
        <h1 className="text-3xl font-bold tracking-tight">Materials</h1>
        <p className="mt-1 text-sm text-slate-600">
          Aggregated Tc records per compound. Sort by max Tc, year, or
          literature coverage.
        </p>
      </div>

      <form className="flex flex-wrap items-end gap-3 rounded-lg border border-slate-200 bg-white p-4 text-sm">
        <label className="flex flex-col gap-1">
          <span className="text-xs font-medium uppercase tracking-wide text-slate-500">
            Family
          </span>
          <input
            name="family"
            defaultValue={searchParams.family ?? ""}
            className="rounded border border-slate-300 px-2 py-1"
            placeholder="cuprate, iron, hydride..."
          />
        </label>
        <label className="flex flex-col gap-1">
          <span className="text-xs font-medium uppercase tracking-wide text-slate-500">
            Tc ≥ (K)
          </span>
          <input
            type="number"
            name="tc_min"
            defaultValue={searchParams.tc_min ?? ""}
            className="w-24 rounded border border-slate-300 px-2 py-1"
          />
        </label>
        <label className="flex flex-col gap-1">
          <span className="text-xs font-medium uppercase tracking-wide text-slate-500">
            Sort
          </span>
          <select
            name="sort"
            defaultValue={sort}
            className="rounded border border-slate-300 px-2 py-1"
          >
            <option value="tc_max">Tc max</option>
            <option value="discovery_year">Discovery year</option>
            <option value="total_papers">Paper count</option>
          </select>
        </label>
        <button
          type="submit"
          className="rounded-md bg-slate-900 px-4 py-1.5 font-medium text-white hover:bg-slate-700"
        >
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
        </>
      )}
    </main>
  );
}
