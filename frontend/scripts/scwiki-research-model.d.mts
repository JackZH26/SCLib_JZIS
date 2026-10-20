import type {ResearchCollection} from "../lib/scwiki/research-types";
export function isoWeek(day:string):string;
export function validateResearch(data:unknown,today?:string):ResearchCollection;
export function assertAppendOnly(previous:ResearchCollection,next:ResearchCollection):void;
