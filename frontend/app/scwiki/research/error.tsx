"use client";
export default function ResearchError({reset}:{reset:()=>void}){
 return <main className="scwiki"><h1>Research editions are temporarily unavailable</h1><p>Please retry shortly. Original sources and wiki articles remain available.</p><button onClick={reset}>Retry</button><p><a href="/scwiki">Back to SCWiki</a></p></main>;
}
