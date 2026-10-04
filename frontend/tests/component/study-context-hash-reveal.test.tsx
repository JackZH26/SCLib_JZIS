import { act, cleanup, fireEvent, render } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import PressureAndTablesPage from "@/app/materials/source-observations/pressure-and-tables/page";
import FollowupPage from "@/app/materials/source-observations/followup/page";
import { StudyContextHashReveal } from "@/components/StudyContextHashReveal";

let frames: Map<number, FrameRequestCallback>, frameId: number;
const originalScroll = Object.getOwnPropertyDescriptor(HTMLElement.prototype, "scrollIntoView");
const scroll = vi.fn();
const requestFrame = vi.fn((callback: FrameRequestCallback) => {
  const id = ++frameId;
  frames.set(id, callback);
  return id;
});
const cancelFrame = vi.fn((id: number) => { frames.delete(id); });
function stepFrame() {
  const pending = [...frames.values()];
  frames.clear();
  act(() => { pending.forEach(callback => callback(0)); });
}
function hash(value: string) { window.history.replaceState(null, "", "/" + value); }
function detailsState() {
  return new Map([...document.querySelectorAll("details")].map(fold => [fold, fold.open]));
}
function ancestorFolds(target: HTMLElement) {
  const result: HTMLDetailsElement[] = [];
  for (let element: HTMLElement | null = target; element; element = element.parentElement) {
    if (element instanceof HTMLDetailsElement) result.push(element);
  }
  return result;
}
beforeEach(() => {
  frames = new Map();
  frameId = 0;
  vi.clearAllMocks();
  hash("");
  vi.stubGlobal("requestAnimationFrame", requestFrame);
  vi.stubGlobal("cancelAnimationFrame", cancelFrame);
  Object.defineProperty(HTMLElement.prototype, "scrollIntoView", { configurable: true, value: scroll });
});
afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
  if (originalScroll) Object.defineProperty(HTMLElement.prototype, "scrollIntoView", originalScroll);
  else Reflect.deleteProperty(HTMLElement.prototype, "scrollIntoView");
  hash("");
});

describe("source-context fragment navigation", () => {
  it.each([
    ["study-context-bi-transport", PressureAndTablesPage],
    ["study-context-bi-raman", PressureAndTablesPage],
    ["study-context-pt-calorimetry-attribution", FollowupPage],
    ["study-context-pt-xrd-correspondence", FollowupPage],
  ] as const)("reveals only the actual page's ancestor disclosures for %s", (id, Page) => {
    hash("#" + id);
    render(<Page />);
    const target = document.getElementById(id)!;
    expect(target).not.toBeNull();
    const ancestors = ancestorFolds(target), before = detailsState();
    expect(ancestors.length).toBeGreaterThan(0);
    expect(ancestors.every(fold => !fold.open)).toBe(true);
    stepFrame();
    expect(ancestors.every(fold => fold.open)).toBe(true);
    for (const [fold, wasOpen] of before) {
      if (!ancestors.includes(fold)) expect(fold.open).toBe(wasOpen);
    }
    expect(scroll).not.toHaveBeenCalled();
    stepFrame();
    expect(scroll).toHaveBeenCalledOnce();
    expect(scroll.mock.instances[0]).toBe(target);
    expect(scroll).toHaveBeenCalledWith({ block: "start", behavior: "auto" });
  });

  it.each(["", "#mo-table-heading", "#study-context-bi-transport-extra", "#source-record-bitecl-01"])(
    "preserves default fold states for an unrelated or absent hash %s", value => {
      hash(value);
      render(<PressureAndTablesPage />);
      const before = detailsState();
      stepFrame();
      stepFrame();
      for (const [fold, wasOpen] of before) expect(fold.open).toBe(wasOpen);
      expect(scroll).not.toHaveBeenCalled();
    },
  );

  it("leaves both open and closed unrelated folds unchanged when an accepted target is absent", () => {
    hash("#study-context-bi-transport");
    const view = render(<><details open><summary>Already open</summary>Retained</details><details><summary>Still closed</summary>Retained</details><StudyContextHashReveal /></>);
    const before = detailsState();
    stepFrame();
    stepFrame();
    for (const [fold, wasOpen] of before) expect(fold.open).toBe(wasOpen);
    expect(scroll).not.toHaveBeenCalled();
    view.unmount();
  });

  it("reads a navigation hash at reveal time after mounting, rather than retaining an earlier URL", () => {
    render(<PressureAndTablesPage />);
    hash("#study-context-bi-transport");
    const target = document.getElementById("study-context-bi-transport")!;
    stepFrame();
    expect(ancestorFolds(target).every(fold => fold.open)).toBe(true);
    stepFrame();
    expect(scroll.mock.instances[0]).toBe(target);
  });

  it("handles native hash/back navigation and cancels an earlier pending scroll when the target changes", () => {
    render(<PressureAndTablesPage />);
    stepFrame();
    hash("#study-context-bi-transport");
    fireEvent(window, new HashChangeEvent("hashchange"));
    stepFrame();
    const pendingScroll = [...frames.keys()][0];
    hash("#study-context-bi-raman");
    fireEvent(window, new PopStateEvent("popstate"));
    expect(cancelFrame).toHaveBeenCalledWith(pendingScroll);
    stepFrame();
    stepFrame();
    expect(scroll).toHaveBeenCalledOnce();
    expect(scroll.mock.instances[0]).toBe(document.getElementById("study-context-bi-raman"));
  });

  it.each(["reveal", "scroll"] as const)("removes its listeners and pending %s frame on unmount", phase => {
    const add = vi.spyOn(window, "addEventListener"), remove = vi.spyOn(window, "removeEventListener");
    hash("#study-context-bi-transport");
    const view = render(<PressureAndTablesPage />);
    if (phase === "scroll") stepFrame();
    const pending = [...frames.keys()][0];
    const listener = add.mock.calls.find(call => call[0] === "hashchange")![1];
    view.unmount();
    expect(remove).toHaveBeenCalledWith("hashchange", listener);
    expect(remove).toHaveBeenCalledWith("popstate", listener);
    expect(cancelFrame).toHaveBeenCalledWith(pending);
    expect(frames.size).toBe(0);
    const requests = requestFrame.mock.calls.length;
    fireEvent(window, new HashChangeEvent("hashchange"));
    fireEvent(window, new PopStateEvent("popstate"));
    stepFrame();
    expect(requestFrame.mock.calls.length).toBe(requests);
    expect(scroll).not.toHaveBeenCalled();
  });
});
