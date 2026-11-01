import { afterEach, expect, it } from "vitest";
import { consumeMaterialsAuthReturn, MATERIALS_DOWNLOAD_RETURN, materialsAuthReturn, rememberMaterialsAuthReturn } from "@/lib/materials-auth-return";
afterEach(() => { sessionStorage.clear(); });

it("keeps Materials return locations and rejects external, ambiguous and unrelated paths", () => {
  expect(materialsAuthReturn("?next="+encodeURIComponent(MATERIALS_DOWNLOAD_RETURN))).toBe(MATERIALS_DOWNLOAD_RETURN);
  for (const next of ["https://example.com", "//example.com", "/materials/../../admin", "/materials/%2e%2e/admin", "/dashboard", "/materials\\\\example.com", "/materials\n"]) {
    expect(materialsAuthReturn("?next="+encodeURIComponent(next))).toBeNull();
  }
});
it("stores only a single-use non-secret return path for OAuth", () => {
  rememberMaterialsAuthReturn(MATERIALS_DOWNLOAD_RETURN);
  expect(consumeMaterialsAuthReturn()).toBe(MATERIALS_DOWNLOAD_RETURN);
  expect(consumeMaterialsAuthReturn()).toBeNull();
  rememberMaterialsAuthReturn("//example.com");
  expect(consumeMaterialsAuthReturn()).toBeNull();
});
