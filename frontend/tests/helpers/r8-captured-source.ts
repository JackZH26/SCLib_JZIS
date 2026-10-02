/** Historical R8 provenance only; this does not recapture the current backend. */
import { execFileSync } from "node:child_process";
import { createHash } from "node:crypto";
import { resolve } from "node:path";
import captured from "../fixtures/ml-use-rights-native.materials20261002r8.wire.json";

export const R8_CAPTURE_SOURCE_REVISION = "748bb23710b409ebb927806e945048bd2608e5ec";
const originalPins = new Map(captured.source_pins.map(pin => [pin.path, pin.sha256]));
const repository = resolve(process.cwd(), "..");

function git(args: string[], input?: string): Buffer {
  return execFileSync("git", args, {
    cwd: repository, input, maxBuffer: 64 * 1024 * 1024, stdio: ["pipe", "pipe", "pipe"],
  });
}

type GitReader = (args: string[], input?: string) => Buffer;

function requireCaptureAncestor(runGit: GitReader) {
  try {
    const revision = runGit(["rev-parse", "--verify", `${R8_CAPTURE_SOURCE_REVISION}^{commit}`]).toString("utf8").trim();
    if (revision !== R8_CAPTURE_SOURCE_REVISION) throw new Error("Unexpected capture revision");
  } catch {
    throw new Error("The fixed R8 capture source revision is unavailable; full checkout history is required");
  }
  try {
    runGit(["merge-base", "--is-ancestor", R8_CAPTURE_SOURCE_REVISION, "HEAD"]);
  } catch {
    throw new Error("The fixed R8 capture source revision is not an ancestor of this checkout");
  }
}

function checkedPin(pin: unknown): { path: string; sha256: string } {
  if (!pin || typeof pin !== "object" || Array.isArray(pin)) throw new Error("Invalid captured source pin");
  const row = pin as Record<string, unknown>;
  if (Object.keys(row).sort().join(",") !== "path,sha256" || typeof row.path !== "string" || typeof row.sha256 !== "string"
    || !/^(api|scripts)\/[A-Za-z0-9_./-]+\.(py|schema\.json)$/.test(row.path)
    || row.path.split("/").some(part => part === "" || part === "." || part === "..")
    || !/^[0-9a-f]{64}$/.test(row.sha256) || originalPins.get(row.path) !== row.sha256) {
    throw new Error("Unknown, unsafe or altered R8 captured source pin");
  }
  return { path: row.path, sha256: row.sha256 };
}

/** Each session uses the same fixed revision and complete finite pin registry. */
export function createHistoricalR8Reader(runGit: GitReader = git): (pin: unknown) => Buffer {
  let sources: Map<string, Buffer> | null = null;
  return (pin: unknown) => {
    const row = checkedPin(pin);
    if (!sources) {
      requireCaptureAncestor(runGit);
      let batch: Buffer;
      try {
        batch = runGit(["cat-file", "--batch"], [...originalPins.keys()]
          .map(path => `${R8_CAPTURE_SOURCE_REVISION}:${path}\n`).join(""));
      } catch {
        throw new Error("Captured source blobs are unavailable");
      }
      const verified = new Map<string, Buffer>();
      let offset = 0;
      for (const [path, digest] of originalPins) {
        const end = batch.indexOf(10, offset);
        if (end < offset) throw new Error(`Captured source blob is unavailable: ${path}`);
        const header = batch.subarray(offset, end).toString("ascii").match(/^[0-9a-f]{40} blob ([0-9]+)$/);
        const size = header ? Number(header[1]) : NaN;
        if (!Number.isSafeInteger(size) || size < 0 || size > 8 * 1024 * 1024
          || end + 1 + size >= batch.length || batch[end + 1 + size] !== 10) {
          throw new Error(`Captured source blob is unavailable: ${path}`);
        }
        const bytes = batch.subarray(end + 1, end + 1 + size);
        if (createHash("sha256").update(bytes).digest("hex") !== digest) {
          throw new Error(`Captured source blob does not match its original pin: ${path}`);
        }
        verified.set(path, bytes);
        offset = end + 2 + size;
      }
      if (offset !== batch.length) throw new Error("Unexpected data after captured source blobs");
      sources = verified;
    }
    return Buffer.from(sources.get(row.path)!);
  };
}

export const historicalR8Source = createHistoricalR8Reader();
