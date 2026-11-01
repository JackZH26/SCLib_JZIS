import { describe, expect, it } from "vitest";
import { tcDisplayExclusion, type TcDisplayValues } from "@/lib/tc-display-policy";

const row = (changes: Partial<TcDisplayValues> = {}): TcDisplayValues => ({
  value_kelvin: 210, value_lower_kelvin: null, value_upper_kelvin: null, value_relation: "exact", ...changes,
});
describe("public Tc display ceiling", () => {
  it("includes 300 K and flags every explicit endpoint above it without rewriting values", () => {
    expect(tcDisplayExclusion(row({value_kelvin:300}))).toBeNull();
    for (const data of [row({value_kelvin:300.0001}), row({value_kelvin:null,value_relation:"interval",value_lower_kelvin:290,value_upper_kelvin:310}), row({value_kelvin:null,value_relation:"le",value_upper_kelvin:400})]) {
      const original = structuredClone(data);
      expect(tcDisplayExclusion(data)).toBe("tc_above_300k");
      expect(data).toEqual(original);
    }
  });
  it("preserves interval and lower-bound semantics at the boundary", () => {
    expect(tcDisplayExclusion(row({value_kelvin:null,value_relation:"interval",value_lower_kelvin:290,value_upper_kelvin:300}))).toBeNull();
    expect(tcDisplayExclusion(row({value_kelvin:null,value_relation:"gt",value_lower_kelvin:300}))).toBe("tc_above_300k");
    expect(tcDisplayExclusion(row({value_kelvin:null,value_relation:"ge",value_lower_kelvin:300}))).toBeNull();
    expect(tcDisplayExclusion({...row(),pressure_gpa:800,raw:"A source mentions 850 K"} as TcDisplayValues)).toBeNull();
  });
});
