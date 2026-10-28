/** Test-server preload. Installed packages are retained; external fetches are not
 * needed for source review QA. In particular, Next's development version check
 * otherwise awaits the npm registry without a request timeout during startup.
 * This changes only the isolated child process, not application fetch behavior.
 */
if (!/^[1-9][0-9]{3,4}$/.test(process.env.SCLIB_REVIEW_E2E_PORT || "")) {
  throw new Error("Offline fetch preload requires the isolated review server");
}
const originalFetch = globalThis.fetch;
globalThis.fetch = async function offlineReviewFetch(input, options) {
  const url = new URL(typeof input === "string" || input instanceof URL ? input : input.url);
  if (!["127.0.0.1", "localhost", "[::1]"].includes(url.hostname)) {
    console.log(`Isolated review blocked external fetch: ${url.origin}${url.pathname}`);
    throw new Error("External fetch is unavailable in offline review QA");
  }
  return originalFetch(input, options);
};
