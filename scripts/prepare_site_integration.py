"""Render a reviewed Nginx candidate. Never installs, reloads, or edits production.

Require the SHA-256 of the audited input to guard against concurrent edits.
API servers and other top-level blocks remain byte-for-byte unchanged.
"""
from __future__ import annotations

import argparse
import hashlib
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def server_blocks(source: str) -> list[tuple[int, int, str]]:
    """Find top-level server blocks, ignoring quoted and commented braces."""
    depth = 0
    quote = None
    escaped = False
    comment = False
    start = None
    blocks = []
    for index, char in enumerate(source):
        if comment:
            if char == "\n":
                comment = False
            continue
        if escaped:
            escaped = False
            continue
        if char == "\\":
            escaped = True
            continue
        if quote:
            if char == quote:
                quote = None
            continue
        if char in "\"'":
            quote = char
        elif char == "#":
            comment = True
        elif char == "{":
            if depth == 0:
                match = re.search(r"(?m)^\s*server\s*$", source[:index])
                start = match.start() if match else None
            depth += 1
        elif char == "}":
            depth -= 1
            if depth < 0:
                raise ValueError("Unbalanced Nginx configuration")
            if depth == 0 and start is not None:
                blocks.append((start, index + 1, source[start:index + 1]))
                start = None
    if depth or quote:
        raise ValueError("Incomplete Nginx configuration")
    return blocks


def tls_directives(block: str) -> str:
    lines = re.findall(r"(?m)^\s*(?:listen\s+[^;]*\bssl\b[^;]*|ssl_certificate(?:_key)?\s+[^;]+|ssl_dhparam\s+[^;]+|include\s+/etc/letsencrypt/[^;]+);[^\n]*", block)
    text = "\n    ".join(line.strip() for line in lines)
    if not all(re.search(r"\b" + name + r"\s+", text) for name in ["listen", "ssl_certificate", "ssl_certificate_key"]):
        raise ValueError("Missing audited TLS directives")
    return text


def render(source: str) -> str:
    replacements = []
    found = set()
    for start, end, block in server_blocks(source):
        match = re.search(r"\bserver_name\s+([^;]+);", block)
        hosts = set(match.group(1).split()) if match else set()
        if not re.search(r"\blisten\s+[^;]*\bssl\b", block):
            continue
        if hosts == {"jzis.org", "www.jzis.org"}:
            role = "main"
            # The actual audited host also has a private interview location in
            # a separate snippet. Keep that unrelated site and all non-TLS includes.
            includes = re.findall(r"(?m)^\s*(include\s+(?!/etc/letsencrypt/)[^;]+;)", block)
            template = (ROOT / "nginx/main-site.conf").read_text()
            replacement = template.replace("@@PRESERVED_INCLUDES@@", "\n    ".join(includes))
        elif hosts == {"asrp.jzis.org"}:
            role = "retired"
            replacement = (ROOT / "nginx/retired-site.conf").read_text()
        else:
            continue
        if role in found:
            raise ValueError("Ambiguous duplicate website server")
        found.add(role)
        replacements.append((start, end, "\n" + replacement.replace("@@TLS@@", tls_directives(block)).strip() + "\n"))
    if found != {"main", "retired"}:
        raise ValueError("Expected both audited HTTPS website servers; review the topology first")
    for start, end, replacement in reversed(replacements):
        source = source[:start] + replacement + source[end:]
    return source


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--expected-sha256", required=True)
    args = parser.parse_args()
    original = args.input.read_bytes()
    if hashlib.sha256(original).hexdigest() != args.expected_sha256:
        parser.error("The input changed since the audit; inspect it before generating a candidate")
    if args.output.resolve() == args.input.resolve():
        parser.error("Candidate must be a separate file")
    candidate = render(original.decode())
    with args.output.open("x") as output:
        output.write(candidate)
    print("Candidate generated; review its diff and run nginx -t before any cutover.")


if __name__ == "__main__":
    main()
