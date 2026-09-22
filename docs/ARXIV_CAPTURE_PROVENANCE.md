# arXiv capture provenance — bounded ML01 implementation

Status: local implementation and mocked regression coverage; not a production
backfill, a verified historical dataset, or closure of ML01's full acceptance.

## Scientific boundary

An arXiv work identifier is stable across revisions. A `vN` suffix selects a
specific revision; an identifier without it refers to the most recent revision.
The implementation separates `PaperMetadata.arxiv_id` from `requested_version`
and uses `download_id` only for fetching and version-specific retries. It does
not create a new catalogue paper for every `vN`. The identifier syntax and
version-selector behavior follow the [official arXiv identifier documentation](https://info.arxiv.org/help/arxiv_identifier.html).

OAI exposes current article metadata. Its modification datestamp is not a
reliable original-submission or replacement timestamp. `created`, `updated`
and the OAI header datestamp remain bibliographic/metadata observations, never
new result-availability witnesses. See [arXiv's OAI documentation](https://info.arxiv.org/help/oa/index.html).

In particular, the material NER input prepends OAI title/abstract to parsed body
sections. A pinned v1 body plus current metadata is **mixed, unverified input**:
a later abstract can contain a result absent from v1. This batch records that
limitation instead of attaching the body's version to the extracted result.

## Capture and persistence

The normal arXiv pipeline fetches a fresh artifact once per paper invocation
(HTTP retries and the existing source-to-PDF fallback remain). It no longer
reuses legacy work-level `src/` or `pdf/` caches as current evidence. The legacy
objects and helpers are left untouched for other existing readers; they are
not upgraded, deleted or labelled version verified.

Explicit version selectors are preserved in requests. Artifact redirects are
checked before following them: only HTTPS `arxiv.org` / `export.arxiv.org`, the
recognized source/PDF endpoint and matching work/version are permitted. Query
parameters, credentials, fragments, non-provider hosts and loss/change of an
explicit version fail closed. No automatic Atom lookup or latest-version
discovery is added. `explicit_version_url` means an observed, identity-matching
provider URL, **not** independent content authentication or a publication date.

Fresh bytes are saved under `captures/arxiv/{work}/{kind}/sha256/{digest}`.
An explicit version additionally gets an immutable
`{kind}/versions/vN.json` digest anchor. Both use GCS `if_generation_match=0`.
An existing object is read with a generation precondition and must match exactly;
there is no unconditional overwrite. Different bytes for the same version/kind
cause an integrity failure, even if a provider legitimately repackaged a tarball
or regenerated a PDF. Resolving such a conflict requires a future explicit
reconciliation policy. A rejected attempt may leave a new digest object without
an accepted version anchor; it is not a scientific revision record.

`arxiv-ingestion-capture/1.0.0` is a derived diagnostic envelope:

| Group | Recorded meaning |
| --- | --- |
| `canonical_paper_id`, `requested_version` | Stable catalogue key and optional explicit selector; not a Work-table UUID |
| `artifact` | Actual response bytes SHA-256, byte count, UTC observation timestamp, allowlisted requested/resolved URLs, kind, version-binding status and immutable storage object |
| `metadata` | Hash of the parsed OAI record's ElementTree serialization (not wire bytes), separate title/abstract JSON digest, metadata observation timestamp, modified date and header datestamp |
| `ner_input` | SHA-256 and byte count of the document prepared for the prompt after the current 16,000-character limit; separate full assembled-text digest, truncation flag, sections used, representation, attempt status and input-binding status |
| `scientific_available_at`, `temporal_status` | Always `null` / `unknown`; no source-registry witness is fabricated |

The NER hash covers the document portion, not the full prompt, model request,
embedding input, parser binary or provider execution. Hashes, dates and storage
object names are stored; source excerpts and credentials are not copied into
the envelope. `metadata_captured_at` is the local metadata-parse observation,
not the article's announcement time. Historical failure-pool metadata without
this observation remains unknown.

The source parser's textual transformation is unchanged. A downloaded PDF is
archived but is not parsed by the current fallback: NER still uses metadata only.
A failed LaTeX parse also gives a metadata-only extraction. These cases set
`artifact_used=false`; skipping NER sets `status=not_run` and no input hash.
Otherwise the initial status is `prepared`: the document has been assembled
and hashed, but no NER call is claimed. It becomes `attempted` only when the
extractor is invoked. Attempted does not mean that a provider response succeeded
or that any extracted scientific assertion is correct.
Source and NER-input hashes must never be substituted for one another.

An immutable, content-addressed JSON manifest retains the bounded diagnostic
observation without source text. A preparation manifest is archived before
chunking and embedding, so those failures cannot erase the original observation
timestamp or exact prepared-input digest. After an NER attempt, a separate final
manifest links the earlier `prepared_manifest_object`; neither object is
overwritten or contains its own final address. Skipped NER needs only the first
manifest. The reference and envelope are attached to new
material records and to `papers.publication_ref.ingestion_capture`. The latter
is a current catalogue projection: unrelated object keys are merged, and a
non-object legacy value is retained under `legacy_publication_ref`. It is not an
append-only scientific occurrence ledger. Capturing observations does not grant
source visibility, extraction approval, or temporal eligibility. The derived
`ingestion_capture` key is excluded from legacy scientific occurrence identities;
original source claims remain identity-bearing.

## Compatibility and deliberate exclusions

- APS uses its existing, independent transient BagIt path. No APS body, ZIP,
  excerpt or new permanent artifact archive is introduced. Authorized abstract
  and derived Facts behavior, DOI work identity and deletion audit are unchanged.
- Old-style arXiv archive prefixes such as `cond-mat/` are preserved. Ambiguous
  previously stripped seven-digit identifiers are rejected rather than assigned
  a guessed archive. No legacy identifiers or source records are migrated.
- Existing unversioned retries still work; explicit v1/v2 retry entries now keep
  separate keys so one successful revision cannot clear another failed revision.
  A failed attempt retains only `last_capture_manifest_object` in retry metadata,
  linking its already archived observation without copying source text. Invalid
  or version-mismatched stored retry metadata is retained unchanged, marked
  terminal with a metadata/manual-review reason, and handled per entry; it cannot
  abort later retries or silently guess a missing archive/version identifier.
- Current SQL chunks and vector point IDs/year filters are unchanged. This does
  not establish historical vector retrieval, snapshot dependency closure, or a
  versioned re-embedding release (RG03).
- No automatic authoritative source-version/result-availability registry writes
  occur. Dates, hashes and complete input/source revision binding need separate
  evidence and review before strict temporal ML admission.
- A manifest alone does not reconstruct all past OAI metadata or the exact full
  model request. Immutable metadata/input archives, parser/model configuration,
  raw result occurrence binding and release closure remain later gates.
- Fresh fetching increases requests versus cache reuse, and immutable captures
  need object-storage capacity/retention planning. Existing throttles remain.

## Verification and remaining deployment gates

`ingestion/tests/test_arxiv_capture.py` uses synthetic bytes, XML, HTTP transports,
an in-memory GCS object store and compiled/mocked SQL. It covers version identity,
retry roundtrip, stale-cache refusal, redirect rejection, create-or-verify races
and mismatches, source/PDF/input separation, metadata/body mixing, actual prompt
truncation, no invented dates, and publication-reference merge construction.
APS pipeline/metadata tests are included in the bounded regression run.
`tests/test_capture_resilience.py` additionally mocks chunk/embed/archive
failures, prepared/attempted manifest transitions, exact input hashes, skipped
NER, bounded failure references, and invalid-metadata retry continuation.

No paper was fetched, no provider/GCS/database operation was performed by these
tests, and no production data was changed. Real provider redirects, GCS IAM and
precondition behavior, SQL execution under release infrastructure, cost/retention
policy and a reviewed historical result-occurrence dataset still require explicit
acceptance before deployment or ML01 closure.
