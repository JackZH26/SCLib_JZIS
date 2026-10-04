# Probe-image-size security update

Current-main Security run `37166885671` failed both the Trivy filesystem scan and the frontend production audit on `probe-image-size 7.3.0`, reached through `plotly.js 2.35.2` and its React wrapper. [The official advisory](https://github.com/advisories/GHSA-gjj5-9665-rwrc) identifies the SVG parser denial-of-service issue as CVE-2026-104861 and lists `7.4.0` as the patched release.

The change adds `probe-image-size@<7.4.0: 7.4.0` to the existing pnpm overrides and regenerates the lockfile using the project's declared pnpm `9.12.0`. The generated diff changes only that override, package integrity, package snapshot and Plotly dependency edge.

Local checks used bundled Node `v24.19.0` and pnpm `9.12.0`:

- Frozen installation passed. Both production dependency paths resolve the actual installed `7.4.0` package.
- The unchanged CI command `pnpm audit --prod --audit-level high` passed, with zero high or critical findings. One moderate `fast-uri` finding remains. A separate JSON diagnostic reported that moderate finding and exited 1; its actual output is retained.
- Fifteen installed-parser cases passed: SVG/PNG dimensions, viewBox and BOM handling, one-byte streams, invalid dimensions, malformed buffers up to 200,000 bytes, and the patched 10,240-byte SVG-header bound. Every case ran in a separate subprocess with a five-second limit; the longest measured parser case took 212.723 ms. These bounded measurements are local regression evidence.
- `pnpm test` passed 46 source-contract tests and 2,409 unit/component tests in 92 files.
- `pnpm build` passed type validation and generated all 54 static pages.

These checks cover the dependency diff based on `0a35c5dfccfd03c5f15d8ed5e56f8b58309648f5`. The new commit's CI, signed release and production deployment require their own verification.

