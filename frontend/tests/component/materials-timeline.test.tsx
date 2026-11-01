import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { MaterialsTcTimeline } from "@/components/MaterialsTcTimeline";
import { timelineDate, timelinePressure, timelineTc, timelineFamilies, type NerTimelineData, type NerTimelinePoint } from "@/lib/materials-timeline";

const api=vi.hoisted(()=>({read:vi.fn()}));
vi.mock("@/lib/api",()=>({getMaterialsTimeline:api.read}));
const point=(overrides:Partial<NerTimelinePoint>={}):NerTimelinePoint=>({
  id:"tc-a",material_id:"source:sample-a",paper_id:"arxiv:1909.10482",formula:"YH6",family:"hydride",
  date:"2019-09-23",date_basis:"paper_submission",date_precision:"day",
  value_kelvin:210,value_lower_kelvin:null,value_upper_kelvin:null,value_relation:"exact",
  approximate:false,criterion:"onset",pressure_gpa:201,pressure_regime:"nonambient",...overrides,
});
const response=(points=[point()]):NerTimelineData=>({dataset:"materials-production90/1",points,
  total_results:points.length,total_materials:points.length,total_papers:1,plotted_results:points.length,
  omitted_without_date:0,omitted_invalid_quantity:0,sampled:false,families:{hydride:points.length},date_min:"2019-01-01",date_max:"2019-12-31"});
beforeEach(()=>{
  vi.clearAllMocks();
  vi.spyOn(HTMLCanvasElement.prototype,"getContext").mockReturnValue({
    setTransform:vi.fn(),clearRect:vi.fn(),save:vi.fn(),beginPath:vi.fn(),rect:vi.fn(),clip:vi.fn(),
    moveTo:vi.fn(),lineTo:vi.fn(),closePath:vi.fn(),fill:vi.fn(),stroke:vi.fn(),arc:vi.fn(),restore:vi.fn(),
  } as unknown as CanvasRenderingContext2D);
});

describe("new NER Tc timeline",()=>{
  it("places different months of one year at distinct continuous positions without jitter",()=>{
    const jan=point({date:"2019-01-01"}),feb=point({date:"2019-02-01"}),sep=point({date:"2019-09-23"});
    expect(timelineDate(jan)).toBeLessThan(timelineDate(feb));
    expect(timelineDate(feb)).toBeLessThan(timelineDate(sep));
    expect(timelineDate({...jan,id:"another-report"})).toBe(timelineDate(jan));
    const month=point({date:"2020-02",date_precision:"month",date_basis:"arxiv_identifier_month"});
    expect(timelineDate(month)).toBe((Date.UTC(2020,1,1)+Date.UTC(2020,2,1))/2);
    expect(timelineDate(point({date:"2019-02-31"}))).toBeNaN();
  });
  it("keeps ranges, inequalities, approximation and unreported pressure explicit",()=>{
    expect(timelineTc(point({value_kelvin:null,value_relation:"interval",value_lower_kelvin:6,value_upper_kelvin:12}))).toBe("6–12 K");
    expect(timelineTc(point({value_kelvin:null,value_relation:"lt",value_upper_kelvin:1.7,approximate:true}))).toBe("< ≈ 1.7 K");
    expect(timelinePressure(point({pressure_gpa:null,pressure_regime:"unknown"}))).toBe("Pressure not stated");
    expect(new Set(Object.values(timelineFamilies).map(f=>f.color+":"+f.shape)).size).toBe(25);
  });
  it("starts with the homepage legend closed, and allows opening it",()=>{
    render(<MaterialsTcTimeline compact initialData={response()}/>);
    const details=screen.getByText(/Material families/).closest("details")!;
    expect(details.open).toBe(false);
    fireEvent.click(details.querySelector("summary")!);
    expect(details.open).toBe(true);
    expect(screen.getByRole("button",{name:"Hydride"})).toBeVisible();
  });
  it("pins a keyboard-selected report, preserves its material link, and closes with Escape",()=>{
    render(<MaterialsTcTimeline initialData={response()}/>);
    const chart=screen.getByRole("img",{name:/Two-dimensional/});
    fireEvent.keyDown(chart,{key:"ArrowRight"});
    expect(screen.getByRole("dialog",{name:"Reported Tc details"})).toHaveTextContent("210 K");
    expect(screen.getByRole("link",{name:/View material data/})).toHaveAttribute("href","/materials/source%3Asample-a");
    fireEvent.pointerLeave(chart.closest(".ner-timeline-stage")!);
    expect(screen.getByRole("dialog")).toBeVisible();
    fireEvent.keyDown(document,{key:"Escape"});
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  });
  it("keeps overlapping reports independently reachable",()=>{
    render(<MaterialsTcTimeline initialData={response([point(),point({id:"tc-b",material_id:"source:sample-b",criterion:"midpoint"})])}/>);
    fireEvent.keyDown(screen.getByRole("img",{name:/Two-dimensional/}),{key:"ArrowRight"});
    expect(screen.getByText(/overlapping reports/)).toHaveTextContent("1 / 2");
    fireEvent.click(screen.getByRole("button",{name:"Next overlapping report"}));
    expect(screen.getByRole("link",{name:/View material data/})).toHaveAttribute("href","/materials/source%3Asample-b");
    expect(screen.getByRole("dialog")).toHaveTextContent("Midpoint");
  });
  it("retains month precision in pinned details",()=>{
    render(<MaterialsTcTimeline initialData={response([point({date:"2019-09",date_precision:"month",date_basis:"arxiv_identifier_month"})])}/>);
    fireEvent.click(screen.getByRole("button",{name:"Read a point"}));
    expect(screen.getByRole("dialog")).toHaveTextContent("Month precision · arXiv identifier");
    fireEvent.change(screen.getByRole("combobox",{name:"Time view"}),{target:{value:"month"}});
    expect(screen.getByRole("combobox",{name:"Year"})).toHaveValue("2019");
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  });
  it("excludes above-ceiling assertions from selection and offers no bypass range",()=>{
    render(<MaterialsTcTimeline initialData={response([
      point({id:"above",formula:"Excluded",value_kelvin:850}),point(),
      point({id:"interval",formula:"Excluded range",value_kelvin:null,value_relation:"interval",value_lower_kelvin:290,value_upper_kelvin:310}),
    ])}/>);
    expect(screen.queryByRole("option",{name:"Full range"})).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("button",{name:"Read a point"}));
    expect(screen.getByRole("dialog")).toHaveTextContent("210 K");
    fireEvent.keyDown(screen.getByRole("img",{name:/Two-dimensional/}),{key:"ArrowRight"});
    expect(screen.getByRole("dialog")).toHaveTextContent("210 K");
    expect(screen.queryByText(/Excluded/)).not.toBeInTheDocument();
    expect(screen.getByText("1 displayed")).toBeVisible();
  });
  it("offers recovery after a data failure, without substituting legacy results",async()=>{
    api.read.mockRejectedValueOnce(new Error("offline")).mockResolvedValueOnce(response());
    render(<MaterialsTcTimeline/>);
    expect(await screen.findByRole("alert")).toHaveTextContent("could not be loaded");
    fireEvent.click(screen.getByRole("button",{name:"Try again"}));
    await waitFor(()=>expect(screen.getByRole("img",{name:/Two-dimensional/})).toBeVisible());
    expect(api.read.mock.calls.every(call=>call[0]===20000)).toBe(true);
  });
  it("waits for the homepage module to approach the viewport and requests its compact budget",async()=>{
    let enter:IntersectionObserverCallback=()=>{};
    vi.stubGlobal("IntersectionObserver",class{constructor(callback:IntersectionObserverCallback){enter=callback;}observe(){}disconnect(){}});
    api.read.mockResolvedValue(response());
    render(<MaterialsTcTimeline compact/>);
    expect(api.read).not.toHaveBeenCalled();
    await act(async()=>enter([{isIntersecting:true}] as IntersectionObserverEntry[],{} as IntersectionObserver));
    expect(api.read).toHaveBeenCalledWith(2000,expect.any(AbortSignal));
    vi.unstubAllGlobals();
  });
});
