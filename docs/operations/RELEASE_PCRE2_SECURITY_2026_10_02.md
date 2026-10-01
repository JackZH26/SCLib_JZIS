# PCRE2 release-image security correction

On 2026-10-01, Release images run [36925494066](https://github.com/JackZH26/SCLib_JZIS/actions/runs/36925494066) built revision `44595268c802386a24e7149d7f4c82ec37ba0283`. Its API and ingestion digest scans each reported one fixable HIGH OS-package vulnerability:

| Field | Actual SARIF finding |
| --- | --- |
| Vulnerability | CVE-2026-103111 |
| Package | `libpcre2-8-0` |
| Installed version | `10.46-1~deb13u2` |
| Fixed version | `10.46-1~deb13u3` |
| API analysis | `1877262250` |
| Ingestion analysis | `1877260729` |

The [Debian CVE record](https://security-tracker.debian.org/tracker/CVE-2026-103111) and [DSA-6530-1](https://security-tracker.debian.org/tracker/DSA-6530-1) identify the patched trixie-security version. This finding concerns a Debian system library, outside the Python dependency locks. It is not a scanner/network error.

The scanned API digest was `sha256:b73975a10d7ba8922e6a4f53d35de566a121c6fe45094faaf17b1f4bfb1e4b5a`; ingestion was `sha256:aacbcf248d717117315ceead5bacae7a160e0324836f9302e7785141b06dc298`. Both build logs identify the base as `python:3.11-slim@sha256:e41613d42d4891e4930f79523f93f81bbc7632584ec65e36ab055f41a800b41e`.

The operator cancelled this release because that revision also contained two confirmed material sample-form interpretation errors. Its terminal conclusion is `cancelled`; ingestion's scan had already failed, and API's scan had also failed before cancellation. [Deploy 36925835913](https://github.com/JackZH26/SCLib_JZIS/actions/runs/36925835913) was `skipped`; it executed no deployment step. These images are not an accepted scientific release.

PR91 revision `9a79d3ab62dcbb4b08b55eaa69b54a22e16d665c` still used byte-identical API/ingestion Dockerfiles and locks and did not include this OS correction. The subsequent correction explicitly includes `libpcre2-8-0` in each existing `apt-get update` / installation step and requires `dpkg --compare-versions` to confirm at least `10.46-1~deb13u3`. A stale package mirror must fail the build. The existing Python base identity and dependency locks are retained; no scanner exception or severity reduction is introduced.

Both recipes pin that same already-scanned multi-architecture Python index. Its official linux/amd64 child manifest is `sha256:174bec68e0451bffabbb08c7d5d21c6b253f772d81d52b9558af97bb3159b761`; registry annotations identify `3.11.16-slim-trixie` and `debian:trixie-slim`. Original registry bytes were captured and checked against their content digests. This prevents a mutable tag from silently changing Debian suites while retaining a trixie-specific minimum-version check. It does not replace installation of the patched PCRE2 package.

Static checks validate the recipe only. Actual availability of the patched package and its installed runtime version must be established by a fresh image build. A new successful Test/Security/release chain must bind the corrected source revision to its scanned image digests and runtime inventories before deployment. The seven genuine R7 native captures retain all 4,123 original source pins; their 635-input capture scope does not include these Dockerfiles. Their application inputs and five resources remain unchanged. Historical captures have not been regenerated or rewritten for this deployment-only dependency correction.

Private investigation evidence is retained in `/tmp/sclib-release-445-20261001/` (release/deploy receipts, full release log, actual API/ingestion SARIF and source comparison), with official-page captures and local correction checks in `/tmp/sclib-release-pcre2-fix-20261002/`. No private credential values are included in this document.
