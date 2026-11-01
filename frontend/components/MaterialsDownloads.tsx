"use client";

import { useState } from "react";
import { getMaterialsDataset, materialsDatasetDownloadUrl } from "@/lib/api";
import type { MaterialsDataset } from "@/lib/materials-vnext";

export function MaterialsDownloads() {
  const [state, setState] = useState<"idle" | "loading" | "ready">("idle");
  const [dataset, setDataset] = useState<MaterialsDataset | null>(null);
  async function load() {
    if (state !== "idle") return;
    setState("loading");
    setDataset(await getMaterialsDataset().catch(() => null));
    setState("ready");
  }
  if (state === "ready") return <MaterialsDatasetDownloads dataset={dataset} />;
  return <section className="materials-dataset-downloads" aria-labelledby="materials-downloads-heading" aria-busy={state === "loading"}>
    <h2 id="materials-downloads-heading">Download dataset</h2>
    <button type="button" className="site-text-link" onClick={load} disabled={state === "loading"}>
      {state === "loading" ? "Loading downloads…" : "Show dataset downloads"}
    </button>
  </section>;
}

export function MaterialsDatasetDownloads({ dataset }: { dataset: MaterialsDataset | null }) {
  return <section className="materials-dataset-downloads" aria-labelledby="materials-downloads-heading">
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
