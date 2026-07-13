/** @type {import('next').NextConfig} */
// SCLib_JZIS is served under https://jzis.org/sclib in production, so
// Next.js must mint every asset URL (/_next/static/...) and every link
// href under that prefix. basePath handles both. Without it the HTML
// references /_next/static/... absolute-rooted and the browser fetches
// them from https://jzis.org/_next/... which falls through to the main
// jzis.org site → 404 → page renders completely unstyled.
//
// Env override exists so `pnpm dev` at the repo root still works without
// the prefix. The Dockerfile builder sets NEXT_PUBLIC_BASE_PATH=/sclib.
const basePath = process.env.NEXT_PUBLIC_BASE_PATH || "";
const isDevelopment = process.env.NODE_ENV === "development";
let developmentApiOrigin = "";
if (isDevelopment && process.env.NEXT_PUBLIC_API_BASE) {
  try {
    developmentApiOrigin = ` ${new URL(process.env.NEXT_PUBLIC_API_BASE).origin}`;
  } catch {
    // Invalid values are rejected by fetch as well; do not weaken CSP for them.
  }
}

const contentSecurityPolicy = [
  "default-src 'self'",
  `script-src 'self' 'unsafe-inline'${isDevelopment ? " 'unsafe-eval'" : ""} https://www.googletagmanager.com`,
  "style-src 'self' 'unsafe-inline'",
  "img-src 'self' data: blob: https://lh3.googleusercontent.com https://www.google-analytics.com https://*.google-analytics.com",
  "font-src 'self' data:",
  `connect-src 'self' https://api.jzis.org https://www.googletagmanager.com https://www.google-analytics.com https://*.google-analytics.com${developmentApiOrigin}`,
  "worker-src 'self' blob:",
  "manifest-src 'self'",
  "media-src 'none'",
  "object-src 'none'",
  "base-uri 'self'",
  "form-action 'self'",
  "frame-src 'none'",
  "frame-ancestors 'none'",
].join("; ");

const securityHeaders = [
  {
    key: "Content-Security-Policy",
    value: contentSecurityPolicy,
  },
  {
    key: "Strict-Transport-Security",
    value: "max-age=63072000; includeSubDomains",
  },
  {
    key: "X-Content-Type-Options",
    value: "nosniff",
  },
  {
    key: "X-Frame-Options",
    value: "DENY",
  },
  {
    key: "Referrer-Policy",
    value: "strict-origin-when-cross-origin",
  },
  {
    key: "Permissions-Policy",
    value: "camera=(), microphone=(), geolocation=(), browsing-topics=()",
  },
];

module.exports = {
  reactStrictMode: true,
  output: "standalone",
  outputFileTracingRoot: __dirname,
  basePath,
  async headers() {
    return [
      {
        source: "/:path*",
        headers: securityHeaders,
      },
    ];
  },
};
