# Source-computed research hypotheses

This independent dataset publishes 103 composition groups as unscored research
hypotheses. It does not add COD coordinate proposals, formal RPS scores, ranks,
human scientific reviews, experimental superconductivity or room-temperature
claims. All retained route assessments concern geometry or ordered-site
construction within stated source approximations. Physical orbital bandwidth
and mobile-carrier benefits remain unknown.

Earlier private-screening decisions are now published in this unscored
catalogue. Historical references to private assessment remain as context;
they do not describe the current publication status or a human review.

Source: Tiago F. T. Cerqueira, Antonio Sanna and Miguel A. L. Marques,
*Sampling the materials space for conventional superconducting compounds*,
Materials Cloud 2023.163 v1, [DOI 10.24435/materialscloud:qv-bq](https://doi.org/10.24435/materialscloud:qv-bq),
[record](https://archive.materialscloud.org/records/3kbt5-r3n56).
The source record declares [CC BY 4.0](https://creativecommons.org/licenses/by/4.0/).
The public projection retains attribution and identifies its additional
screening commentary and wording correction. Per-material download URLs are
not invented: AGM IDs and original archive directory locators identify source
states inside the dataset.

The complete JSON retains all 103 source/control identities, source Eliashberg
Tc values in K at mu*=0.1, signed lambda contrasts, seven screening explanations,
risks, adverse controls and next falsifiable actions. Source Tc is a separate
model product, not an individual Gaussian-width result or an error interval.
Absent full ten-point vectors remain null rather than reconstructed.

Each `details/<source_state>.json` contains the exact same candidate record and
shared source context. The detail manifest pins every byte sequence. The server
loader checks these against the full catalogue, then supplies only a small
browse projection. Clients request and verify a detail only when opened.
Risk previews are excerpts; the full detail and complete download retain the
original risk and decision text. Attention labels are neither rejection rules
nor inferred magnetic measurements.

Local paths, accounts and private execution resources are omitted. Artifact
digests are marked `digest_reference`, not represented as downloadable evidence.
Scientific unit fields, frequency-path observations, width tokens and all
countercontrol directions are retained. The only scientific-prose correction
is the unrelated Nb2TiMo precedent in the Nb2HfTa novelty sentence; it now refers
to different-composition HfNbTa. Frozen scientific inputs are not changed.

To reproduce, supply the two pinned source files explicitly:

```sh
python3 scripts/build_discovery_source_hypotheses.py \
  --index /path/to/candidate-index.json \
  --eligibility /path/to/discovery-publication-eligibility-103-20261007-v1.json \
  --output-dir frontend/public/research-hypotheses
```

The generator validates frozen input hashes and refuses to replace a different
output. It performs no new scientific calculation, model fit or source download.
