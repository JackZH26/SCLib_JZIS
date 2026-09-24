import { webcrypto } from "node:crypto";

import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import SourceTasksPage from "@/app/dashboard/research/source-tasks/page";
import { ApiError, sourceLifecycleHistory, sourceLifecycleImpact, sourceTaskCapabilities, sourceTaskCommit, sourceTaskExecutionOutcome,
  sourceTaskHistory, sourceTaskPreview, sourceTaskRequestOutcome } from "@/lib/api";
import { notifyAuthChange } from "@/lib/auth-session";
import { knownLifecycleHistory, knownSourceImpact, knownTaskCapabilities, knownTaskHistory, knownTaskOperation, knownTaskPreview, knownTaskReceipt,
  taskOperationSha256, type TaskOperation, type TaskPreview, type TaskReceipt } from "@/lib/source-tasks";
import http from "../fixtures/source-task-operations-http.json";

vi.mock("@/lib/api", async original => ({ ...await original<typeof import("@/lib/api")>(), sourceTaskCapabilities: vi.fn(),
  sourceLifecycleHistory: vi.fn(), sourceLifecycleImpact: vi.fn(), sourceTaskHistory: vi.fn(), sourceTaskPreview: vi.fn(),
  sourceTaskCommit: vi.fn(), sourceTaskRequestOutcome: vi.fn(), sourceTaskExecutionOutcome: vi.fn() }));
type Obj = Record<string, unknown>;
const object = (v: unknown) => v as Obj;
const copy = <T,>(v: T): T => structuredClone(v);
const capabilities = knownTaskCapabilities(http.capabilities)!;
const originalEnqueue = knownTaskOperation(http.enqueue_request)!;
const originalExecute = knownTaskOperation(http.execution_request)!;
const lifecycle = knownLifecycleHistory(http.source_history, "paper", http.source_id)!;
const event = lifecycle.head!;
const actorId = capabilities.actor_user_id;
const foreignId = "00000000-0000-4000-8000-999999999999";

async function preview(operation: TaskOperation): Promise<TaskPreview> {
  return { ...copy(operation.operation === "enqueue" ? http.enqueue_preview : http.execution_preview),
    operation: operation.operation, operation_sha256: await taskOperationSha256(operation) } as TaskPreview;
}
async function receipt(operation: TaskOperation, replayed = false): Promise<TaskReceipt> {
  const value = copy(operation.operation === "enqueue" ? http.enqueue_receipt : http.execution_receipt) as TaskReceipt;
  value.operation_sha256 = await taskOperationSha256(operation); value.replayed = replayed;
  value.executed_now = operation.operation === "execute" && !replayed;
  if (operation.operation === "enqueue") {
    value.request.request_key = operation.request_key; value.request.event_id = operation.event_id;
    value.request.event_sha256 = operation.expected_event_sha256; value.request.inventory_sha256 = operation.expected_inventory_sha256;
  } else {
    value.request.id = operation.request_id; value.request.record_sha256 = operation.expected_request_sha256;
    value.attempt!.request_id = operation.request_id; value.attempt!.execution_key = operation.execution_key;
    value.attempt!.predecessor_id = operation.expected_predecessor_id;
  }
  return value;
}
function deferred<T>() { let resolve!: (value: T) => void; const promise = new Promise<T>(done => { resolve = done; }); return { resolve, promise }; }
async function mount() { render(<SourceTasksPage />); await screen.findByText(/Current curator access verified/); }
async function inspect() {
  fireEvent.change(screen.getByLabelText("Source identifier"), { target: { value: http.source_id } });
  fireEvent.click(screen.getByRole("button", { name: "Inspect source" }));
  fireEvent.click(await screen.findByRole("button", { name: /Inspect impact · revision/ }));
  return screen.findByRole("heading", { name: "Exact declared impact" });
}
async function prepare() { await inspect(); fireEvent.click(screen.getByRole("button", { name: "Preview enqueue" })); return screen.findByRole("heading", { name: "3. Confirm exact enqueue preview" }); }

beforeEach(() => {
  vi.stubGlobal("crypto", webcrypto); vi.resetAllMocks();
  vi.mocked(sourceTaskCapabilities).mockResolvedValue(copy(http.capabilities));
  vi.mocked(sourceLifecycleHistory).mockResolvedValue(copy(http.source_history));
  vi.mocked(sourceLifecycleImpact).mockResolvedValue(copy(http.source_impact));
  vi.mocked(sourceTaskHistory).mockResolvedValue(copy(http.queued_task_history));
  vi.mocked(sourceTaskPreview).mockImplementation(async operation => preview(operation));
  vi.mocked(sourceTaskCommit).mockImplementation(async operation => receipt(operation));
  vi.mocked(sourceTaskRequestOutcome).mockResolvedValue(copy(http.recovered_enqueue));
  vi.mocked(sourceTaskExecutionOutcome).mockResolvedValue(copy(http.recovered_execution));
});
afterEach(() => { vi.unstubAllGlobals(); vi.useRealTimers(); });

describe("source-task closed contracts", () => {
  it("admits the complete actual disposable SQL-to-HTTP fixture and exact Python operation hashes", async () => {
    expect(capabilities).not.toBeNull(); expect(lifecycle).not.toBeNull();
    expect(knownSourceImpact(http.source_impact, event)).not.toBeNull();
    expect(knownTaskHistory(http.queued_task_history, http.enqueue_receipt.request.id)).not.toBeNull();
    expect(knownTaskHistory(http.task_history, http.enqueue_receipt.request.id)).not.toBeNull();
    for (const operation of [originalEnqueue, originalExecute]) {
      const sha = await taskOperationSha256(operation), raw = operation.operation === "enqueue" ? http.enqueue_preview : http.execution_preview;
      expect(sha).toBe(raw.operation_sha256);
      const p = knownTaskPreview(raw, operation, capabilities, sha); expect(p).not.toBeNull();
      expect(knownTaskReceipt(operation.operation === "enqueue" ? http.enqueue_receipt : http.execution_receipt,
        { actorId, operation, operationSha: sha, preview: p! })).not.toBeNull();
    }
    expect(knownTaskReceipt(http.recovered_enqueue, { actorId, requestKey: http.enqueue_request.request_key })).not.toBeNull();
    expect(knownTaskReceipt(http.recovered_execution, { actorId, requestId: http.execution_request.request_id, executionKey: http.execution_request.execution_key })).not.toBeNull();
  });
  it.each(["version", "actor", "write_false", "coercion", "approval", "extra"])("rejects unsupported capability %s", kind => {
    const value = object(copy(http.capabilities));
    if (kind === "version") value.version = "source-task-capabilities/99";
    if (kind === "actor") value.actor_user_id = "not-an-id";
    if (kind === "write_false") value.can_write = false;
    if (kind === "coercion") value.can_read = 1;
    if (kind === "approval") value.scientific_acceptance = true;
    if (kind === "extra") value.private_secret = "not displayed";
    expect(knownTaskCapabilities(value)).toBeNull();
  });
  it.each(["extra", "key", "upper_hash", "missing_pair", "wrong_id", "version"])("rejects operation %s", kind => {
    const value = object(copy(http.execution_request));
    if (kind === "extra") value.actor_user_id = actorId;
    if (kind === "key") value.execution_key = "../another";
    if (kind === "upper_hash") value.expected_request_sha256 = "A".repeat(64);
    if (kind === "missing_pair") value.expected_predecessor_id = foreignId;
    if (kind === "wrong_id") value.request_id = "bad";
    if (kind === "version") value.version = "source-task-operation/2";
    expect(knownTaskOperation(value)).toBeNull();
  });
  it.each(["actor", "grant", "hash", "approval", "queued_code", "extra", "mutated"])("rejects preview %s", kind => {
    const value = object(copy(http.enqueue_preview));
    if (kind === "actor") value.actor_user_id = foreignId;
    if (kind === "grant") value.actor_grant_id = foreignId;
    if (kind === "hash") value.operation_sha256 = "b".repeat(64);
    if (kind === "approval") object(value.receipt_semantics).propagation_complete = true;
    if (kind === "queued_code") value.predicted_outcome_code = "timeline_cache_invalidated";
    if (kind === "extra") value.raw_source = "unexpected";
    if (kind === "mutated") value.database_mutated = true;
    expect(knownTaskPreview(value, originalEnqueue, capabilities, http.enqueue_preview.operation_sha256)).toBeNull();
  });
  it("permits a same-user historical replay grant without claiming it is current", () => {
    const p = { ...copy(http.enqueue_preview), replayed: true, actor_grant_id: foreignId };
    expect(knownTaskPreview(p, originalEnqueue, capabilities, p.operation_sha256)).not.toBeNull();
    const r = copy(http.recovered_enqueue); r.actor_grant_id = foreignId; r.request.requester_grant_id = foreignId;
    expect(knownTaskReceipt(r, { actorId, requestKey: r.request.request_key })).not.toBeNull();
    expect(knownTaskReceipt(r, { actorId: foreignId, requestKey: r.request.request_key })).toBeNull();
  });
  it.each(["commit_false", "outer_commit", "approval", "actor", "attempt_number", "state_flags", "outcome", "extra", "request_hash", "predecessor", "operation_hash"])("rejects receipt %s", kind => {
    const value = object(copy(http.execution_receipt)), a = object(value.attempt);
    if (kind === "commit_false") value.committed = false;
    if (kind === "outer_commit") value.requires_outer_commit = true;
    if (kind === "approval") object(value.receipt_semantics).ml_training_approved = true;
    if (kind === "actor") value.actor_user_id = foreignId;
    if (kind === "attempt_number") a.attempt_number = true;
    if (kind === "state_flags") { a.state_present = false; a.state_changed = true; }
    if (kind === "outcome") a.outcome_code = "source_changed";
    if (kind === "extra") value.inventory_json = "private";
    if (kind === "request_hash") object(value.request).record_sha256 = "b".repeat(64);
    if (kind === "predecessor") { a.attempt_number = 2; a.predecessor_id = foreignId; }
    if (kind === "operation_hash") value.operation_sha256 = "a".repeat(64);
    expect(knownTaskReceipt(value, { actorId, operation: originalExecute, operationSha: http.execution_preview.operation_sha256,
      preview: http.execution_preview as TaskPreview })).toBeNull();
  });
  it("checks the exact predicted outcome code even within the same status", () => {
    const value = copy(http.execution_receipt), p = copy(http.execution_preview);
    value.attempt.status = "obsolete"; value.attempt.outcome_code = "inventory_changed"; value.attempt.state_changed = false; value.attempt.state_present = false; value.executed_now = false;
    p.predicted_status = "obsolete"; p.predicted_outcome_code = "source_changed";
    expect(knownTaskReceipt(value, { actorId, operation: originalExecute, operationSha: p.operation_sha256, preview: p as TaskPreview })).toBeNull();
  });
  it.each(["wrong_source", "approval", "duplicate", "boolean_revision", "head", "oversized", "unknown_field"])("rejects history %s", kind => {
    const value = object(copy(http.source_history));
    if (kind === "wrong_source") value.source_id = "other-paper";
    if (kind === "approval") value.source_reinstatement = true;
    if (kind === "duplicate") (value.events as unknown[]).push(copy((value.events as unknown[])[0]));
    if (kind === "boolean_revision") object((value.events as unknown[])[0]).revision = true;
    if (kind === "head") value.head = null;
    if (kind === "oversized") value.status = "x".repeat(300000);
    if (kind === "unknown_field") value.source_text = "not rendered";
    expect(knownLifecycleHistory(value, "paper", http.source_id)).toBeNull();
  });
  it.each(["event", "counts", "authority", "duplicate", "unknown_scope", "extra", "bound", "relation", "refresh"])("rejects impact %s", kind => {
    const value = object(copy(http.source_impact));
    if (kind === "event") object(value.event).record_sha256 = "f".repeat(64);
    if (kind === "counts") value.node_count = 0;
    if (kind === "authority") value.propagation_complete = true;
    if (kind === "duplicate") (value.nodes as unknown[]).push(copy((value.nodes as unknown[])[0]));
    if (kind === "unknown_scope") value.supported_scopes = ["everything"];
    if (kind === "extra") value.full_source = "not rendered";
    if (kind === "bound") object(value.limits).nodes = 100000;
    if (kind === "relation") object((object((value.nodes as unknown[])[0]).relations as unknown[])[0]).kind = "proves_science";
    if (kind === "refresh") object(value.observation).refresh_scheduled = true;
    expect(knownSourceImpact(value, event)).toBeNull();
  });
  it("validates whole attempt chains and returns detached copies", () => {
    const original = copy(http.task_history), parsed = knownTaskHistory(original, original.request.id)!;
    expect(parsed).not.toBeNull(); parsed.request.request_key = "changed";
    expect(original.request.request_key).not.toBe("changed");
    original.attempts.push(copy(original.attempts[0]));
    expect(knownTaskHistory(original, original.request.id)).toBeNull();
  });
});

describe("private source-task workbench", () => {
  it("checks curator access before any source read or write, and keeps English disclaimers", async () => {
    const delayed = deferred<unknown>(); vi.mocked(sourceTaskCapabilities).mockReturnValue(delayed.promise);
    render(<SourceTasksPage />); expect(sourceLifecycleHistory).not.toHaveBeenCalled(); expect(sourceTaskPreview).not.toHaveBeenCalled();
    await act(async () => delayed.resolve(http.capabilities));
    expect(await screen.findByText(/Current curator access verified/)).toBeVisible();
    expect(screen.getByText(/Invalidation only/)).toHaveTextContent(/does not rebuild.*authorize ML training/);
    expect(screen.queryByRole("button", { name: "Commit exact preview" })).not.toBeInTheDocument();
    expect(sourceTaskCommit).not.toHaveBeenCalled();
  });
  it("requires explicit inspect, preview, commit and execution, with exact real pins", async () => {
    const storage = vi.spyOn(window.localStorage, "setItem"); await mount(); await prepare();
    expect(sourceTaskCommit).not.toHaveBeenCalled();
    expect(sourceLifecycleImpact).toHaveBeenCalledWith(event.id, event.record_sha256, expect.any(AbortSignal));
    fireEvent.click(screen.getByRole("button", { name: "Commit exact preview" }));
    await screen.findByRole("heading", { name: "Committed historical receipt" });
    expect(sourceTaskCommit).toHaveBeenCalledTimes(1);
    expect(screen.getByText(/Timeline rebuilt: no/)).toBeVisible();
    fireEvent.click(screen.getByRole("button", { name: "Inspect recorded task" }));
    await screen.findByRole("heading", { name: "Immutable task history" });
    fireEvent.click(screen.getByRole("button", { name: "Preview execution" }));
    await screen.findByRole("heading", { name: "3. Confirm exact execute preview" });
    const operation = vi.mocked(sourceTaskPreview).mock.calls.at(-1)![0];
    expect(operation).toMatchObject({ operation: "execute", request_id: http.enqueue_receipt.request.id,
      expected_request_sha256: http.enqueue_receipt.request.record_sha256, expected_predecessor_id: null, expected_predecessor_sha256: null });
    fireEvent.click(screen.getByRole("button", { name: "Commit exact preview" }));
    await screen.findByRole("heading", { name: "Committed historical receipt" });
    expect(screen.getByText(/Cache state present:/)).toBeVisible();
    expect(sourceTaskCommit).toHaveBeenCalledTimes(2); expect(storage).not.toHaveBeenCalled(); storage.mockRestore();
  });
  it("clears preview on input edits and never silently reuses it", async () => {
    await mount(); await prepare();
    fireEvent.change(screen.getByLabelText("Source identifier"), { target: { value: "another-paper" } });
    expect(screen.queryByRole("button", { name: "Commit exact preview" })).not.toBeInTheDocument();
    expect(screen.queryByRole("heading", { name: "Exact declared impact" })).not.toBeInTheDocument();
    expect(sourceTaskCommit).not.toHaveBeenCalled();
  });
  it.each([0, 409, 503])("keeps an uncertain commit key after HTTP %s and recovers with reads only", async status => {
    vi.mocked(sourceTaskCommit).mockRejectedValue(new ApiError(status, null, "private server detail"));
    await mount(); await prepare(); fireEvent.click(screen.getByRole("button", { name: "Commit exact preview" }));
    await screen.findByRole("heading", { name: "Recover unknown commit" });
    const op = vi.mocked(sourceTaskCommit).mock.calls[0][0]; expect(op.operation).toBe("enqueue");
    const key = op.operation === "enqueue" ? op.request_key : "";
    expect(screen.getByText("Original request key: " + key)).toBeVisible();
    expect(screen.queryByText("private server detail")).not.toBeInTheDocument();
    vi.mocked(sourceTaskRequestOutcome).mockRejectedValueOnce(new ApiError(404, null, "missing"));
    fireEvent.click(screen.getByRole("button", { name: "Check original outcome" }));
    await screen.findByText(/Not found now.*absence is not proof/);
    expect(sourceTaskCommit).toHaveBeenCalledTimes(1); expect(screen.getByText("Original request key: " + key)).toBeVisible();
    vi.mocked(sourceTaskRequestOutcome).mockResolvedValue(await receipt(op, true));
    fireEvent.click(screen.getByRole("button", { name: "Check original outcome" }));
    await screen.findByRole("heading", { name: "Committed historical receipt" });
    expect(sourceTaskRequestOutcome).toHaveBeenLastCalledWith(key, expect.any(AbortSignal)); expect(sourceTaskCommit).toHaveBeenCalledTimes(1);
    expect(screen.getByText(/Exact replay; no new execution/)).toBeVisible();
  });
  it("rejects malformed commit success without enabling a second write", async () => {
    vi.mocked(sourceTaskCommit).mockImplementation(async op => ({ ...await receipt(op), committed: false }));
    await mount(); await prepare(); fireEvent.click(screen.getByRole("button", { name: "Commit exact preview" }));
    await screen.findByRole("heading", { name: "Recover unknown commit" });
    expect(screen.queryByRole("button", { name: "Commit exact preview" })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Preview enqueue" })).not.toBeInTheDocument();
  });
  it("clears private evidence and ignores a late response after auth change", async () => {
    const late = deferred<unknown>(); vi.mocked(sourceLifecycleImpact).mockReturnValue(late.promise);
    await mount(); fireEvent.change(screen.getByLabelText("Source identifier"), { target: { value: http.source_id } });
    fireEvent.click(screen.getByRole("button", { name: "Inspect source" }));
    fireEvent.click(await screen.findByRole("button", { name: /Inspect impact · revision/ }));
    await waitFor(() => expect(sourceLifecycleImpact).toHaveBeenCalled());
    act(() => notifyAuthChange()); await act(async () => late.resolve(http.source_impact));
    expect(screen.queryByText(http.source_id)).not.toBeInTheDocument(); expect(screen.queryByText(http.source_impact.inventory_sha256)).not.toBeInTheDocument();
    expect(screen.queryByRole("heading", { name: "Exact declared impact" })).not.toBeInTheDocument(); expect(sourceTaskCommit).not.toHaveBeenCalled();
  });
  it("retains only same-account opaque unknown recovery after an auth notification", async () => {
    vi.mocked(sourceTaskCommit).mockRejectedValue(new ApiError(503, null, "unknown"));
    await mount(); await prepare(); fireEvent.click(screen.getByRole("button", { name: "Commit exact preview" }));
    await screen.findByRole("heading", { name: "Recover unknown commit" });
    const op = vi.mocked(sourceTaskCommit).mock.calls[0][0], key = op.operation === "enqueue" ? op.request_key : "";
    act(() => notifyAuthChange()); expect(screen.queryByText("Original request key: " + key)).not.toBeInTheDocument();
    vi.mocked(sourceTaskCapabilities).mockResolvedValue({ ...http.capabilities, actor_user_id: foreignId });
    fireEvent.click(screen.getByRole("button", { name: "Refresh curator access" })); await screen.findByText(/Current curator access verified/);
    expect(screen.queryByRole("button", { name: "Check original outcome" })).not.toBeInTheDocument();
    act(() => notifyAuthChange()); vi.mocked(sourceTaskCapabilities).mockResolvedValue(http.capabilities);
    fireEvent.click(screen.getByRole("button", { name: "Refresh curator access" }));
    await screen.findByRole("heading", { name: "Recover unknown commit" });
    expect(screen.getByText("Original request key: " + key)).toBeVisible(); expect(sourceTaskCommit).toHaveBeenCalledTimes(1);
  });
  it.each([401, 403])("clears evidence when curator access fails with %s", async code => {
    await mount(); await inspect(); vi.mocked(sourceTaskCapabilities).mockRejectedValue(new ApiError(code, null, "private secret"));
    fireEvent.click(screen.getByRole("button", { name: "Preview enqueue" }));
    await screen.findByText(/Session or curator access is unavailable/);
    expect(screen.queryByRole("heading", { name: "Exact declared impact" })).not.toBeInTheDocument(); expect(sourceTaskPreview).not.toHaveBeenCalled();
  });
  it("never offers another execution after a terminal historical success", async () => {
    vi.mocked(sourceTaskHistory).mockResolvedValue(http.task_history); await mount();
    fireEvent.change(screen.getByLabelText("Task request UUID"), { target: { value: http.enqueue_receipt.request.id } });
    fireEvent.click(screen.getByRole("button", { name: "Load task history" })); await screen.findByRole("heading", { name: "Immutable task history" });
    expect(screen.getByRole("button", { name: "Preview execution" })).toBeDisabled(); expect(screen.getByText(/No further execution is available/)).toBeVisible();
  });
  it("recovers an exact execution key with a GET, not an inferred success or new task", async () => {
    await mount(); fireEvent.change(screen.getByLabelText("Task request UUID"), { target: { value: http.execution_request.request_id } });
    fireEvent.change(screen.getByLabelText("Execution key"), { target: { value: http.execution_request.execution_key } });
    fireEvent.click(screen.getByRole("button", { name: "Find execution outcome" })); await screen.findByRole("heading", { name: "Committed historical receipt" });
    expect(sourceTaskExecutionOutcome).toHaveBeenCalledWith(http.execution_request.request_id, http.execution_request.execution_key, expect.any(AbortSignal));
    expect(sourceTaskPreview).not.toHaveBeenCalled(); expect(sourceTaskCommit).not.toHaveBeenCalled();
  });
  it("handles a source with no lifecycle events without inventing a task", async () => {
    vi.mocked(sourceLifecycleHistory).mockResolvedValue({ ...http.source_history, head: null, events: [], next_before_revision: null,
      direct_lifecycle_review_required: false, lifecycle_review_required: false, effective_lifecycle_revision: null });
    await mount(); fireEvent.change(screen.getByLabelText("Source identifier"), { target: { value: http.source_id } });
    fireEvent.click(screen.getByRole("button", { name: "Inspect source" })); await screen.findByText(/No lifecycle events were returned/);
    expect(screen.queryByRole("button", { name: "Preview enqueue" })).not.toBeInTheDocument();
  });
  it("warns on document unload while outcome is unknown, without claiming SPA persistence", async () => {
    vi.mocked(sourceTaskCommit).mockRejectedValue(new ApiError(503, null, "unknown"));
    await mount(); await prepare(); fireEvent.click(screen.getByRole("button", { name: "Commit exact preview" }));
    await screen.findByRole("heading", { name: "Recover unknown commit" });
    const event = new Event("beforeunload", { cancelable: true }); window.dispatchEvent(event);
    expect(event.defaultPrevented).toBe(true);
    expect(screen.getByText(/does not persist recovery across reloads or guarantee protection/)).toBeVisible();
    const op = vi.mocked(sourceTaskCommit).mock.calls[0][0]; vi.mocked(sourceTaskRequestOutcome).mockResolvedValue(await receipt(op, true));
    fireEvent.click(screen.getByRole("button", { name: "Check original outcome" })); await screen.findByRole("heading", { name: "Committed historical receipt" });
    const after = new Event("beforeunload", { cancelable: true }); window.dispatchEvent(after); expect(after.defaultPrevented).toBe(false);
  });
  it("makes a captured uncertain-state unload listener harmless after verified recovery without waiting for cleanup", async () => {
    const add = vi.spyOn(window, "addEventListener"), remove = vi.spyOn(window, "removeEventListener");
    try {
      vi.mocked(sourceTaskCommit).mockRejectedValue(new ApiError(503, null, "unknown"));
      const view = render(<SourceTasksPage />); await screen.findByText(/Current curator access verified/);
      const callbacks = () => add.mock.calls.filter(([type]) => type === "beforeunload");
      const before = new Event("beforeunload", { cancelable: true }); window.dispatchEvent(before); expect(before.defaultPrevented).toBe(false);
      await prepare(); fireEvent.click(screen.getByRole("button", { name: "Commit exact preview" }));
      // The locator is set before the operation's first await, so the original
      // mounted callback already protects the in-flight write.
      const committing = new Event("beforeunload", { cancelable: true }); window.dispatchEvent(committing); expect(committing.defaultPrevented).toBe(true);
      await screen.findByRole("heading", { name: "Recover unknown commit" });
      const warn = callbacks().at(-1)![1] as EventListener;
      const unknown = new Event("beforeunload", { cancelable: true }); warn(unknown); expect(unknown.defaultPrevented).toBe(true);
      const op = vi.mocked(sourceTaskCommit).mock.calls[0][0]; vi.mocked(sourceTaskRequestOutcome).mockResolvedValue(await receipt(op, true));
      fireEvent.click(screen.getByRole("button", { name: "Check original outcome" })); await screen.findByRole("heading", { name: "Committed historical receipt" });
      // Invoke the captured callback directly: this is independent of whether
      // React has removed/reinstalled any passive-effect listeners yet.
      const settled = new Event("beforeunload", { cancelable: true }); warn(settled); expect(settled.defaultPrevented).toBe(false);
      expect(callbacks()).toHaveLength(1);
      view.unmount(); expect(remove).toHaveBeenCalledWith("beforeunload", warn);
      const unmounted = new Event("beforeunload", { cancelable: true }); window.dispatchEvent(unmounted); expect(unmounted.defaultPrevented).toBe(false);
    } finally { add.mockRestore(); remove.mockRestore(); }
  });
  it("turns transport timeout into unknown and ignores a late successful response", async () => {
    const delayed = deferred<unknown>(); vi.mocked(sourceTaskCommit).mockReturnValue(delayed.promise);
    await mount(); await prepare();
    const real = window.setTimeout.bind(window);
    const timers = vi.spyOn(window, "setTimeout").mockImplementation((handler, delay, ...args) => real(handler, delay === 30000 ? 5 : delay, ...args));
    fireEvent.click(screen.getByRole("button", { name: "Commit exact preview" }));
    await screen.findByRole("heading", { name: "Recover unknown commit" });
    const op = vi.mocked(sourceTaskCommit).mock.calls[0][0]; await act(async () => delayed.resolve(await receipt(op)));
    expect(screen.queryByRole("heading", { name: "Committed historical receipt" })).not.toBeInTheDocument();
    expect(sourceTaskCommit).toHaveBeenCalledTimes(1); timers.mockRestore();
  });
  it("never issues duplicate concurrent commits", async () => {
    const delayed = deferred<unknown>(); vi.mocked(sourceTaskCommit).mockReturnValue(delayed.promise);
    await mount(); await prepare(); const commit = screen.getByRole("button", { name: "Commit exact preview" });
    fireEvent.click(commit); fireEvent.click(commit);
    await waitFor(() => expect(sourceTaskCommit).toHaveBeenCalledTimes(1));
    const op = vi.mocked(sourceTaskCommit).mock.calls[0][0]; await act(async () => delayed.resolve(await receipt(op)));
    await screen.findByRole("heading", { name: "Committed historical receipt" });
  });
  it("pins the exact retry predecessor from a checked immutable history", async () => {
    const rows = copy(http.task_history); rows.stored_state = "retryable_failure";
    Object.assign(rows.attempts[0], { status: "retryable_failure", outcome_code: "database_busy", state_present: false, state_changed: false });
    vi.mocked(sourceTaskHistory).mockResolvedValue(rows); await mount();
    fireEvent.change(screen.getByLabelText("Task request UUID"), { target: { value: rows.request.id } });
    fireEvent.click(screen.getByRole("button", { name: "Load task history" })); await screen.findByRole("heading", { name: "Immutable task history" });
    fireEvent.click(screen.getByRole("button", { name: "Preview execution" })); await screen.findByRole("heading", { name: "3. Confirm exact execute preview" });
    expect(sourceTaskPreview).toHaveBeenCalledWith(expect.objectContaining({ expected_predecessor_id: rows.attempts[0].id,
      expected_predecessor_sha256: rows.attempts[0].record_sha256 }), expect.any(AbortSignal));
    expect(sourceTaskCommit).not.toHaveBeenCalled();
  });
  it("checks Work UUIDs without coercing paper identifiers or sending both selectors", async () => {
    const value = copy(http.source_history), id = foreignId;
    Object.assign(value, { source_kind: "work", source_id: id });
    for (const row of [...value.events, value.head]) Object.assign(row, { paper_id: null, work_id: id });
    vi.mocked(sourceLifecycleHistory).mockResolvedValue(value); await mount();
    fireEvent.change(screen.getByLabelText("Source type"), { target: { value: "work" } });
    fireEvent.change(screen.getByLabelText("Source identifier"), { target: { value: "bad-uuid" } });
    expect(screen.getByRole("button", { name: "Inspect source" })).toBeDisabled();
    fireEvent.change(screen.getByLabelText("Source identifier"), { target: { value: id } }); fireEvent.click(screen.getByRole("button", { name: "Inspect source" }));
    await screen.findByRole("button", { name: /Inspect impact · revision/ });
    expect(sourceLifecycleHistory).toHaveBeenCalledWith("work", id, null, expect.any(AbortSignal));
  });
  it("fails closed on malformed source impact and does not leave an actionable preview", async () => {
    vi.mocked(sourceLifecycleImpact).mockResolvedValue({ ...http.source_impact, propagation_complete: true });
    await mount(); fireEvent.change(screen.getByLabelText("Source identifier"), { target: { value: http.source_id } });
    fireEvent.click(screen.getByRole("button", { name: "Inspect source" })); fireEvent.click(await screen.findByRole("button", { name: /Inspect impact · revision/ }));
    await screen.findByText(/The response could not be verified/);
    expect(screen.queryByRole("button", { name: "Preview enqueue" })).not.toBeInTheDocument();
    expect(sourceTaskPreview).not.toHaveBeenCalled();
  });
  it("detects a different current actor even without an auth-change event", async () => {
    await mount(); await inspect(); vi.mocked(sourceTaskCapabilities).mockResolvedValue({ ...http.capabilities, actor_user_id: foreignId });
    fireEvent.click(screen.getByRole("button", { name: "Preview enqueue" })); await screen.findByText(/Session or curator access is unavailable/);
    expect(screen.queryByRole("heading", { name: "Exact declared impact" })).not.toBeInTheDocument(); expect(sourceTaskPreview).not.toHaveBeenCalled();
  });
});

it("API helpers use private cookie/no-store requests, exact commit envelope and encoded lookup selectors", async () => {
  const api = await vi.importActual<typeof import("@/lib/api")>("@/lib/api");
  const fetch = vi.fn().mockImplementation(async () => new Response("{}", { headers: { "content-type": "application/json" } }));
  vi.stubGlobal("fetch", fetch);
  await api.sourceTaskCapabilities();
  await api.sourceLifecycleHistory("paper", "a/b?secret", 4);
  await api.sourceLifecycleImpact(event.id, event.record_sha256);
  await api.sourceTaskHistory(http.enqueue_receipt.request.id);
  await api.sourceTaskPreview(originalEnqueue);
  await api.sourceTaskCommit(originalEnqueue, http.enqueue_preview.preview_sha256);
  await api.sourceTaskRequestOutcome("key/with?reserved");
  await api.sourceTaskExecutionOutcome(foreignId, "key/with?reserved");
  expect(fetch).toHaveBeenCalledTimes(8);
  for (const [, init] of fetch.mock.calls) expect(init).toMatchObject({ cache: "no-store", credentials: "include" });
  expect(fetch.mock.calls[1][0]).toContain("paper_id=a%2Fb%3Fsecret&limit=25&before_revision=4");
  expect(fetch.mock.calls[6][0]).toContain("requests/key%2Fwith%3Freserved");
  expect(fetch.mock.calls[7][0]).toContain("executions/key%2Fwith%3Freserved");
  expect(JSON.parse(fetch.mock.calls[5][1].body)).toEqual({ request: originalEnqueue, expected_preview_sha256: http.enqueue_preview.preview_sha256 });
  expect(fetch.mock.calls[5][1].method).toBe("POST");
});
