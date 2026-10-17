import {searchIndex,revisionHeaders} from "@/lib/scwiki/catalogue";
export const dynamic="force-static";
export function GET(){return Response.json(searchIndex(),{headers:revisionHeaders()});}
