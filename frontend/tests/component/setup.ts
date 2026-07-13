import "@testing-library/jest-dom/vitest";

// Node 24 exposes an opt-in global localStorage stub that can shadow jsdom's
// implementation without a --localstorage-file. Install a deterministic
// in-memory Storage for component tests instead of depending on Node flags.
const values = new Map<string, string>();
Object.defineProperty(window, "localStorage", {
  configurable: true,
  value: {
    get length() {
      return values.size;
    },
    clear: () => values.clear(),
    getItem: (key: string) => values.get(key) ?? null,
    key: (index: number) => Array.from(values.keys())[index] ?? null,
    removeItem: (key: string) => values.delete(key),
    setItem: (key: string, value: string) => values.set(key, String(value)),
  } satisfies Storage,
});
