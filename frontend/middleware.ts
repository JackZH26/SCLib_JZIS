import { NextRequest, NextResponse } from "next/server";
import { isPrivatePage, legacyDestination } from "./lib/site-routes";

export function middleware(request: NextRequest) {
  const url = request.nextUrl.clone();
  const path = url.pathname;
  const rootBuild = !process.env.NEXT_PUBLIC_BASE_PATH;
  // Standalone Next.js may construct nextUrl with its loopback hostname.
  // Nginx forwards the original Host; only these two owned hosts are canonicalized.
  const hostname = (request.headers.get("host") || url.host).toLowerCase();
  const canonicalHost = rootBuild && hostname === "www.jzis.org";
  const destination = rootBuild ? legacyDestination(path) : null;
  const privatePage = isPrivatePage(path) || isPrivatePage(destination || "");
  let response: NextResponse;
  if (destination || canonicalHost) {
    // Changing pathname does not decode/re-encode opaque IDs or discard queries.
    if (destination) url.pathname = destination;
    if (canonicalHost || hostname === "jzis.org") { url.hostname = "jzis.org"; url.protocol = "https:"; url.port = ""; }
    response = NextResponse.redirect(url, privatePage ? 307 : 308);
  } else if (rootBuild && path.startsWith("/sclib/_next/")) {
    url.pathname = path.slice(6);
    response = NextResponse.rewrite(url);
  } else {
    response = NextResponse.next();
  }
  if (privatePage) {
    response.headers.set("Cache-Control", "private, no-store, max-age=0");
    response.headers.set("Referrer-Policy", "no-referrer");
    response.headers.set("X-Robots-Tag", "noindex, nofollow");
  }
  return response;
}

export const config = { matcher: ["/((?!_next/static|_next/image|favicon.ico).*)"] };
