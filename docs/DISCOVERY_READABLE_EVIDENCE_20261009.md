# Discovery readable evidence notes

The expanded source-candidate details include a display-only companion for 21
previously compressed or ambiguous notes across nine materials: Ti2ZrW, TiTa2W,
TiTa3, TiZr3, ZrTc2, Cr2Tc, ScZr3N4, YZr3N4 and ZrNb2Ta. The default one-row
catalogue, source Tc values, C/E1 assessments and ordering are unchanged.

`frontend/lib/resources/discovery-readable-evidence-2026-10-09.json` contains
explicit English paraphrases. Each entry binds its candidate ID, source state,
formula, dossier hash, source-detail hash and original text hash. The component
applies the companion only after the existing source-detail and dossier byte/hash
verifiers succeed. Only the five declared prose fields are eligible; arbitrary
scientific or scoring keys are rejected. If any matching entry is invalid or
stale, the entire candidate falls back to the original notes. This failure never
changes source verification or suppresses otherwise verified evidence.

Affected details show **Reader’s summary** and a closed **Original source notes**
disclosure containing the exact original strings. The full source JSON and
catalogue download remain unchanged. Ambient-scope copy, if added later, must
match both the dossier copy and `detail.ambient_scope`, the field actually shown.

The companion is not an evidence input or a scientific approval. In particular:

- Printed zero forces and sampled phonons do not establish converged structures
  or full Brillouin-zone stability.
- TiZr3's pressure/stress terminology and Ti2ZrW's differing force definitions
  remain unresolved in the underlying sources.
- Alternative controls and discordant coupling/Tc directions remain visible.
- Phase-level energies do not become exact-state energies; legacy internal
  grades do not become P, C/E1, RPS or success probabilities.
- A bounded literature review does not establish global novelty or experimental
  validation of an exact proposed phase.

The editorial review selected 21 explicit strings from the frozen public source
evidence. Its approved editorial mapping has SHA256
`a6e705c72ac1099a906f4b5ed9d9c73d368929ecc3fe374f7ea7272d13570eb7`.
This is an editorial trace, not a scientific-signoff artifact.

Validation covers every existing source/detail/dossier hash, all 21 mappings,
identity and hash drift, duplicate/unknown fields, original-note disclosure,
failed source verification, safe fallback, and unchanged support and ordering
for both research targets. No new calculations or experiments are introduced.
