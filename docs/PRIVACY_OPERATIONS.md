# Privacy operations

The public `/privacy`, `/terms`, and `/cookies` pages describe the controls in
this repository as of 2026-07-13. They are an engineering data inventory, not a
substitute for legal advice.

## Production review gate

Before publishing these changes, an appropriately qualified privacy/legal
reviewer should confirm:

- the operator's full legal name, Hong Kong address, and request contact;
- the applicable jurisdictions and the Terms' governing-law language;
- processor agreements, processing regions, and cross-border disclosures for
  Google Cloud, Google OAuth/Analytics, and Resend;
- the configured Google Analytics retention period and backup rotation; and
- any statutory retention or request-log requirements.

Copy must be updated if the deployed configuration differs from the repository.

## User controls

- `GET /v1/auth/me/export` returns a `Cache-Control: no-store` JSON export.
  Authentication secrets and raw/keyed network identifiers are excluded.
- `DELETE /v1/auth/me` requires the exact email and the current password when
  the account supports password sign-in. It permanently removes the user and
  database rows covered by `ON DELETE CASCADE`.
- Administrator self-deletion is blocked to prevent accidental operator lockout.
- The deletion audit event remains with `user_id = NULL`; it contains keyed
  identifiers rather than plaintext account/network data.
- Email already delivered through Resend and protected backup copies are outside
  the synchronous deletion transaction and must be handled through the relevant
  operational request process when required.

Never exercise the deletion endpoint against a real account during a smoke test.
Use the isolated API test database and `tests/test_privacy_controls.py`.
