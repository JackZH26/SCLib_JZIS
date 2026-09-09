import { createHash } from "node:crypto";
import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { parseGovernanceHeader, parseOperatorAccess, parseReviewPage, verifyCompleteHistory } from "@/lib/discovery-governance";

export const governanceWire = (name: string): string => JSON.parse(readFileSync(resolve(process.cwd(), "tests/fixtures/discovery-governance", name), "utf8"));
export const governanceHash = (raw: string) => createHash("sha256").update(raw).digest("hex");
export type Phase = "initial" | "approved" | "published" | "held" | "rejected" | "withdrawn";
export const packageId = JSON.parse(governanceWire("initial-governance.response.wire.json")).package.id as string;
export function historyWire(phase: Phase, kind: "governance" | "reviews", actor: "reviewer" | "publisher" = "reviewer") {
  return governanceWire(`${phase}-${actor === "publisher" ? "publisher-" : ""}${kind}.response.wire.json`);
}
export function operationRequest(operation: "approve" | "reject" | "publish" | "withdraw") {
  return JSON.parse(governanceWire(`${operation === "approve" || operation === "reject" ? "review-" : ""}${operation}-commit.request.wire.json`));
}
export async function governanceFixture(phase: Phase = "initial", actor: "reviewer" | "publisher" = "reviewer") {
  const access = parseOperatorAccess(governanceWire(`${actor}-access.response.wire.json`));
  const header = parseGovernanceHeader(historyWire(phase, "governance", actor), access, packageId);
  const page = parseReviewPage(historyWire(phase, "reviews", actor), access, header, null);
  await verifyCompleteHistory(header, page.reviews);
  return { access, header, page };
}
