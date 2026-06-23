#!/usr/bin/env bash
# Run one APS harvest-ready ingest batch, automatically advancing from
# newer years to older years.
#
# This is intentionally one-shot. A systemd timer or external monitor can
# call it repeatedly; the checkpoint decides what remains pending.

set -Eeuo pipefail

SCLIB_ROOT="${SCLIB_ROOT:-/opt/SCLib_JZIS}"
MANIFEST_ROOT="${APS_MANIFEST_ROOT:-/opt/sclib_aps_manifests}"
START_YEAR="${APS_START_YEAR:-2026}"
END_YEAR="${APS_END_YEAR:-1986}"
BATCH_SIZE="${APS_BATCH_SIZE:-125}"
LOCKFILE="${APS_LOCKFILE:-/var/lock/sclib-aps-yearly-ingest.lock}"
LOG_DIR="${MANIFEST_ROOT}/reports/logs"
RUNNER_LOG="${LOG_DIR}/aps_yearly_runner.log"
SKIP_YEARS_FILE="${LOG_DIR}/aps_yearly_skip_years.txt"

mkdir -p "${MANIFEST_ROOT}/checkpoints" "${LOG_DIR}" "$(dirname "${LOCKFILE}")"

if [[ "${SCLIB_APS_RUNNER_LOCKED:-}" != "1" ]]; then
    export SCLIB_APS_RUNNER_LOCKED=1
    exec flock --nonblock --conflict-exit-code 99 "${LOCKFILE}" "$0" "$@"
fi

log() {
    printf '[%s] %s\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)" "$*" | tee -a "${RUNNER_LOG}"
}

load_skip_years() {
    if [[ -f "${SKIP_YEARS_FILE}" ]]; then
        tr '\n' ' ' < "${SKIP_YEARS_FILE}" | xargs echo -n
    fi
}

append_skip_year() {
    local year="$1"
    touch "${SKIP_YEARS_FILE}"
    if ! grep -qx "${year}" "${SKIP_YEARS_FILE}" 2>/dev/null; then
        printf '%s\n' "${year}" >> "${SKIP_YEARS_FILE}"
    fi
}

select_year() {
    MANIFEST_ROOT="${MANIFEST_ROOT}" START_YEAR="${START_YEAR}" END_YEAR="${END_YEAR}" SKIP_YEARS="${1:-}" \
        python3 - <<'PY'
import json
import os
from pathlib import Path

root = Path(os.environ["MANIFEST_ROOT"])
start = int(os.environ["START_YEAR"])
end = int(os.environ["END_YEAR"])
skip_years = {
    int(x) for x in os.environ.get("SKIP_YEARS", "").split() if x.strip()
}
terminal_statuses = {"unsupported_no_jats", "unsupported_no_text"}


def read_dois(path: Path) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    if not path.exists():
        return out
    for raw in path.read_text(errors="ignore").splitlines():
        line = raw.split("#", 1)[0].strip()
        if not line:
            continue
        doi = line.split()[0].strip().rstrip(".,;)]}").lower()
        if doi and doi not in seen:
            seen.add(doi)
            out.append(doi)
    return out


def latest_checkpoint(paths: list[Path]) -> dict[str, dict]:
    latest: dict[str, dict] = {}
    for path in sorted(paths, key=lambda p: (p.stat().st_mtime, p.name)):
        if not path.exists():
            continue
        for raw in path.read_text(errors="ignore").splitlines():
            if not raw.strip():
                continue
            try:
                rec = json.loads(raw)
            except json.JSONDecodeError:
                continue
            doi = str(rec.get("doi") or "").strip().lower()
            if doi:
                latest[doi] = rec
    return latest


def is_terminal(rec: dict) -> bool:
    status = str(rec.get("status") or "").strip()
    if status in terminal_statuses:
        return True
    if status != "error":
        return False
    err = str(rec.get("error") or rec.get("result", {}).get("error") or "")
    return "404 not found: /v2/journals/articles/" in err


for year in range(start, end - 1, -1):
    if year in skip_years:
        continue
    manifest = root / "yearly" / f"aps_{year}_harvest_ready.txt"
    dois = read_dois(manifest)
    total = len(dois)
    if total == 0:
        continue
    checkpoint_paths = list((root / "checkpoints").glob(f"aps_{year}*.checkpoint.jsonl"))
    latest = latest_checkpoint(checkpoint_paths)
    ok = sum(1 for doi in dois if str(latest.get(doi, {}).get("status") or "") == "ok")
    terminal = sum(1 for doi in dois if is_terminal(latest.get(doi, {})))
    errored = sum(
        1 for doi in dois
        if str(latest.get(doi, {}).get("status") or "") == "error"
        and not is_terminal(latest.get(doi, {}))
    )
    pending = total - ok - terminal
    if pending > 0:
        print(f"YEAR={year}")
        print(f"TOTAL={total}")
        print(f"OK={ok}")
        print(f"TERMINAL={terminal}")
        print(f"ERROR={errored}")
        print(f"PENDING={pending}")
        raise SystemExit(0)

print("YEAR=")
print("TOTAL=0")
print("OK=0")
print("TERMINAL=0")
print("ERROR=0")
print("PENDING=0")
PY
}

progress_for_year() {
    local year="$1"
    MANIFEST_ROOT="${MANIFEST_ROOT}" YEAR="${year}" python3 - <<'PY'
import json
import os
from pathlib import Path

root = Path(os.environ["MANIFEST_ROOT"])
year = int(os.environ["YEAR"])
manifest = root / "yearly" / f"aps_{year}_harvest_ready.txt"
terminal_statuses = {"unsupported_no_jats", "unsupported_no_text"}

dois = []
seen = set()
for raw in manifest.read_text(errors="ignore").splitlines():
    line = raw.split("#", 1)[0].strip()
    if not line:
        continue
    doi = line.split()[0].strip().rstrip(".,;)]}").lower()
    if doi and doi not in seen:
        seen.add(doi)
        dois.append(doi)

latest = {}
checkpoint_paths = sorted(
    (root / "checkpoints").glob(f"aps_{year}*.checkpoint.jsonl"),
    key=lambda p: (p.stat().st_mtime, p.name),
)
for path in checkpoint_paths:
    for raw in path.read_text(errors="ignore").splitlines():
        if not raw.strip():
            continue
        try:
            rec = json.loads(raw)
        except json.JSONDecodeError:
            continue
        doi = str(rec.get("doi") or "").strip().lower()
        if doi:
            latest[doi] = rec


def is_terminal(rec: dict) -> bool:
    status = str(rec.get("status") or "").strip()
    if status in terminal_statuses:
        return True
    if status != "error":
        return False
    err = str(rec.get("error") or rec.get("result", {}).get("error") or "")
    return "404 not found: /v2/journals/articles/" in err

total = len(dois)
ok = sum(1 for doi in dois if str(latest.get(doi, {}).get("status") or "") == "ok")
terminal = sum(1 for doi in dois if is_terminal(latest.get(doi, {})))
errored = sum(
    1 for doi in dois
    if str(latest.get(doi, {}).get("status") or "") == "error"
    and not is_terminal(latest.get(doi, {}))
)
print(
    f"year={year} total={total} ok={ok} terminal={terminal} "
    f"error={errored} pending={total - ok - terminal}"
)
PY
}

progress_value() {
    local key="$1"
    local line="$2"
    for token in ${line}; do
        if [[ "${token}" == "${key}="* ]]; then
            echo "${token#*=}"
            return 0
        fi
    done
    return 1
}

cd "${SCLIB_ROOT}"

chmod 0777 "${MANIFEST_ROOT}/checkpoints" "${MANIFEST_ROOT}/reports" "${LOG_DIR}" 2>/dev/null || true
chmod a+rw "${MANIFEST_ROOT}"/checkpoints/*.checkpoint.jsonl 2>/dev/null || true

while true; do
    skip_years="$(load_skip_years)"
    selection="$(select_year "${skip_years}")"
    eval "${selection}"

    if [[ -z "${YEAR:-}" ]]; then
        log "DONE all APS harvest-ready manifests complete for ${START_YEAR}..${END_YEAR}"
        exit 0
    fi

    manifest="${MANIFEST_ROOT}/yearly/aps_${YEAR}_harvest_ready.txt"
    checkpoint="${MANIFEST_ROOT}/checkpoints/aps_${YEAR}_harvest_ready.checkpoint.jsonl"
    year_log="${LOG_DIR}/aps_${YEAR}_autostart.log"

    log "START APS yearly batch year=${YEAR} total=${TOTAL} ok=${OK} terminal=${TERMINAL} error=${ERROR} pending=${PENDING} limit=${BATCH_SIZE}"

    set +e
    docker compose -f docker-compose.yml run --rm \
        -v "${MANIFEST_ROOT}:${MANIFEST_ROOT}" \
        ingestion \
        python -m ingestion.aps_batch \
            --manifest "${manifest}" \
            --checkpoint "${checkpoint}" \
            --limit "${BATCH_SIZE}" \
            --retry-failed \
            -v 2>&1 | tee -a "${year_log}" | tee -a "${RUNNER_LOG}"
    batch_rc=${PIPESTATUS[0]}
    set -e

    before_ok="${OK}"
    before_terminal="${TERMINAL}"
    progress_line="$(progress_for_year "${YEAR}")"
    after_ok="$(progress_value ok "${progress_line}")"
    after_terminal="$(progress_value terminal "${progress_line}")"
    log "batch exit=${batch_rc} ${progress_line}"

    set +e
    "${SCLIB_ROOT}/scripts/sclib-daily-aggregate.sh" 2>&1 | tee -a "${RUNNER_LOG}"
    aggregate_rc=${PIPESTATUS[0]}
    set -e

    if [[ "${aggregate_rc}" == "99" ]]; then
        log "aggregate skipped by lock; treating as ok"
        aggregate_rc=0
    else
        log "aggregate exit=${aggregate_rc}"
    fi

    leftovers="$(find /dev/shm /tmp -maxdepth 3 -name 'aps-*' -type d 2>/dev/null | head -20 || true)"
    if [[ -n "${leftovers}" ]]; then
        log "WARN APS temp leftovers detected: ${leftovers//$'\n'/, }"
    fi

    if (( aggregate_rc != 0 )); then
        exit "${aggregate_rc}"
    fi

    if (( batch_rc != 0 )); then
        if [[ "${after_ok}" == "${before_ok}" && "${after_terminal}" == "${before_terminal}" ]]; then
            log "SKIP year=${YEAR} because batch failed with zero progress (ok=${after_ok}, terminal=${after_terminal})"
            append_skip_year "${YEAR}"
            continue
        fi
        log "RETRY same year=${YEAR} after partial progress despite batch error"
        continue
    fi

    log "ADVANCE next year after successful batch"
done
