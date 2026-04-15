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

module.exports = {
  reactStrictMode: true,
  output: "standalone",
  basePath,
  experimental: { instrumentationHook: false },
};
