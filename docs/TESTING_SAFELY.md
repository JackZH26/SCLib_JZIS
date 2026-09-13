# Disposable API and migration tests

Implemented for EN01 (#42), with the locked-install/provenance portion of EN04
(#52). API tests intentionally create/drop the application schema and flush
Redis between tests. **Never point these tests at a development, staging,
production, restored research, or shared service.**

## One entry point, no reusable DSNs

`scripts/run_disposable_tests.py` is the only supported API/migration test entry
point. It creates new services and randomly named credentials, validates them,
runs tests, then removes only the services and temporary data it created.
It does not accept connection URLs, attach to existing services, use Compose,
mount a project database volume, or automatically install service binaries.

Run with the project's existing Python environment after a locked install:

```bash
cd api
uv sync --locked --extra dev --python 3.11
.venv/bin/python ../scripts/run_disposable_tests.py --backend docker --suite api -- -q
.venv/bin/python ../scripts/run_disposable_tests.py --backend docker --suite migrations
```

Docker mode requires a running local default Docker context and already
available `postgres:16-alpine` and `redis:7-alpine` images. The runner uses
`--pull never`. CI explicitly prepares these images in its disposable runner;
local users may prepare them separately when authorized. Remote Docker contexts
and published ports other than `127.0.0.1` are refused. Containers have unique
run labels/full IDs, random high host ports and temporary data, with no shared
named database volumes. The Redis config is the only generated bind mount.

Where Docker is unavailable but PostgreSQL and Redis binaries are already
installed, an explicit native fallback creates a **new** private cluster and
new foreground child processes. Example for a Homebrew installation:

```bash
api/.venv/bin/python scripts/run_disposable_tests.py \
  --backend native \
  --postgres-bin /opt/homebrew/opt/postgresql@16/bin \
  --redis-bin /opt/homebrew/opt/redis/bin/redis-server \
  --suite api -- -q tests/test_disposable_environment.py
```

Use the same arguments with `--suite migrations` and no pytest arguments to
exercise empty-database-to-head migration and schema verification. Native mode
does not call `brew services`, reuse a data directory, stop an existing server,
or connect to a default port. Service version differences between native local
testing and Linux CI must be recorded; the fallback is not image parity proof.

## Capacity tests use their own service lifetime

`api/tests_capacity` is a separate suite, deliberately outside the ordinary
`tests` discovery path. It imports the same pre-client capability guard and
owned-schema fixture. Run it with a **new** invocation, never appended to the
ordinary API session:

```bash
api/.venv/bin/python scripts/run_disposable_tests.py \
  --backend docker --suite api -- -q tests_capacity
```

The explicit native fallback above also supports `--suite api -- -q tests_capacity`.
The API CI job invokes this suite separately after the ordinary API suite. Each
invocation creates and cleans up its own services. No quota override, shared
database, recycled capability or table reset between cases is needed.

The private review test fills the actual 32 MiB logical live-payload cap, then
checks concurrent last-slot admission, atomic rejection at capacity, reclamation
after purge and original-key replay without resurrection. Its synthetic text is
compressible: retained `octet_length` is the measured quantity, not physical disk
use. This is a correctness test, not a throughput, production load, licence or
scientific-acceptance measurement. Immutable audit rows intentionally survive
throughout that invocation, so mixing it with other API tests would consume
their shared quota and invalidate the experiment.

## Guard layers

1. Before importing application/database/client modules, the API conftest and
   migration test wrapper require `ENVIRONMENT=test` and a valid capability.
   Ordinary `pytest` without the runner fails closed, including collection.
2. A capability binds a random run ID to an owner-only `0700` temporary
   directory and `0600` nonsymlink manifest, a live runner PID and a short expiry.
   It is not a checkbox such as “database name contains test”. Do not fabricate,
   copy, export or reuse this file; expiry or runner exit invalidates it.
3. Both service URLs must match their exact capability hashes, generated roles,
   credentials, strict `127.0.0.1` host, allocated high port and database. Query
   overrides, fragments, default ports, remote hosts and alternate Redis DBs are
   rejected before a client is created. Cached Settings are checked as well.
4. Native services must still be direct children of this runner, with the
   expected executable/data directory/port. Docker services must have the exact
   owned container ID/label and port binding on the local daemon.
5. Before destructive SQL, the connected PostgreSQL role/database and a
   bootstrap-owned run marker are verified. The app role is NOSUPERUSER,
   NOCREATEDB, NOCREATEROLE, NOREPLICATION and NOBYPASSRLS; it owns only this
   run's application database. The private bootstrap identity is not given to
   the test process.
6. Redis has one database and a per-run ACL user; default access is disabled.
   Only this disposable user's DB may be flushed. FLUSHALL, CONFIG and ACL
   administration are denied. The server's runtime ID is rechecked before
   cleanup, and survives FLUSHDB.

The test subprocess receives a minimal environment with generated test settings
and no inherited service/cloud/email credentials. API and migration tests disable
`.env` loading in their own process; production Settings are unchanged. The
fixture guard is checked again at engine creation and cleanup boundaries.

This protects against accidental configuration mistakes and stale/reused
capabilities. It is not a security sandbox against a local user who can edit
tests or a hostile Docker daemon. Provider calls must still be mocked by tests;
the runner supplies no usable cloud credentials but does not implement an OS
network sandbox for all Python code.

## Prepare tokenizer data before offline tests

The `tiktoken` wheel does not include the `cl100k_base` ranks. A cold cache would
make its first import attempt an HTTPS download, which the corpus tests rightly
reject. After the locked dependency install, prepare this public dependency in
an explicit network-enabled installation step, using the same Python runtime
and cache settings as the tests:

```bash
api/.venv/bin/python -c "import tiktoken; tiktoken.get_encoding('cl100k_base')"
api/.venv/bin/python -m pytest -q scripts/tests
```

The installed constructor verifies the ranks against its SHA-256; the asset test
also pins `223921b76ee99bde995b7ff738513eef100fb51d18c93597a113bcffe865b2a7`.
It launches a fresh subprocess with socket creation blocked and checks actual
multilingual tokenization/round-trip. Missing/corrupt caches fail; tests do not
download data, skip corpus checks or substitute a fake tokenizer. A tokenizer
asset change requires deliberate compatibility review, not updating a digest
just to pass tests. This is a tokenization dependency, not an embedding-model
download, paid provider call or upload of research content.

All three Python CI jobs now prepare the dependency explicitly with a two-minute
step limit. CI uses the library's default cache, shared by these steps and the
sanitized owned-service runner via its existing temporary-directory policy.
Do not set an empty `TIKTOKEN_CACHE_DIR` (which disables caching); custom cache
settings used outside the runner are not automatically forwarded into it.

API and ingestion image builds prepare the same hash-verified ranks in
`/opt/tiktoken-cache`. Each Dockerfile then runs a real tokenizer smoke check as
UID 1001 with BuildKit `--network=none`. This adds an executable image-build
gate; source checks and native subprocess tests alone do not prove a Linux
image was built or that a deployed image contains the ranks. No existing image
or deployment is changed by editing these Dockerfiles.

## Safe tests before any service is started

These standard-library tests do not load the API conftest or open sockets:

```bash
api/.venv/bin/python -m unittest discover -s scripts/tests -p test_test_safety.py -v
api/.venv/bin/python -m unittest discover -s scripts/tests -p test_runtime_inventory.py -v
```

They instrument application/client imports and socket creation, prove invalid
DSNs/sentinels fail first, and verify that error messages do not disclose URLs
or passwords. Integration coverage in `api/tests/test_disposable_environment.py`
checks actual least-privilege PostgreSQL and Redis cleanup behavior only after
the guard has accepted newly created services.

## Interrupted runs and cleanup

Normal completion/failure removes this run's created processes/containers and
private temporary files. No broad `docker prune`, service restart, database
wipe command or deletion of a repository directory is used. If the runner is
forcibly killed, do not reuse its manifest. Inspect the specific remaining
container's full ID and run label, or native PID/parent and private data path,
before removing that exact abandoned resource. Never infer cleanup targets from
a broad name glob or from inherited DSNs. A failed ownership check requires
operator investigation, not a forced bypass.

## Locked dependencies and image parity (EN04)

API, migration and ingestion CI jobs pin `uv==0.11.16` (the tool version used by
the current API/ingestion Dockerfiles), consume their own `uv.lock` using
`uv sync --locked --extra dev`, and upload an actual installed-package inventory
with both lock/pyproject digests and Python/platform identity. Lock inconsistency fails the
install instead of resolving a fresh dependency graph. Frontend
`pnpm install --frozen-lockfile` behavior is unchanged.

`scripts/runtime_inventory.py --lock api/uv.lock --pyproject api/pyproject.toml --revision <full-checked-out-git-sha>` captures the current interpreter,
not the interpreter selected by the path to the lock. Run it inside each actual
environment to avoid inventing parity. Compare an actual runtime-image inventory
against its test inventory with:

```bash
python scripts/runtime_inventory.py --runtime image-runtime.json --tests test-runtime.json
```

Version 2 rejects old/malformed inventories, duplicate package identities,
unrepresented installed versions, absent project distributions and duplicate
JSON keys. Comparisons require matching lock, pyproject, collector bytes, full
source revision, Python minor/implementation, OS and architecture, and every
runtime package version. Test-only allowances are exactly `pytest`,
`pytest-asyncio`, `ruff`, `iniconfig`, `pluggy`, and `pygments`: test tools and
their exclusive dependencies from the current dev extras. These are not wildcards;
any package also present in runtime must match its runtime version. Unknown
extras fail. Python patch versions are recorded but not required equal; OS native
libraries, wheel bytes/ABI, Python patch parity and application behavior are not
proved by this package-version comparison. Inventories contain no environment
values, DSNs, source text or credentials. Re-capture v1 artifacts; do not relabel
them as v2.

All three Python CI jobs now run `scripts/run_runtime_parity.py`: API and
migration jobs each build `api/Dockerfile`, while ingestion builds
`ingestion/Dockerfile`. This checks the actual independent test environment in
each job, rather than assuming API/migration inventories are interchangeable.
The existing six jobs and frontend frozen-lockfile paths are preserved. An
image mismatch fails the job before API/migration/ingestion execution. Tests
still use the owned-service guard; the parity tool never supplies a test DSN.

The helper matches the current release workflow's `linux/amd64` platform and
requires Linux/x86_64 test inventories, a local default Unix Docker daemon, clean tracked
build inputs and no untracked project inputs. It refuses inherited Docker
connection overrides. It builds the checked-out release Dockerfile without
publishing/tagging an image, records the immutable local image ID and Dockerfile
digest, and binds/validates build-input labels. Build dependency downloads need
ordinary CI network access. Only the **inventory process** is network-isolated:
it explicitly overrides ENTRYPOINT to `/opt/venv/bin/python -I -B -`, disables
healthchecks, runs as UID 1001 with read-only rootfs/no capabilities and
`--network none`, and receives only the identical collector script via stdin.
There are no volume/secret/socket mounts or inherited environment settings.
Neither the API entrypoint/migration, ingestion default command, application
imports nor service probes are executed. Exact-ID/run-label checks scope
interrupted-container cleanup; no image prune or shared-service cleanup occurs.
Local build layers remain only in the disposable CI runner cache until that
runner is destroyed.

Test/image inventories and the parity report are uploaded per job outside the
Docker build context, including on comparison failure. Missing artifacts fail
upload; build/preflight failures may have only the test inventory and a failing
job, never a fabricated passing report. Fresh runner builds use the exact lock
and pyproject COPY layers, so changed inputs invalidate those layers; there is
no independently keyed stale parity cache.

Run the no-network mocked checks locally without Docker or uv:

```bash
api/.venv/bin/python -m unittest discover -s scripts/tests -p 'test_runtime_*.py' -v
```

**Still required for full EN04 closure:** execute these jobs in Linux CI and
review the actual image/test inventory artifacts, owned-service integration and
release-gating configuration. Local mocked tests are not image execution proof.
These candidate-image checks do not establish that an already published or
deployed image matches them; an approved release must bind its final image
digest to the tested revision. No production image, registry, database,
deployment or remote CI run was used to implement this follow-up.
