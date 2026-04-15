#!/usr/bin/env python3
"""Wrap the host ADC into an impersonated_service_account credential.

Context: the SCLib API container should authenticate to GCP as the
dedicated `sclib-api@jzis-sclib.iam.gserviceaccount.com` service
account, not as the human operator who ran `gcloud auth
application-default login`. Org policy forbids JSON keys, so we use
impersonation: the API's source credential stays a user OAuth refresh
token, but every call first exchanges that for a short-lived SA token
via the IAM Credentials API.

``gcloud auth application-default login --impersonate-service-account``
can produce this form directly, but it requires a browser OAuth flow.
When the host already holds a fresh `authorized_user` ADC (because an
operator just did a plain login, or the token was recently refreshed),
this script rewrites the existing file in place so no browser dance is
needed. Useful on a headless VPS.

The rewrite is a pure JSON transformation — no network calls — so it's
safe to run repeatedly. It refuses to touch a file that is not an
`authorized_user` credential.

Side effects:
  * Creates a timestamped backup of the original file next to it
  * Relaxes the mode to 0644 so uid 1001 inside the api container
    can read the mounted credential. The file is under /root/.config
    which is 0700, so the host-side blast radius is unchanged.

Usage (on VPS2, as root):
    python3 /opt/SCLib_JZIS/scripts/wrap_adc_impersonated.py
    docker restart sclib-api
"""
from __future__ import annotations

import json
import os
import shutil
import sys
import time

ADC_PATH = "/root/.config/gcloud/application_default_credentials.json"
SA = "sclib-api@jzis-sclib.iam.gserviceaccount.com"


def main() -> int:
    if not os.path.exists(ADC_PATH):
        print(f"error: {ADC_PATH} does not exist. "
              f"Run `gcloud auth application-default login` first.",
              file=sys.stderr)
        return 1

    with open(ADC_PATH) as f:
        cred = json.load(f)

    cred_type = cred.get("type")
    if cred_type == "impersonated_service_account":
        target = cred.get("service_account_impersonation_url", "")
        if SA in target:
            print(f"already wrapped: impersonating {SA}. Nothing to do.")
            return 0
        print(f"error: already impersonating a different SA: {target}",
              file=sys.stderr)
        return 2

    if cred_type != "authorized_user":
        print(f"error: unexpected ADC type {cred_type!r}, "
              f"expected authorized_user", file=sys.stderr)
        return 3

    backup = f"{ADC_PATH}.user-{int(time.time())}.bak"
    shutil.copy2(ADC_PATH, backup)
    print(f"backup -> {backup}")

    wrapped = {
        "type": "impersonated_service_account",
        "service_account_impersonation_url": (
            f"https://iamcredentials.googleapis.com"
            f"/v1/projects/-/serviceAccounts/{SA}:generateAccessToken"
        ),
        "delegates": [],
        "source_credentials": {
            "type": "authorized_user",
            "client_id":     cred["client_id"],
            "client_secret": cred["client_secret"],
            "refresh_token": cred["refresh_token"],
        },
        "quota_project_id": cred.get("quota_project_id", "jzis-sclib"),
    }

    with open(ADC_PATH, "w") as f:
        json.dump(wrapped, f, indent=2)
    os.chmod(ADC_PATH, 0o644)

    print(f"rewrote {ADC_PATH} as impersonated_service_account (mode 0644)")
    print(f"target SA: {SA}")
    print()
    print("Next:  docker restart sclib-api")
    return 0


if __name__ == "__main__":
    sys.exit(main())
