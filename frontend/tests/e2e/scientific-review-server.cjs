/** Isolated test server: copied source, linked installed dependencies, no installs.
 * The normal frontend/.next and any existing server are untouched. Temporary
 * copies remain in the OS temporary directory for diagnosis, not in git.
 */
const { cpSync, mkdtempSync, symlinkSync } = require("node:fs");
const { tmpdir } = require("node:os");
const path = require("node:path");
const { spawn } = require("node:child_process");

const port = process.env.SCLIB_REVIEW_E2E_PORT;
if (!/^[1-9][0-9]{3,4}$/.test(port || "") || Number(port) > 65535) throw new Error("Invalid isolated test port");
const original = path.resolve(__dirname, "../..");
const isolated = mkdtempSync(path.join(tmpdir(), "sclib-review-browser-workspace-"));
for (const entry of ["app", "components", "lib", "public", "package.json", "tsconfig.json", "next-env.d.ts",
  "middleware.ts", "next.config.js", "postcss.config.js", "tailwind.config.ts"]) {
  cpSync(path.join(original, entry), path.join(isolated, entry), { recursive: true });
}
symlinkSync(path.join(original, "node_modules"), path.join(isolated, "node_modules"), "dir");
const child = spawn(process.execPath, [path.join(original, "node_modules/next/dist/bin/next"), "dev",
  "--hostname", "127.0.0.1", "--port", port], {
  cwd: isolated,
  stdio: "inherit",
  env: { ...process.env, NODE_ENV: "development", NEXT_TELEMETRY_DISABLED: "1", NEXT_PUBLIC_BASE_PATH: "",
    NEXT_PUBLIC_API_BASE: `http://127.0.0.1:${port}/__synthetic_api/v1`, API_BASE_SERVER: "http://127.0.0.1:1/inert/v1",
    NEXT_FONT_GOOGLE_MOCKED_RESPONSES: path.join(__dirname, "scientific-review-offline-fonts.cjs") },
});
console.log(`Isolated scientific review workspace: ${isolated}`);
for (const signal of ["SIGTERM", "SIGINT"]) process.on(signal, () => child.kill(signal));
child.on("exit", code => process.exit(code ?? 0));
