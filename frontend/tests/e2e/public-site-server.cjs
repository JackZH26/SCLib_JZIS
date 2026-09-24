/** Production-mode public E2E in an owned copy, never the developer's .next.
 * Fonts are downloaded at build time by the normal Next.js font loader.
 * Browser destinations are independently restricted by public-site-fixture.ts.
 */
const { appendFileSync, cpSync, mkdirSync, mkdtempSync, realpathSync, symlinkSync } = require("node:fs");
const path = require("node:path");
const { spawn } = require("node:child_process");

function childEnvironment(parent) {
  const env = {};
  for (const key of ["PATH", "TMPDIR", "TMP", "TEMP", "LANG", "LC_ALL", "SystemRoot"]) {
    if (parent[key] !== undefined) env[key] = parent[key];
  }
  return { ...env, CI: "1", NODE_ENV: "production", NEXT_TELEMETRY_DISABLED: "1",
    NEXT_PUBLIC_BASE_PATH: "",
    // Preserve public href/CSP semantics; the browser fixture refuses egress.
    NEXT_PUBLIC_API_BASE: "https://api.jzis.org/sclib/v1",
    API_BASE_SERVER: "http://127.0.0.1:1/inert/v1" };
}

function createWorkspace(source) {
  const original = realpathSync(source);
  const workspaceRoot = path.join(original, "tmp");
  mkdirSync(workspaceRoot, { recursive: true, mode: 0o700 });
  const isolated = mkdtempSync(path.join(workspaceRoot, "sclib-public-browser-workspace-"));
  for (const entry of ["app", "components", "lib", "public", "types", "package.json", "tsconfig.json",
    "next-env.d.ts", "middleware.ts", "next.config.js", "postcss.config.js", "tailwind.config.ts"]) {
    cpSync(path.join(original, entry), path.join(isolated, entry), { recursive: true });
  }
  symlinkSync(path.join(original, "node_modules"), path.join(isolated, "node_modules"), "dir");
  // Both source and linked dependencies must be inside the tracing root.
  // Keep standalone output and all production settings in the copied config.
  appendFileSync(path.join(isolated, "next.config.js"),
    `\nmodule.exports.outputFileTracingRoot = ${JSON.stringify(original)};\n`);
  return isolated;
}

function main() {
  const original = realpathSync(path.resolve(__dirname, "../.."));
  const isolated = createWorkspace(original);
  console.log(`Isolated public browser workspace: ${isolated}`);
  const next = path.join(original, "node_modules/next/dist/bin/next");
  const options = { cwd: isolated, stdio: "inherit", env: childEnvironment(process.env) };
  let stopping = false;
  let child;
  function run(args, done) {
    child = spawn(process.execPath, [next, ...args], options);
    child.on("error", () => { process.exitCode = 1; });
    child.on("exit", code => {
      if (!stopping && code === 0 && done) done();
      else process.exitCode = code ?? 1;
    });
  }
  for (const signal of ["SIGINT", "SIGTERM"]) {
    process.on(signal, () => { stopping = true; child?.kill(signal); });
  }
  run(["build"], () => run(["start", "--hostname", "127.0.0.1", "--port", "3102"]));
}

module.exports = { childEnvironment, createWorkspace };
if (require.main === module) main();
