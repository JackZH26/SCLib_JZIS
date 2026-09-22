/** Create one new output root before Playwright and all of its workers load config. */
const { mkdirSync, mkdtempSync } = require("node:fs");
const { tmpdir } = require("node:os");
const path = require("node:path");
const { spawn } = require("node:child_process");

function prepareOutput(requested) {
  if (requested === undefined) {
    return mkdtempSync(path.join(tmpdir(), "sclib-research-browser-artifacts-"));
  }
  if (!path.isAbsolute(requested)) {
    throw new Error("Research browser output must be an absolute new directory.");
  }
  // Exclusive creation preserves earlier runs and rejects existing symlinks.
  mkdirSync(requested, { mode: 0o700 });
  return requested;
}

function main() {
  const args = process.argv.slice(2);
  if (args.length && !(args.length === 1 && args[0] === "--list")) {
    throw new Error("Only --list is supported; the CI launcher always selects the full suite.");
  }
  const artifacts = prepareOutput(process.env.SCLIB_RESEARCH_BROWSER_OUTPUT);
  console.log(`Research browser artifacts: ${artifacts}`);
  const child = spawn(process.execPath, [require.resolve("@playwright/test/cli"), "test",
    "--config", path.join(__dirname, "research-workbenches.config.ts"), ...args], {
    cwd: path.resolve(__dirname, "../.."),
    env: { ...process.env, SCLIB_RESEARCH_BROWSER_OUTPUT: artifacts },
    stdio: "inherit",
  });
  for (const signal of ["SIGINT", "SIGTERM"]) {
    process.on(signal, () => child.kill(signal));
  }
  child.on("error", () => { process.exitCode = 1; });
  child.on("exit", code => { process.exitCode = code ?? 1; });
}

module.exports = { prepareOutput };
if (require.main === module) main();
