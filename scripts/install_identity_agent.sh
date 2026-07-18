#!/usr/bin/env bash
# Install three independently signed, short-lived OIDC identities on VPS2.
set -euo pipefail

if [[ $# -ne 2 ]]; then
  echo "usage: $0 PROJECT_NUMBER WORKLOAD_IDENTITY_POOL" >&2
  exit 2
fi

PROJECT_NUMBER="$1"
POOL_ID="$2"
ROOT="/etc/sclib/identity-agent"
RUNTIME_ROOT="/run/sclib-identity"
LIB_ROOT="/usr/local/lib/sclib"

[[ "$PROJECT_NUMBER" =~ ^[1-9][0-9]+$ ]]
[[ "$POOL_ID" =~ ^[a-z][a-z0-9-]{3,31}$ ]]
[[ "$(id -u)" == "0" ]] || {
  echo "identity-agent installation must run as root" >&2
  exit 1
}

install -d -m 0700 -o root -g root "$ROOT"
install -d -m 0755 -o root -g root "$RUNTIME_ROOT" "$LIB_ROOT"
install -m 0755 scripts/sclib_identity_agent.py "$LIB_ROOT/sclib_identity_agent.py"

for role in api ingestion backup; do
  key="$ROOT/$role-signing.key"
  jwks="$ROOT/$role.jwks.json"
  if [[ ! -f "$key" ]]; then
    umask 077
    openssl genpkey -algorithm RSA -pkeyopt rsa_keygen_bits:3072 -out "$key"
  fi
  chmod 0600 "$key"
  kid="$(python3 scripts/export_identity_jwks.py --private-key "$key" --output "$jwks")"
  printf '%s\n' "$kid" > "$ROOT/$role.kid"
  chmod 0644 "$jwks" "$ROOT/$role.kid"
  install -d -m 0750 -o root -g 1001 "$RUNTIME_ROOT/$role"
done

python3 - "$ROOT/config.json" "$PROJECT_NUMBER" "$POOL_ID" <<'PY'
import json
import os
import sys
import tempfile
from pathlib import Path

output = Path(sys.argv[1])
project_number = sys.argv[2]
pool_id = sys.argv[3]
workloads = []
for role in ("api", "ingestion", "backup"):
    kid = (output.parent / f"{role}.kid").read_text().strip()
    workloads.append(
        {
            "role": role,
            "issuer": f"https://api.jzis.org/sclib-identity/{role}",
            "subject": f"sclib-{role}-vps2",
            "audience": (
                f"https://iam.googleapis.com/projects/{project_number}/locations/global/"
                f"workloadIdentityPools/{pool_id}/providers/vps2-{role}"
            ),
            "kid": kid,
            "private_key": f"/etc/sclib/identity-agent/{role}-signing.key",
            "output": f"/run/sclib-identity/{role}/subject.jwt",
            "gid": 1001,
        }
    )
payload = {
    "token_ttl_seconds": 300,
    "interval_seconds": 60,
    "workloads": workloads,
}
fd, temporary_name = tempfile.mkstemp(prefix=".config.", dir=output.parent, text=True)
try:
    os.fchmod(fd, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as handle:
        json.dump(payload, handle, indent=2, sort_keys=True)
        handle.write("\n")
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(temporary_name, output)
finally:
    Path(temporary_name).unlink(missing_ok=True)
PY

install -m 0644 ops/systemd/sclib-identity-agent.service \
  /etc/systemd/system/sclib-identity-agent.service
systemctl daemon-reload
systemctl enable --now sclib-identity-agent.service
systemctl is-active --quiet sclib-identity-agent.service
echo "SCLib identity agent installed; configure GCP WIF before credential validation."
