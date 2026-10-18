import {discoveryIndex} from "@/lib/scwiki/library";
import {searchIndex,revisionHeaders} from "@/lib/scwiki/catalogue";
export const dynamic="force-static";
export function GET(){const index=discoveryIndex(searchIndex());return Response.json(index,{headers:revisionHeaders(index.revision)});}
