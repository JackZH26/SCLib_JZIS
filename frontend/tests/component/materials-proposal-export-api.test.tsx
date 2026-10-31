import { afterEach, expect, it, vi } from "vitest";
import { webcrypto, createHash } from "node:crypto";
import { materialsProposalExportFile } from "@/lib/api";

afterEach(() => vi.unstubAllGlobals());
const bytes = new Uint8Array([80, 75, 3, 4, 0, 7]), run = "a".repeat(64);
const hash = createHash("sha256").update(bytes).digest("hex");
function reply(body = bytes, type = "application/zip") {
  vi.stubGlobal("crypto", webcrypto);
  vi.stubGlobal("fetch", vi.fn().mockResolvedValue(new Response(body, { headers: { "content-type": type } })));
}
it("checks exact download length and SHA-256 and uses current cookies without caching", async () => {
  reply(); expect(await materialsProposalExportFile(run, hash, bytes.length)).toEqual(bytes);
  expect(fetch).toHaveBeenCalledWith(expect.stringContaining(`expected_sha256=${hash}`), expect.objectContaining({ credentials: "include", cache: "no-store" }));
});
it.each(["hash", "truncated", "oversized", "type"])("rejects a %s response instead of saving a partial review", async problem => {
  reply(bytes, problem === "type" ? "application/json" : "application/zip");
  await expect(materialsProposalExportFile(run, problem === "hash" ? "0".repeat(64) : hash, bytes.length + (problem === "truncated" ? 1 : problem === "oversized" ? -1 : 0))).rejects.toThrow();
});
