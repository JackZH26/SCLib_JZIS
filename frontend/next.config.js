/** @type {import('next').NextConfig} */
// SCLib_JZIS is served under https://jzis.org/sclib in production.
// basePath lets Next.js mint correct asset URLs behind that prefix.
const basePath = process.env.NEXT_PUBLIC_BASE_PATH || "";

module.exports = {
  reactStrictMode: true,
  output: "standalone",
  basePath,
  experimental: { instrumentationHook: false },
};
