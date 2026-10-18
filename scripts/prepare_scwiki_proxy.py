"""Generate an inactive, additive SCWiki proxy candidate from an audited snapshot.

No SSH, installation, reload, or production write is performed. External includes
and inherited settings still require expanded-configuration and target validation.
"""
from __future__ import annotations

import argparse
from dataclasses import dataclass
import hashlib
import json
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
HTTP_BEGIN = "# BEGIN SCWIKI HTTP CANDIDATE\n"
HTTP_END = "# END SCWIKI HTTP CANDIDATE\n"
SERVER_BEGIN = "\n    # BEGIN SCWIKI SERVER CANDIDATE\n"
SERVER_END = "    # END SCWIKI SERVER CANDIDATE\n"


@dataclass
class Directive:
    words: list[str]
    start: int
    end: int
    children: list[Directive] | None = None


def directives(source: str) -> list[Directive]:
    """Read directive boundaries without interpreting quoted/commented braces."""
    tokens = []
    index = 0
    while index < len(source):
        char = source[index]
        if char.isspace():
            index += 1
            continue
        if char == "#":
            end = source.find("\n", index)
            index = len(source) if end < 0 else end + 1
            continue
        start = index
        if char in "{};":
            tokens.append((char, start, index + 1, True))
            index += 1
            continue
        word = []
        quote = None
        while index < len(source):
            char = source[index]
            if char == "\\":
                if index + 1 == len(source):
                    raise ValueError("Incomplete escape")
                word.append(source[index:index + 2])
                index += 2
            elif quote:
                index += 1
                if char == quote:
                    quote = None
                else:
                    word.append(char)
            elif char in "\"'":
                quote = char
                index += 1
            elif source[index:index + 2] == "${":
                end = source.find("}", index + 2)
                if end < 0:
                    raise ValueError("Incomplete variable")
                word.append(source[index:end + 1])
                index = end + 1
            elif char.isspace() or char in "{};#":
                break
            else:
                word.append(char)
                index += 1
        if quote:
            raise ValueError("Incomplete quoted string")
        tokens.append(("".join(word), start, index, False))

    def parse(position, nested=False):
        result = []
        while position < len(tokens):
            token, start, end, symbol = tokens[position]
            if symbol and token == "}":
                if not nested:
                    raise ValueError("Unexpected closing brace")
                return result, position + 1, end
            words = []
            while position < len(tokens) and not tokens[position][3]:
                words.append(tokens[position][0])
                position += 1
            if not words or position == len(tokens):
                raise ValueError("Incomplete directive")
            delimiter, _, end, _ = tokens[position]
            position += 1
            if delimiter == "{":
                children, position, end = parse(position, True)
            elif delimiter == ";":
                children = None
            else:
                raise ValueError("Directive missing terminator")
            result.append(Directive(words, start, end, children))
        if nested:
            raise ValueError("Missing closing brace")
        return result, position, len(source)

    return parse(0)[0]


def render(source: str, nginx_dir: Path = ROOT / "nginx") -> tuple[str, dict]:
    if any(value in source for value in ["/api/scwiki", "scwiki_api", "scwiki_rate_limited", "BEGIN SCWIKI"]):
        raise ValueError("Existing SCWiki configuration or marker requires explicit reconciliation")
    blocks = directives(source)
    targets = []
    hosts_expected = {"jzis.org", "www.jzis.org"}
    for block in blocks:
        if block.words != ["server"] or block.children is None:
            continue
        names = [d.words[1:] for d in block.children if d.words[0] == "server_name"]
        hosts = set(word for nameset in names for word in nameset)
        tls = any(d.words[0] == "listen" and "ssl" in d.words[1:] for d in block.children)
        if hosts & hosts_expected and tls:
            if hosts != hosts_expected or len(names) != 1:
                raise ValueError("Unexpected HTTPS website host topology")
            if any(d.words[0] in {"return", "rewrite", "if", "set_real_ip_from", "real_ip_header", "limit_req_dry_run"} for d in block.children):
                raise ValueError("Website-level rewrite or trust settings need separate review")
            targets.append(block)
    if len(targets) != 1:
        raise ValueError("Expected exactly one audited HTTPS website server")
    snippets = {name: (nginx_dir / name).read_bytes() for name in ["scwiki-http.conf", "scwiki-server.conf", "scwiki-proxy-common.conf"]}
    common = snippets["scwiki-proxy-common.conf"].decode().strip()
    server = snippets["scwiki-server.conf"].decode().strip()
    include = "    include /etc/nginx/snippets/scwiki-proxy-common.conf;"
    if server.count(include) != 2:
        raise ValueError("Unexpected common snippet structure")
    server = server.replace(include, "\n".join("    " + line for line in common.splitlines()))
    insertion = SERVER_BEGIN + "\n".join("    " + line for line in server.splitlines()) + "\n" + SERVER_END
    prefix = HTTP_BEGIN + snippets["scwiki-http.conf"].decode().rstrip() + "\n" + HTTP_END
    offset = targets[0].end - 1
    candidate = prefix + source[:offset] + insertion + source[offset:]
    # Removing only the two generated ranges must reproduce every original byte.
    restored = candidate[len(prefix):]
    restored = restored[:offset] + restored[offset + len(insertion):]
    if restored != source:
        raise ValueError("Original configuration preservation failed")
    directives(candidate)
    return candidate, {"inputSha256": hashlib.sha256(source.encode()).hexdigest(), "outputSha256": hashlib.sha256(candidate.encode()).hexdigest(), "originalBytesPreserved": True, "insertionOffset": offset, "sourceHashes": {name: hashlib.sha256(data).hexdigest() for name, data in snippets.items()}, "productionChanged": False, "targetNginxValidated": False, "externalIncludesValidated": False, "limitations": ["Requires expanded configuration review for inherited settings and conflicts in external includes.", "Requires target-version nginx -t, rollback preparation, and specific production approval before installation."]}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--receipt", type=Path, required=True)
    parser.add_argument("--expected-sha256", required=True)
    args = parser.parse_args()
    if len({p.resolve() for p in [args.input, args.output, args.receipt]}) != 3:
        parser.error("Input, candidate, and receipt must be distinct files")
    original = args.input.read_bytes()
    if hashlib.sha256(original).hexdigest() != args.expected_sha256:
        parser.error("Input changed since its audit")
    candidate, receipt = render(original.decode())
    receipt["generatorSha256"] = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
    receipt["inputPath"] = str(args.input.resolve())
    receipt["candidatePath"] = str(args.output.resolve())
    created = []
    try:
        for path, data in [(args.output, candidate), (args.receipt, json.dumps(receipt, indent=2) + "\n")]:
            fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            created.append(path)
            with os.fdopen(fd, "w", newline="") as output:
                output.write(data)
                output.flush()
                os.fsync(output.fileno())
    except BaseException:
        for path in reversed(created):
            path.unlink()
        raise
    print("Inactive candidate generated; original bytes preserved. Target validation pending.")


if __name__ == "__main__":
    main()
