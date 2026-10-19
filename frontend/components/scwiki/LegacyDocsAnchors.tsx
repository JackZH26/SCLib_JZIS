"use client";
import {useEffect} from "react";
import {useRouter} from "next/navigation";
const anchors=new Set(["search-the-literature","explore-materials-and-reported-tc","interpret-research-leads","coverage-and-methodology","your-account"]);
export function LegacyDocsAnchors(){
 const router=useRouter();
 useEffect(()=>{const id=window.location.hash.slice(1);if(anchors.has(id))router.replace("/scwiki/using-sclib"+window.location.search+"#"+id);},[router]);
 return null;
}
