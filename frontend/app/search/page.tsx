import { redirect } from "next/navigation";

/** Preserve bookmarked searches while making Home the single search destination. */
export default async function LegacySearch({ searchParams }: {
  searchParams: Promise<Record<string, string | string[] | undefined>>;
}) {
  const params = await searchParams;
  const query = new URLSearchParams();
  for (const [key, value] of Object.entries(params)) {
    for (const item of Array.isArray(value) ? value : value === undefined ? [] : [value]) query.append(key, item);
  }
  redirect(query.size ? "/?" + query.toString() : "/");
}
