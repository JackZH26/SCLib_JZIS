# APS OpenClaw Cron Fix

Last updated: 2026-06-18

## Context

The APS full-text ingest pipeline stopped progressing into 2023 because the
monitoring cron kept launching a fixed 2024 command after 2024 was already
complete.

Observed evidence on VPS2:

- `aps_2024_harvest_ready.txt`: 1039 total, 1039 ok, 0 pending.
- `aps_2023_harvest_ready.txt`: 918 total, only the first 125 ok when checked.
- Hourly logs kept showing 2024 runs with `selected=0 skipped=1039`.
- 2023 itself was not failing: its first batch had `selected=125 ok=125 error=0`.

Root cause: the scheduler selected a fixed year/path instead of deriving the
next unfinished year from manifests and checkpoints.

## Required Change

OpenClaw must stop calling a hard-coded command such as:

```bash
python -m ingestion.aps_batch \
  --manifest /opt/sclib_aps_manifests/yearly/aps_2024_harvest_ready.txt \
  --checkpoint /opt/sclib_aps_manifests/checkpoints/aps_2024_harvest_ready.checkpoint.jsonl \
  --limit 125 \
  --retry-failed \
  -v
```

Instead, call the repo-managed one-shot runner:

```bash
/opt/SCLib_JZIS/scripts/aps-yearly-ingest-once.sh
```

This runner:

- scans `2026 -> 1986`;
- selects the newest year with pending harvest-ready DOI records;
- merges all same-year checkpoint files, including legacy names such as
  `aps_2025_batch01.checkpoint.jsonl`;
- runs one batch with `--retry-failed`;
- runs `aggregate-materials` after the batch;
- refreshes the stats cache;
- uses `flock` so overlapping cron invocations are skipped safely.

## Recommended Scheduler

Prefer the systemd timer that is already deployed on VPS2:

```bash
systemctl enable --now sclib-aps-yearly-ingest.timer
systemctl list-timers --all | grep sclib-aps-yearly-ingest
```

The timer fires near `*:05 UTC` and calls:

```bash
/opt/SCLib_JZIS/scripts/aps-yearly-ingest-once.sh
```

If OpenClaw must keep its own cron, the cron entry should only call the same
one-shot runner and should not call `ingestion.aps_batch` directly:

```cron
5 * * * * /opt/SCLib_JZIS/scripts/aps-yearly-ingest-once.sh >> /opt/sclib_aps_manifests/reports/logs/aps_yearly_runner.cron.log 2>&1
```

Do not run both the systemd timer and an OpenClaw cron at the same cadence
unless OpenClaw treats exit code `99` as a normal lock-skip.

## Progress Checks

Use this command to confirm which year should run next:

```bash
python3 - <<'PY'
from pathlib import Path
import json, collections

root = Path("/opt/sclib_aps_manifests")

def read_dois(year):
    p = root / "yearly" / f"aps_{year}_harvest_ready.txt"
    seen, out = set(), []
    if not p.exists():
        return out
    for raw in p.read_text(errors="ignore").splitlines():
        line = raw.split("#", 1)[0].strip()
        if not line:
            continue
        doi = line.split()[0].strip().rstrip(".,;)]}").lower()
        if doi and doi not in seen:
            seen.add(doi)
            out.append(doi)
    return out

def latest(year):
    latest = {}
    files = sorted(
        (root / "checkpoints").glob(f"aps_{year}*.checkpoint.jsonl"),
        key=lambda p: (p.stat().st_mtime, p.name),
    )
    for p in files:
        for raw in p.read_text(errors="ignore").splitlines():
            if not raw.strip():
                continue
            try:
                rec = json.loads(raw)
            except json.JSONDecodeError:
                continue
            doi = str(rec.get("doi") or "").strip().lower()
            if doi:
                latest[doi] = str(rec.get("status") or "").strip()
    return latest

for year in range(2026, 1985, -1):
    dois = read_dois(year)
    if not dois:
        continue
    state = latest(year)
    counts = collections.Counter(state.get(doi, "pending") for doi in dois)
    pending = len(dois) - counts.get("ok", 0)
    print(year, "total", len(dois), "ok", counts.get("ok", 0),
          "error", counts.get("error", 0), "pending", pending)
PY
```

The next scheduled run should choose the first year, scanning from 2026 down,
whose `pending` is greater than zero.

## Logs To Watch

- Runner log:
  `/opt/sclib_aps_manifests/reports/logs/aps_yearly_runner.log`
- Per-year ingest log:
  `/opt/sclib_aps_manifests/reports/logs/aps_YYYY_autostart.log`
- Systemd status:
  `systemctl status sclib-aps-yearly-ingest.service --no-pager -l`
- Timer status:
  `systemctl list-timers --all | grep sclib-aps-yearly-ingest`

Healthy runner start example:

```text
START APS yearly batch year=2023 total=918 ok=125 error=0 pending=793 limit=125
```

Bad pattern that must not recur:

```text
APS batch manifest=...aps_2024_harvest_ready.txt selected=0 skipped=1039 total=1039
```

If that repeats while an older year has pending DOI records, the scheduler is
still hard-coded incorrectly.

## Stop Conditions

OpenClaw should stop and report if any of the following happens:

- repeated non-lock non-zero exits;
- 401/403 from APS Harvest;
- high 404 rate after using `*_harvest_ready.txt`;
- repeated `[Errno 28] No space left on device`;
- APS temp directories remain after a run:

```bash
find /dev/shm /tmp -maxdepth 3 -name 'aps-*' -type d
```

Exit code `99` means another run already holds the lock. Treat it as a safe
skip, not a failure.

## Current Corrective Action

The runner and systemd timer have been deployed:

- `/opt/SCLib_JZIS/scripts/aps-yearly-ingest-once.sh`
- `/etc/systemd/system/sclib-aps-yearly-ingest.service`
- `/etc/systemd/system/sclib-aps-yearly-ingest.timer`

OpenClaw should align its cron task with this runner and stop maintaining a
separate fixed-year command.
