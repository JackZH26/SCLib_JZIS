import {NextRequest,NextResponse} from "next/server";
import {isPrivatePage,legacyDestination} from "./lib/site-routes";

export function middleware(request:NextRequest){
 const url=request.nextUrl.clone();
 const path=url.pathname;
 const rootBuild=!process.env.NEXT_PUBLIC_BASE_PATH;
 const hostname=(request.headers.get("host")||url.host).toLowerCase();
 const canonicalHost=rootBuild&&hostname==="www.jzis.org";
 const destination=rootBuild?legacyDestination(path):null;
 const privatePage=isPrivatePage(path)||isPrivatePage(destination||"");
 let response:NextResponse;
 if(destination||canonicalHost){
  // A standard URL does not retain NextURL's original trailing-slash state.
  // Preserve opaque path segments and queries without decoding/re-encoding them.
  const redirectUrl=new URL(request.url);
  if(destination)redirectUrl.pathname=destination;
  if(canonicalHost||hostname==="jzis.org"){
   redirectUrl.hostname="jzis.org";redirectUrl.protocol="https:";redirectUrl.port="";
  }else if(/^(?:localhost|127\.0\.0\.1|\[::1\])(?::\d{1,5})?$/.test(hostname)){
   // Owned loopback previews must retain the browser's origin, not Next's
   // internal localhost hostname. Arbitrary Host headers are not trusted.
   redirectUrl.host=hostname;
  }
  response=NextResponse.redirect(redirectUrl,privatePage?307:308);
 }else if(rootBuild&&path.startsWith("/sclib/_next/")){
  url.pathname=path.slice(6);response=NextResponse.rewrite(url);
 }else response=NextResponse.next();
 if(privatePage){
  response.headers.set("Cache-Control","private, no-store, max-age=0");
  response.headers.set("Referrer-Policy","no-referrer");
  response.headers.set("X-Robots-Tag","noindex, nofollow");
 }
 return response;
}
export const config={matcher:["/((?!_next/static|_next/image|favicon.ico).*)"]};
