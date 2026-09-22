# Restore-repair native capture scan review — September 15

Actual capture commit: `2374b5a42608300257316a3a49245e077e53a1ec`.
The redacted immutable-commit scan reported 13 generic-api-key matches in
three native.delivery20260915r2 JSON fixture lines. Every match was checked
against its original source columns. All are generated request_key values:
one UUID in the Discovery barrier fixture, six synthetic participation/pilot
keys and six synthetic declaration/withdrawal keys.

The generators and account boundaries are the same reviewed disposable-test
paths described in [the first delivery triage](Secret_Scan_Triage_Delivery_2026-09-15.md).
These identifiers do not authenticate a caller. Original captured bytes and all
older archives remain unchanged. Only the three actual commit/path/rule/line
fingerprints were added, with matching exact-set tests; no path or rule ignore
was introduced. The original redacted report is retained privately as
`/private/tmp/sclib-delivery-20260915-cvlj6qk5/restore-capture-scan.json`.
