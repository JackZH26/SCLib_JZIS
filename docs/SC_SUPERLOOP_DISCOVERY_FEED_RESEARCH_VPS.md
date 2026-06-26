# SC SuperLoop Discovery Feed Service - Research VPS Runbook

## Goal

Deploy the public read-only SC SuperLoop Discovery feed service on the research
VPS so that VPS2 can pull:

- `https://discovery-feed.jzis.org/healthz`
- `https://discovery-feed.jzis.org/discovery-meta.json`
- `https://discovery-feed.jzis.org/discovery-feed.json`

Do not change VPS2 or SCLib website code in this task.

## Context

- DNS has already been configured for `discovery-feed.jzis.org`.
- VPS2 already has `/data/sclib/discovery` mounted into the SCLib API container.
- SCLib will keep reading only its local cache file:
  `/data/sclib/discovery/discovery_feed.json`.
- The research VPS should expose only reviewed public JSON, not internal state.

## Public Payload Sanitization

Before exposing `discovery-feed.json` publicly, sanitize the exported payload at
the exporter/source layer. The public JSON must not contain:

- internal filesystem paths such as `/data/...`, `/root/...`, `/opt/...`,
  `/tmp/...`, `/var/...`, `/home/...`, or `/Users/...`
- run-root, workspace, checkpoint, temp-dir, log, container, hostname, command,
  task, or job provenance
- `dossier_path`, local dossier file paths, or private report paths
- local URLs such as `localhost`, `127.0.0.1`, or `file://...`
- private notes, loop-control state, credentials, tokens, or operator-only
  debugging fields

Keep only public-safe provenance text, for example:

```text
SC SuperLoop reviewed discovery export
```

If a public dossier reference is needed, expose only a public HTTPS URL such as
`dossier_url`. Do not expose local paths.

## Important Constraints

- Bind the Python feed service to `127.0.0.1:3091`, not the public interface.
- Do not open port `3091` to the internet.
- Expose only read-only GET endpoints through nginx.
- Do not expose internal loop control, private notes, local filesystem paths, or
  write endpoints.
- If the exporter includes fields such as `dossier_path`, remove or null them
  from the public feed output before publishing.

## Paths

Research workspace:

```bash
/data/.openclaw/workspace/research/SC_SuperLoop
```

Feed files:

```bash
/data/.openclaw/workspace/research/SC_SuperLoop/reports/discovery_feed.json
/data/.openclaw/workspace/research/SC_SuperLoop/reports/discovery_meta.json
```

Server script:

```bash
/data/.openclaw/workspace/research/SC_SuperLoop/scripts/serve_public_discovery_feed.py
```

Exporter script:

```bash
/data/.openclaw/workspace/research/SC_SuperLoop/scripts/export_discovery_feed.py
```

## Step 1 - Verify And Export Feed

Run on the research VPS:

```bash
set -euo pipefail

cd /data/.openclaw/workspace/research/SC_SuperLoop

ls -l scripts/export_discovery_feed.py
ls -l scripts/serve_public_discovery_feed.py

python3 scripts/export_discovery_feed.py \
  --output /data/.openclaw/workspace/research/SC_SuperLoop/reports/discovery_feed.json \
  --meta-output /data/.openclaw/workspace/research/SC_SuperLoop/reports/discovery_meta.json

ls -l reports/discovery_feed.json reports/discovery_meta.json
jq . reports/discovery_meta.json
jq '.status, (.candidates | length)' reports/discovery_feed.json
```

Expected:

- `discovery_meta.json` contains `status`, `candidate_count`, and `sha256`.
- `candidate_count` is greater than `0`.
- `discovery_feed.json` contains public preview candidates.

Run the leak audit before continuing:

```bash
python3 - <<'PY'
import json
import re
import sys
from pathlib import Path

feed_path = Path("reports/discovery_feed.json")
meta_path = Path("reports/discovery_meta.json")

bad_key = re.compile(
    r"(dossier_path|run[_-]?root|workspace|checkpoint|temp|tmp|log|"
    r"hostname|host|container|command|argv|task|job|operator|secret|token|"
    r"credential|filesystem|path|dir|file)",
    re.I,
)
bad_value = re.compile(
    r"(/data/|/root/|/opt/|/tmp/|/var/|/home/|/Users/|\.openclaw|"
    r"run-root|run root|workspace|checkpoint|dossier_path|file://|"
    r"localhost|127\.0\.0\.1|0\.0\.0\.0)",
    re.I,
)

def walk(value, where="$"):
    leaks = []
    if isinstance(value, dict):
        for key, nested in value.items():
            key_text = str(key)
            child = f"{where}.{key_text}"
            if bad_key.search(key_text):
                leaks.append((child, "key", key_text))
            leaks.extend(walk(nested, child))
    elif isinstance(value, list):
        for index, nested in enumerate(value):
            leaks.extend(walk(nested, f"{where}[{index}]"))
    elif isinstance(value, str) and bad_value.search(value):
        leaks.append((where, "value", value[:240]))
    return leaks

leaks = []
for path in (feed_path, meta_path):
    payload = json.loads(path.read_text(encoding="utf-8"))
    leaks.extend((str(path), *leak) for leak in walk(payload))

if leaks:
    print("Public discovery feed leak audit FAILED:", file=sys.stderr)
    for filename, where, kind, sample in leaks[:80]:
        print(f"- {filename} {where} {kind}: {sample}", file=sys.stderr)
    if len(leaks) > 80:
        print(f"... {len(leaks) - 80} more leaks", file=sys.stderr)
    sys.exit(1)

print("Public discovery feed leak audit passed.")
PY
```

If this audit fails, patch `scripts/export_discovery_feed.py` first and rerun
the export. Do not continue to nginx or HTTPS until the audit passes.

## Step 2 - Create systemd Service

Run on the research VPS:

```bash
sudo tee /etc/systemd/system/sc-superloop-discovery-feed.service >/dev/null <<'EOF'
[Unit]
Description=SC SuperLoop public Discovery feed
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
WorkingDirectory=/data/.openclaw/workspace/research/SC_SuperLoop
Environment=SC_DISCOVERY_PUBLIC_HOST=127.0.0.1
Environment=SC_DISCOVERY_PUBLIC_PORT=3091
Environment=SC_DISCOVERY_PUBLIC_FEED_PATH=/data/.openclaw/workspace/research/SC_SuperLoop/reports/discovery_feed.json
Environment=SC_DISCOVERY_PUBLIC_META_PATH=/data/.openclaw/workspace/research/SC_SuperLoop/reports/discovery_meta.json
ExecStart=/usr/bin/python3 /data/.openclaw/workspace/research/SC_SuperLoop/scripts/serve_public_discovery_feed.py
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
EOF

sudo systemctl daemon-reload
sudo systemctl enable --now sc-superloop-discovery-feed.service
sudo systemctl status sc-superloop-discovery-feed.service --no-pager
```

Verify local service:

```bash
curl -fsS http://127.0.0.1:3091/healthz
curl -fsS http://127.0.0.1:3091/discovery-meta.json | jq .
curl -fsS http://127.0.0.1:3091/discovery-feed.json | jq '.status, (.candidates | length)'
```

## Step 3 - Configure nginx Reverse Proxy

Run on the research VPS:

```bash
sudo tee /etc/nginx/sites-available/discovery-feed.jzis.org >/dev/null <<'EOF'
server {
    listen 80;
    server_name discovery-feed.jzis.org;

    location = /healthz {
        proxy_pass http://127.0.0.1:3091/healthz;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
    }

    location = /discovery-meta.json {
        proxy_pass http://127.0.0.1:3091/discovery-meta.json;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        add_header Cache-Control "public, max-age=60" always;
    }

    location = /discovery-feed.json {
        proxy_pass http://127.0.0.1:3091/discovery-feed.json;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        add_header Cache-Control "public, max-age=300" always;
    }

    location / {
        return 404;
    }
}
EOF

sudo ln -sf /etc/nginx/sites-available/discovery-feed.jzis.org \
  /etc/nginx/sites-enabled/discovery-feed.jzis.org

sudo nginx -t
sudo systemctl reload nginx
```

## Step 4 - Enable HTTPS

Run on the research VPS:

```bash
if ! command -v certbot >/dev/null 2>&1; then
  sudo apt-get update
  sudo apt-get install -y certbot python3-certbot-nginx
fi

sudo certbot --nginx -d discovery-feed.jzis.org --redirect
sudo nginx -t
sudo systemctl reload nginx
```

## Step 5 - Public Verification

Run on the research VPS, or from any external machine:

```bash
dig +short discovery-feed.jzis.org

curl -fsS https://discovery-feed.jzis.org/healthz
curl -fsS https://discovery-feed.jzis.org/discovery-meta.json | jq .
curl -fsS https://discovery-feed.jzis.org/discovery-feed.json | jq '.status, (.candidates | length)'

curl -fsS -o /dev/null -w "%{http_code}\n" https://discovery-feed.jzis.org/
curl -fsS -o /dev/null -w "%{http_code}\n" https://discovery-feed.jzis.org/private
```

Expected:

- `/healthz` returns healthy status.
- `/discovery-meta.json` returns HTTP 200 and includes `sha256`.
- `/discovery-feed.json` returns HTTP 200 and candidate count greater than `0`.
- `/` returns `404`.
- `/private` returns `404`.

## Report Back

Report these outputs:

```bash
systemctl status sc-superloop-discovery-feed.service --no-pager
curl -fsS https://discovery-feed.jzis.org/healthz
curl -fsS https://discovery-feed.jzis.org/discovery-meta.json | jq .
curl -fsS https://discovery-feed.jzis.org/discovery-feed.json | jq '.status, (.candidates | length)'
curl -fsS -o /dev/null -w "%{http_code}\n" https://discovery-feed.jzis.org/
curl -fsS -o /dev/null -w "%{http_code}\n" https://discovery-feed.jzis.org/private
```

## Acceptance Criteria

- `sc-superloop-discovery-feed.service` is active.
- The service listens only on `127.0.0.1:3091`.
- Public HTTPS endpoints return valid JSON.
- Candidate count is greater than `0`.
- Only `/healthz`, `/discovery-meta.json`, and `/discovery-feed.json` are
  exposed.
- No internal paths, private notes, loop control data, or write endpoints are
  public.
