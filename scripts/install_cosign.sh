#!/usr/bin/env bash
# Install the exact Cosign verifier used by the release workflow.
set -euo pipefail

readonly VERSION="v3.0.6"
readonly INSTALL_DIR="${COSIGN_INSTALL_DIR:-/usr/local/bin}"

case "$(uname -m)" in
  x86_64|amd64)
    readonly ASSET="cosign-linux-amd64"
    readonly EXPECTED_SHA256="c956e5dfcac53d52bcf058360d579472f0c1d2d9b69f55209e256fe7783f4c74"
    ;;
  aarch64|arm64)
    readonly ASSET="cosign-linux-arm64"
    readonly EXPECTED_SHA256="bedac92e8c3729864e13d4a17048007cfafa79d5deca993a43a90ffe018ef2b8"
    ;;
  *)
    echo "unsupported architecture for Cosign: $(uname -m)" >&2
    exit 1
    ;;
esac

if [[ -x "$INSTALL_DIR/cosign" ]] &&
  "$INSTALL_DIR/cosign" version 2>/dev/null | grep -Fq "GitVersion:    $VERSION"; then
  exit 0
fi

tmp="$(mktemp)"
trap 'rm -f "$tmp"' EXIT
curl --retry 3 --fail --silent --show-error --location \
  "https://github.com/sigstore/cosign/releases/download/$VERSION/$ASSET" \
  --output "$tmp"
actual_sha256="$(sha256sum "$tmp" | awk '{print $1}')"
if [[ "$actual_sha256" != "$EXPECTED_SHA256" ]]; then
  echo "Cosign checksum mismatch for $ASSET" >&2
  exit 1
fi
install -d -m 0755 "$INSTALL_DIR"
install -m 0755 "$tmp" "$INSTALL_DIR/cosign"
"$INSTALL_DIR/cosign" version
