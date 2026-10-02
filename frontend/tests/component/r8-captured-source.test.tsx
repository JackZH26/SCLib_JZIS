import { execFileSync } from "node:child_process";
import { createHash } from "node:crypto";
import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { beforeEach, describe, expect, it, vi } from "vitest";
import captured from "../fixtures/ml-use-rights-native.materials20261002r8.wire.json";

const pin = captured.source_pins.find(row => row.path === "api/config.py")!;
const digest = (bytes: Buffer) => createHash("sha256").update(bytes).digest("hex");
const actualGit = (args: string[], input?: string): Buffer => execFileSync("git", args, {
  cwd: resolve(process.cwd(), ".."), input, maxBuffer: 64 * 1024 * 1024, stdio: ["pipe", "pipe", "pipe"],
});
const runGit = vi.fn(actualGit);
async function reader() {
  const module = await import("../helpers/r8-captured-source");
  return { ...module, historicalR8Source: module.createHistoricalR8Reader(runGit) };
}
beforeEach(() => { runGit.mockReset().mockImplementation(actualGit); });

describe("historical R8 captured source provenance", () => {
  it("verifies the fixed ancestor bytes while keeping intentional current S01 changes distinct", async () => {
    const { historicalR8Source, R8_CAPTURE_SOURCE_REVISION } = await reader();
    const bytes = historicalR8Source(pin);
    expect(digest(bytes)).toBe(pin.sha256);
    expect(digest(readFileSync(resolve(process.cwd(), "..", pin.path)))).not.toBe(pin.sha256);
    expect(runGit).toHaveBeenCalledWith(["merge-base", "--is-ancestor", R8_CAPTURE_SOURCE_REVISION, "HEAD"]);
    expect(runGit).toHaveBeenCalledWith(["cat-file", "--batch"],
      captured.source_pins.map(row => `${R8_CAPTURE_SOURCE_REVISION}:${row.path}\n`).join(""));
    bytes.fill(0); expect(digest(historicalR8Source(pin))).toBe(pin.sha256);
  });
  it.each([null, [], { ...pin, private_notes: "extra" }, { ...pin, sha256: "f".repeat(64) },
    { ...pin, path: "api/../config.py" }, { ...pin, path: "api//config.py" }, { ...pin, path: "api/config.py:HEAD" },
    { ...pin, path: "api/unknown.py" }])("rejects altered or unsafe source pins before any Git read: %j", async value => {
    const { historicalR8Source } = await reader();
    expect(() => historicalR8Source(value)).toThrow(); expect(runGit).not.toHaveBeenCalled();
  });
  it("fails closed when the fixed revision is absent instead of falling back to disk or another commit", async () => {
    runGit.mockImplementation(() => { throw new Error("missing revision"); });
    const { historicalR8Source } = await reader();
    expect(() => historicalR8Source(pin)).toThrow(/fixed R8 capture source revision is unavailable/);
    expect(runGit).toHaveBeenCalledOnce();
  });
  it("requires capture ancestry before looking up any source blob", async () => {
    runGit.mockImplementation((args, input) => {
      if (args?.[0] === "merge-base") throw new Error("not ancestor");
      return actualGit(args, input);
    });
    const { historicalR8Source } = await reader();
    expect(() => historicalR8Source(pin)).toThrow(/not an ancestor/);
    expect(runGit.mock.calls.some(([args]) => args[0] === "cat-file")).toBe(false);
  });
  it("fails closed for a missing captured blob without using its current file", async () => {
    runGit.mockImplementation((args, input) => {
      if (args?.[0] === "cat-file") return Buffer.from("unavailable source missing\n");
      return actualGit(args, input);
    });
    const { historicalR8Source } = await reader();
    expect(() => historicalR8Source(pin)).toThrow(/Captured source blob is unavailable/);
  });
  it("rejects altered blob bytes even if revision and ancestry commands succeeded", async () => {
    runGit.mockImplementation((args, input) => {
      const result = actualGit(args, input);
      if (args?.[0] !== "cat-file") return result;
      const altered = Buffer.from(result); let offset = 0;
      while (offset < altered.length) {
        const end = altered.indexOf(10, offset), size = Number(altered.subarray(offset, end).toString("ascii").split(" ")[2]);
        if (size > 0) { altered[end + 1] ^= 1; break; }
        offset = end + size + 2;
      }
      return altered;
    });
    const { historicalR8Source } = await reader();
    expect(() => historicalR8Source(pin)).toThrow(/does not match its original pin/);
  });
  it("refuses trailing batch data after all original source blobs", async () => {
    runGit.mockImplementation((args, input) => {
      const result = actualGit(args, input);
      return args?.[0] === "cat-file" ? Buffer.concat([Buffer.from(result), Buffer.from("extra")]) : result;
    });
    const { historicalR8Source } = await reader();
    expect(() => historicalR8Source(pin)).toThrow(/Unexpected data after captured source blobs/);
  });
});
