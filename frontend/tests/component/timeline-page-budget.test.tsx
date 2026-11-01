import { render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
const chart=vi.hoisted(()=>vi.fn(()=> <div role="img" aria-label="NER 2D timeline"/>));
vi.mock("@/components/MaterialsTcTimeline",()=>({MaterialsTcTimeline:chart}));
import TimelinePage from "@/app/timeline/page";
import { HomeTcTimeline } from "@/components/HomeTcTimeline";

describe("independent and homepage Timeline entry points",()=>{
 beforeEach(()=>vi.clearAllMocks());
 it("has an independent page without the Discovery subnavigation",()=>{
  render(<TimelinePage/>);
  expect(screen.getByRole("heading",{level:1})).toHaveTextContent("TcTimeline");
  expect(screen.getByRole("img",{name:"NER 2D timeline"})).toBeVisible();
  expect(screen.queryByRole("navigation",{name:"Discovery"})).not.toBeInTheDocument();
 });
 it("provides a compact home module and the independent page link",()=>{
  render(<HomeTcTimeline/>);
  expect(screen.getByRole("heading",{level:2,name:"TcTimeline"})).toBeVisible();
  expect(screen.getByRole("link",{name:/Open TcTimeline/})).toHaveAttribute("href","/timeline");
  expect(chart.mock.calls[0][0]).toEqual({compact:true});
 });
});
