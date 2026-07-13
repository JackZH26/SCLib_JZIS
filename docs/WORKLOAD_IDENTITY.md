# Production workload identity

SCLib production does not accept service-account keys, human Application
Default Credentials, OAuth refresh tokens, or an impersonated credential whose
source is `authorized_user`. VPS2 uses Workload Identity Federation (WIF) with
short-lived OIDC subject tokens and three independently authorized service
accounts.

## External prerequisite

Select an approved OIDC issuer or machine-identity agent that can issue tokens
to this VPS and rotate them before expiry. This is an infrastructure/security
decision outside the repository: issuer URL, JWKS trust, claims, token lifetime,
and revocation must be approved before enabling deployment. Do not emulate an
issuer with a static JWT file.

Configure a production workload identity pool/provider with strict issuer,
audience, attribute mapping, and attribute condition. Give each token a distinct
subject or `sclib_role` claim. Bind only that principal to the matching service
account with `roles/iam.workloadIdentityUser`; never grant the entire pool.

| Workload | Service account | Minimum resource access |
|---|---|---|
| API | `sclib-api@jzis-sclib.iam.gserviceaccount.com` | Vertex/GenAI use and read-only object access actually required by API |
| Ingestion | `sclib-ingestion@jzis-sclib.iam.gserviceaccount.com` | Vertex indexing and read/write access to `sclib-jzis` |
| Backup | `sclib-backup@jzis-sclib.iam.gserviceaccount.com` | object create/get/list/delete only on the dedicated backup bucket |

## Host layout

The identity agent writes tokens atomically and keeps each directory readable
only by root and container UID 1001. External-account JSON files contain no
private key or refresh token and may be read-only.

```text
/etc/sclib/credentials/api-external-account.json
/etc/sclib/credentials/ingestion-external-account.json
/etc/sclib/credentials/backup-external-account.json
/run/sclib-identity/api/subject.jwt
/run/sclib-identity/ingestion/subject.jwt
/run/sclib-identity/backup/subject.jwt
```

Generate each configuration after the provider and service accounts exist:

```bash
gcloud iam workload-identity-pools create-cred-config \
  projects/PROJECT_NUMBER/locations/global/workloadIdentityPools/POOL/providers/PROVIDER \
  --service-account=sclib-api@jzis-sclib.iam.gserviceaccount.com \
  --credential-source-file=/var/run/sclib-identity/api/subject.jwt \
  --credential-source-type=text \
  --output-file=/etc/sclib/credentials/api-external-account.json
```

Repeat with the ingestion and backup service accounts and token paths. Use the
default one-hour impersonated access-token lifetime; do not enable lifetime
extension. The subject JWT should be much shorter lived and continuously
rotated by the selected identity agent.

## Enforcement and verification

Validate all three identities on VPS2 without printing token contents:

```bash
python3 scripts/validate_gcp_credentials.py validate \
  --credential /etc/sclib/credentials/api-external-account.json \
  --expected-service-account sclib-api@jzis-sclib.iam.gserviceaccount.com
python3 scripts/validate_gcp_credentials.py validate \
  --credential /etc/sclib/credentials/ingestion-external-account.json \
  --expected-service-account sclib-ingestion@jzis-sclib.iam.gserviceaccount.com
python3 scripts/validate_gcp_credentials.py validate \
  --credential /etc/sclib/credentials/backup-external-account.json \
  --expected-service-account sclib-backup@jzis-sclib.iam.gserviceaccount.com
```

The validator recursively rejects `authorized_user`, `refresh_token`,
`client_secret`, and `private_key`; requires Google STS, the exact expected
service account, a file-sourced JWT, a dedicated runtime directory, and more
than 60 seconds of token life. Production Compose wraps API and ingestion
entrypoints with this check. Deployment validates all three identities before
container replacement; the backup job validates its identity again on each run.

If interactive troubleshooting is required, use `gcloud auth login
--cred-file=...` only in an isolated administrator environment, never to create
a production ADC on VPS2. Revoke the old human OAuth credential and securely
remove its refresh-token file after the three workload checks and real upstream
smoke tests pass. Credential removal/rotation is a production change and
requires the operator's normal change approval and rollback record.
