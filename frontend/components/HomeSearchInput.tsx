"use client";
import { useSearchParams } from "next/navigation";
import { SearchBar } from "@/components/SearchBar";
export function HomeSearchInput() {
  const query = useSearchParams().get("q") ?? "";
  // The dynamic home page renders this input once. An editable Suspense
  // fallback can discard a query when React replaces it with the real form.
  return <SearchBar key={query} initial={query} placeholder="Paper, wiki concept, material, or research question" />;
}
