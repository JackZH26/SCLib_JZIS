"use client";
import { Suspense } from "react";
import { useSearchParams } from "next/navigation";
import { SearchBar } from "@/components/SearchBar";
function Input() {
  const query = useSearchParams().get("q") ?? "";
  return <SearchBar key={query} initial={query} placeholder="Paper, wiki concept, material, or research question" />;
}
export function HomeSearchInput() {
  return <Suspense fallback={<SearchBar placeholder="Paper, wiki concept, material, or research question" />}><Input /></Suspense>;
}
