import { createHash } from "node:crypto";
import accessWire from "../../fixtures/discovery-selection/selection-access.response.wire.json";
import contextWire from "../../fixtures/discovery-selection/selection-context.response.wire.json";
import prepareRequestWire from "../../fixtures/discovery-selection/selection-prepare.request.wire.json";
import preparedWire from "../../fixtures/discovery-selection/selection-prepare.response.wire.json";
import previewWire from "../../fixtures/discovery-selection/register-preview.response.wire.json";
import commitWire from "../../fixtures/discovery-selection/register-commit.response.wire.json";
import outcomeWire from "../../fixtures/discovery-selection/original-outcome.response.wire.json";
import sourceWire from "../../fixtures/discovery-selection/source.public-bundle.wire.json";
import absentWire from "../../fixtures/discovery-selection/original-outcome-absent.response.wire.json";
import { parsePreparedSelection, parseSelectionAccess, parseSelectionContext, type SelectionRequest } from "@/lib/discovery-selection";

export const wires = { accessWire, contextWire, prepareRequestWire, preparedWire, previewWire, commitWire, outcomeWire, sourceWire, absentWire };
export const hash = (value: string) => createHash("sha256").update(value).digest("hex");
export const requestFixture = () => JSON.parse(prepareRequestWire) as SelectionRequest;
export async function verifiedFixture() {
  const request = requestFixture(), access = parseSelectionAccess(accessWire);
  const context = await parseSelectionContext(contextWire, access, request.source);
  const prepared = await parsePreparedSelection(preparedWire, access, context, request);
  return { request, access, context, prepared };
}
/** Synthetic client transport adapter, NOT another captured backend response.
 * Only changes an opaque request key (excluded from backend request SHA).
 * All original quantity-bearing JSON fragments remain byte-for-byte intact. */
export function withRequestKey(key: string) {
  const response = JSON.parse(preparedWire), old = JSON.stringify(response.request_key), next = JSON.stringify(key);
  response.request_key = key;
  response.preview_json = response.preview_json.replace(old, next);
  response.commit_json = response.commit_json.replace(old, next);
  response.preview_sha256 = hash(response.preview_json); response.commit_sha256 = hash(response.commit_json);
  return JSON.stringify(response);
}
