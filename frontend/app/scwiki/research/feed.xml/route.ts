import {researchCollection,researchRss} from "@/lib/scwiki/research";
export const dynamic="force-dynamic";
export function GET(){return new Response(researchRss(researchCollection()),{headers:{"Content-Type":"application/rss+xml; charset=utf-8","Cache-Control":"public, max-age=60","X-Content-Type-Options":"nosniff"}});}
