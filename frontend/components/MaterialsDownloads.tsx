"use client";

import { useEffect, useRef, useState } from "react";
import Link from "@/components/AppLink";
import { ApiError, getMaterialsDataset, materialsDatasetDownloadUrl, me } from "@/lib/api";
import { onAuthChange } from "@/lib/auth-session";
import { MATERIALS_DOWNLOAD_RETURN } from "@/lib/materials-auth-return";
import type { MaterialsDataset } from "@/lib/materials-vnext";

export function MaterialsDownloads() {
  const [auth, setAuth] = useState<"checking" | "guest" | "member" | "error">("checking");
  const [state, setState] = useState<"idle" | "loading" | "ready" | "error">("idle");
  const [dataset, setDataset] = useState<MaterialsDataset | null>(null);
  const generation = useRef(0);
  const [check, setCheck] = useState(0);
  useEffect(() => {
    const refresh = async () => {
      const request = ++generation.current;
      setAuth("checking"); setDataset(null); setState("idle");
      try { await me(); if (request === generation.current) setAuth("member"); }
      catch (error) { if (request === generation.current) setAuth(error instanceof ApiError && error.status === 401 ? "guest" : "error"); }
    };
    void refresh();
    const unsubscribe = onAuthChange(refresh);
    return () => { ++generation.current; unsubscribe(); };
  }, [check]);
  async function load() {
    if (auth !== "member" || state === "loading") return;
    const request = generation.current;
    setState("loading");
    try {
      const result = await getMaterialsDataset();
      if (request === generation.current) { setDataset(result); setState("ready"); }
    } catch (error) {
      if (request !== generation.current) return;
      setDataset(null);
      if (error instanceof ApiError && error.status === 401) { setAuth("guest"); setState("idle"); }
      else setState("error");
    }
  }
  if (auth === "member" && state === "ready") return <MaterialsDatasetDownloads dataset={dataset} />;
  return <section id="materials-downloads" className="materials-dataset-downloads scroll-mt-24" aria-labelledby="materials-downloads-heading" aria-busy={auth === "checking" || state === "loading"}>
    <h2 id="materials-downloads-heading">Download dataset</h2>
    {auth === "checking" ? <p role="status">Checking sign-in…</p> : auth === "member" ? <>
      {state === "error" && <p role="alert">Dataset downloads could not be loaded. Try again.</p>}
      <button type="button" className="site-text-link" onClick={load} disabled={state === "loading"}>{state === "loading" ? "Loading downloads…" : state === "error" ? "Try again" : "Show dataset downloads"}</button>
    </> : <>
      <p role={auth === "error" ? "alert" : undefined}>{auth === "error" ? "Sign-in status could not be checked. Try again." : "Sign in to view dataset information and downloads."}</p>
      {auth === "error" && <button type="button" className="site-text-link" onClick={() => setCheck(value => value + 1)}>Check again</button>}
      <p><Link className="site-text-link" href={`/login?next=${encodeURIComponent(MATERIALS_DOWNLOAD_RETURN)}`}>Sign in</Link>{" · "}<Link className="site-text-link" href={`/register?next=${encodeURIComponent(MATERIALS_DOWNLOAD_RETURN)}`}>Create an account</Link></p>
      <p className="text-sm text-sage-muted">New to SCLib? Create an account, verify your email, then sign in.</p>
    </>}
  </section>;
}

export function MaterialsDatasetDownloads({ dataset }: { dataset: MaterialsDataset | null }) {
  return <section id="materials-downloads" className="materials-dataset-downloads scroll-mt-24" aria-labelledby="materials-downloads-heading">
    <h2 id="materials-downloads-heading">Download dataset</h2>
    {dataset ? <>
      <p>Full dataset snapshot · {dataset.files.results.rows.toLocaleString("en-US")} results from {dataset.paper_count.toLocaleString("en-US")} papers. Page filters do not change these downloads.</p>
      <ul>{(["results", "evidence", "training"] as const).map(kind => <li key={kind}>
        <a className="site-text-link" href={materialsDatasetDownloadUrl(dataset.version, kind)}>
          {kind === "results" ? "Results CSV" : kind === "evidence" ? "Evidence CSV" : "Training CSV"}
        </a> · {dataset.files[kind].rows.toLocaleString("en-US")} rows
      </li>)}</ul>
      <p>Updated {new Date(dataset.created_at).toLocaleDateString("en-US", { year: "numeric", month: "short", day: "numeric", timeZone: "UTC" })} · Version <code title={dataset.version}>{dataset.version.slice(0, 12)}</code></p>
      <details><summary>Scope and training guidance</summary>
        <p>{dataset.source_scope}</p><p>{dataset.training_policy}</p><p>{dataset.grouping_policy}</p>
        <p>Use only feature columns as model inputs. Review and provenance columns describe the data. Unknown pressure and publication status remain unknown.</p>
        <p>Join the results and evidence files by record_id. Downloads include quality status and source versions; batch sampling is not individual expert review.</p>
      </details>
    </> : <p>Downloads will be available after the latest dataset update is prepared.</p>}
  </section>;
}
