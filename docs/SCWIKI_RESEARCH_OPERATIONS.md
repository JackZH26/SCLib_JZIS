# Independent SCWiki research editions

Research content has its own store and publication process. It is not an article
catalogue migration and must not trigger a website build or Git push for each edition.

## One-time integration

1. Install the frontend routes in this change through the normal site release
   gates. Do not silently include unrelated, unpublished scientific edits.
2. Initialize a persistent directory with `frontend/content/scwiki/research-issues.json`
   as `research.json`. Keep it outside the code checkout and release directories.
3. Mount the **directory**, read-only, into the frontend. A file bind mount would
   continue referencing the old inode after an atomic rename. The example
   `docker-compose.research.yml` uses `SCWIKI_RESEARCH_DIRECTORY` on the host and
   `SCWIKI_RESEARCH_STORE=/var/lib/scwiki-research/research.json` in the frontend.
4. Install `scwiki-research-publish.mjs` and `scwiki-research-model.mjs` together in
   a separate worker directory with Node.js. The publisher needs write access only
   to its content directory. Website requests have read access only. Public content
   files are mode 0644; private review receipts and candidate abstracts are not
   mounted into the website.
5. Verify a new issue appears in HTML, JSON and RSS while the website build ID and
   process stay unchanged. Verify older issue URLs and snapshot digests remain.
   This integration is a one-time website deployment; subsequent publications are
   data operations only.

Without `SCWIKI_RESEARCH_STORE`, development uses the checked-in seed. This fallback
does not mean an independent production update service has been installed.

## Weekly worker

Use a standalone weekly editorial task on the Mac mini, Monday at 09:00 UTC+8.
The desktop app and machine must be running. It must not re-enable the deleted
half-hour development automation, edit application code, merge a PR, build images,
restart the website, buy credits or change billing.

Each run:

1. Check model availability and the content worker status. On exhausted usage,
   save a checkpoint and report it; use a reset only when available and explicitly
   approved for that occurrence.
2. Read the current store and real ISO week. If the week already exists, do not
   publish a duplicate. Missed weeks are not fabricated or backdated.
3. Run `scripts/scwiki_research_collect.py --state-dir PRIVATE_RUN_DIRECTORY`.
   This retrieves at most 100 arXiv submissions from the preceding 14 days.
   It is one discovery source, not an exhaustive survey. Review publisher pages
   and other primary sources as well. Respect rate limits; never turn a retrieval
   failure into a successful empty edition.
4. Read the original paper abstract/full text available for each candidate.
   Verify title, identity, publication/version date and status. Mark preprints.
   Write original English summaries, why the work matters, limits of evidence and
   links to real Wiki topics. Aim for 3–6 useful selections, but do not fill a quota.
   Include `versionDate` when a newly released version of an older paper is selected.
5. Save `candidate.json` as `{"kind":"issue","record":{...}}`. Save a separate
   primary-source review receipt with exact candidate SHA-256, `outcome:
   review-complete`, source URLs, titles, statuses, check dates, evidence locations
   and limitations. `tools/research_ops.py` in the local workspace checks this
   receipt and the 14-day window before preview publication. A schema check does
   not certify scientific accuracy.
6. Run the publisher against the configured independent store:

   ```sh
   node scwiki-research-publish.mjs --store /persistent/research.json \
     --seed /worker/seed.json --candidate /private/candidate.json
   ```

   This creates a single writer lock, preserves a backup, validates the whole
   collection and atomically replaces the content file. A repeated identical ID
   is a no-op; a conflicting ID fails. A lock is never taken over based on age.
   Inspect an interrupted worker before recovering its lock.
7. Read back the issue, archive and feed, verify the snapshot digest and record
   the outcome. Notify on a successful new edition, correction, failure or action
   needed. Keep unchanged duplicate runs quiet.

## History and corrections

The real 18 October 2026 selection is `2026-W42`. Its three original source-check
dates are retained. No earlier issues are invented, and the migration does not
claim to refresh the source checks.

Published issue records are immutable. Add `{"kind":"notice","record":{...}}` for
dated corrections, version updates or retractions. A notice keeps its source URL
and appears alongside the old item and in RSS. A subsequent recommendation of the
same paper requires a different version and an explicit update reason, preserving
its stable paper ID and first-recommended week. Link arXiv and DOI identifiers
when a preprint becomes a journal article.

`snapshotRevision` identifies an original issue; `revision` identifies the issue
plus current notices. Clients must not use the website commit as a research edition
version. JSON endpoints, Markdown and RSS read the same runtime store. Archive
pagination cursors are bound to its revision.

Failed publication leaves the prior complete store visible. A process that has
already read a valid store can display it with a warning if an external edit corrupts
the file. On a cold start with an invalid configured store, the research API returns
503; the Wiki homepage still renders the article search and topics with a research
availability notice. Restore a verified backup rather than silently returning to an
old seed or discarding published editions.

## Acceptance scope

Use the local unified entrypoint `tools/scwiki.py test-weekly-research`, then a
clean snapshot build and `verify-weekly-preview`. The latter uses a separate
throwaway store/server for publication fixtures, preserving the user's preview.
It checks real hot updates with unchanged website build/PID, historical URLs,
duplicate/overwrite handling, archive filters, search section anchors and mobile
overflow. Backend database tests are not needed for this file-store feature.

Production installation and its first real content-only publication require their
own evidence; local tests do not establish that the production service is connected.
