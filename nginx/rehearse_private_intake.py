"""Owned loopback Nginx transport rehearsal using synthetic bytes, never the API.

Requires explicitly prepared Nginx/OpenSSL executables. No downloads, installs,
shared listeners, credentials, application imports or production configuration
writes. The report is exclusively created only after owned-process cleanup.
"""

from __future__ import annotations

import argparse
import hashlib
import http.client
import json
import os
import re
import shutil
import socket
import ssl
import subprocess
import tempfile
import threading
import time
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MIB = 1024 * 1024
PREFIX = "/sclib/v1/ml/"
LIMITS = {
    "pilots/registrations": 22435160,
    "pilots/participation/accept": 22435160,
    "pilots/review-preflight": 44804784,
    "pilots/review-attestations": 44804784,
    "pilots/review-attestations/coverage": 44804784,
    "pilots/review-attestations/evidence": 130 * MIB,
    "use/preflight/reconstruct": 32 * MIB,
    "use/preflight/reconstruct/current": 32 * MIB,
    "use/requests/preview": 32 * MIB,
    "use/requests": 32 * MIB,
    "scientific-program-imports": 24 * MIB,
}
MARKER = b"SCLIB_SYNTHETIC_PRIVATE_CANARY_77"
BLOCK = (MARKER * 2200)[:65536]
ENV = {"PATH": "/usr/bin:/bin", "LANG": "C", "LC_ALL": "C"}


def require(value, message):
    if not value:
        raise ValueError(message)


def sha(value):
    return hashlib.sha256(value).hexdigest()


def source_contract(source, policy):
    """Narrow fail-closed preflight, not a replacement for actual nginx -t."""
    source = "\n".join(line.split("#", 1)[0] for line in source.splitlines())
    policy = "\n".join(line.split("#", 1)[0] for line in policy.splitlines())
    actual = {}
    for path, size in re.findall(
        r"location = (/sclib/v1/ml/[^\s{]+)\s*\{\s*(?:(?:include|proxy_pass) [^;]+;\s*)?"
        r"client_max_body_size ([0-9]+m?);",
        source,
    ):
        require(path not in actual, "Duplicate private upload location")
        actual[path] = int(size.rstrip("m")) * (MIB if size.endswith("m") else 1)
    require(
        actual == {PREFIX + k: v for k, v in LIMITS.items()},
        "Private upload route/size drift",
    )
    for path in actual:
        block = source.split("location = " + path + " {", 1)[1].split("}", 1)[0]
        require(
            "proxy_pass http://127.0.0.1:8000" + path.removeprefix("/sclib") + ";"
            in block,
            "Exact upload route must have its own proxy handler",
        )
    require(
        source.count("include /etc/nginx/snippets/sclib-private-intake.conf;") == 4,
        "Private policy inclusion drift",
    )
    for path in ("pilots/", "use/", "scientific-program-imports/"):
        require(
            f"location ^~ {PREFIX}{path} {{" in source, "Private prefix guard missing"
        )
        require(
            f"proxy_pass http://127.0.0.1:8000/v1/ml/{path};" in source,
            "Private upstream mapping drift",
        )
    require(source.count("client_max_body_size 20m;") == 1, "Generic ceiling drift")
    for directive in (
        "proxy_http_version 1.1;",
        "proxy_request_buffering off;",
        "proxy_buffering off;",
        "proxy_ignore_headers X-Accel-Buffering;",
        "proxy_max_temp_file_size 0;",
        "client_body_in_file_only off;",
        "proxy_cache off;",
        "proxy_store off;",
        "proxy_next_upstream off;",
        "proxy_intercept_errors off;",
        "access_log off;",
        "error_log /dev/null;",
        'add_header Cache-Control "private, no-store" always;',
        "proxy_hide_header Cache-Control;",
        "proxy_read_timeout 120s;",
        "proxy_send_timeout 120s;",
        "limit_req_status 429;",
    ):
        require(directive in policy, "Private transport policy drift")
    require(
        "client_max_body_size" not in policy, "Shared policy must not widen body limits"
    )


def free_port():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
    require(
        port > 1024 and port not in (8000, 3100, 32066), "Unsafe listener allocation"
    )
    return port


def chunks(size):
    while size:
        part = BLOCK[: min(len(BLOCK), size)]
        yield part
        size -= len(part)


class Stub(ThreadingHTTPServer):
    daemon_threads = True

    def __init__(self):
        super().__init__(("127.0.0.1", 0), Handler)
        self.records = []
        self.lock = threading.Lock()
        self.threads = []


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, *_args):
        pass

    def do_GET(self):
        self.do_POST()

    def do_POST(self):
        self.connection.settimeout(5)
        record = {
            "path": self.path,
            "mode": self.headers.get("X-Synthetic-Mode", "echo"),
            "bytes": 0,
            "http": self.request_version,
            "cookie": self.headers.get("Cookie"),
            "origin": self.headers.get("Origin"),
            "participant": self.headers.get("X-SCLib-Participant-Id"),
            "done": False,
        }
        with self.server.lock:
            self.server.records.append(record)
            self.server.threads.append(threading.current_thread())
        digest = hashlib.sha256()
        try:
            if record["mode"] == "deny":
                self.reply(403, b"SYNTHETIC denied before upstream body read")
                return
            chunked = self.headers.get("Transfer-Encoding") == "chunked"
            remaining = int(self.headers.get("Content-Length", "0"))
            while chunked or remaining:
                n = (
                    int(self.rfile.readline(128).strip(), 16)
                    if chunked
                    else min(remaining, 65536)
                )
                require(0 <= n <= 131 * MIB, "Synthetic upstream input bound")
                if chunked and n == 0:
                    require(
                        self.rfile.readline(128) == b"\r\n", "Unexpected chunk trailer"
                    )
                    break
                left = n
                while left:
                    part = self.rfile.read(min(left, 65536))
                    require(bool(part), "Incomplete synthetic body")
                    record["bytes"] += len(part)
                    require(
                        record["bytes"] <= 131 * MIB, "Synthetic upstream body bound"
                    )
                    digest.update(part)
                    left -= len(part)
                if chunked:
                    require(self.rfile.read(2) == b"\r\n", "Invalid chunk terminator")
                else:
                    remaining -= n
            record["sha256"] = digest.hexdigest()
            if record["mode"] == "close":
                return
            if record["mode"] == "response":
                self.send_response(200)
                self.send_header("Content-Length", str(8 * MIB))
                self.send_header("X-Accel-Buffering", "yes")
                self.send_header("Cache-Control", "public, max-age=86400")
                self.end_headers()
                for part in chunks(8 * MIB):
                    self.wfile.write(part)
            else:
                self.reply(200, json.dumps(record).encode())
        except (OSError, ValueError):
            record["interrupted"] = True
        finally:
            record["done"] = True
            self.close_connection = True

    def reply(self, status, raw):
        self.send_response(status)
        self.send_header("Content-Length", str(len(raw)))
        self.send_header("Cache-Control", "public, max-age=86400")
        self.end_headers()
        self.wfile.write(raw)


def connection(port, context):
    return http.client.HTTPSConnection("127.0.0.1", port, context=context, timeout=10)


def headers(conn, path, size, *, chunked=False, mode="echo"):
    conn.putrequest("POST", path, skip_host=True, skip_accept_encoding=True)
    for key, value in {
        "Host": "api.jzis.org",
        "Content-Type": "application/octet-stream",
        "Cookie": "SYNTHETIC_COOKIE_77",
        "Origin": "https://synthetic.invalid",
        "X-SCLib-Participant-Id": "SYNTHETIC_PARTICIPANT_77",
        "X-Synthetic-Mode": mode,
        "Transfer-Encoding" if chunked else "Content-Length": "chunked"
        if chunked
        else str(size),
    }.items():
        conn.putheader(key, value)
    conn.endheaders()


def private_headers(response):
    require(
        response.getheader("Cache-Control") == "private, no-store",
        "Private cache header missing",
    )
    for key, expected in {
        "X-Content-Type-Options": "nosniff",
        "X-Frame-Options": "DENY",
        "Referrer-Policy": "no-referrer",
        "Content-Security-Policy": "default-src 'none'; frame-ancestors 'none'",
        "Strict-Transport-Security": "max-age=63072000; includeSubDomains",
    }.items():
        require(response.getheader(key) == expected, "Private security header missing")


def exchange(
    port, context, path, size, *, chunked=False, expected=200, send=True, mode="echo"
):
    conn = connection(port, context)
    digest = hashlib.sha256()
    try:
        headers(conn, path, size, chunked=chunked, mode=mode)
        if send:
            for part in chunks(size):
                digest.update(part)
                try:
                    conn.send(
                        (f"{len(part):x}\r\n".encode() + part + b"\r\n")
                        if chunked
                        else part
                    )
                except (BrokenPipeError, ConnectionResetError):
                    require(expected != 200, "Unexpected transport interruption")
                    break
            if chunked:
                try:
                    conn.send(b"0\r\n\r\n")
                except (BrokenPipeError, ConnectionResetError):
                    require(expected != 200, "Unexpected chunk interruption")
        response = conn.getresponse()
        require(
            response.status == expected,
            f"Transport status mismatch: {response.status}, expected {expected}",
        )
        private_headers(response)
        raw = response.read(65537)
        require(len(raw) <= 65536, "Unexpected synthetic response size")
        if expected == 200:
            value = json.loads(raw)
            require(
                value["bytes"] == size and value["sha256"] == digest.hexdigest(),
                "Upstream bytes changed",
            )
            require(
                value["path"] == path.removeprefix("/sclib"), "Upstream path changed"
            )
            require(
                value["http"] == "HTTP/1.1"
                and value["cookie"] == "SYNTHETIC_COOKIE_77"
                and value["origin"] == "https://synthetic.invalid"
                and value["participant"] == "SYNTHETIC_PARTICIPANT_77",
                "Private headers changed",
            )
        return {"status": response.status, "bytes": size, "chunked": chunked}
    finally:
        conn.close()


def wait_for(check, seconds=3):
    until = time.monotonic() + seconds
    while time.monotonic() < until:
        if check():
            return True
        time.sleep(0.02)
    return False


def body_files(root, pid=None):
    observed = [
        p
        for name in ("client_temp", "proxy_temp")
        for p in (root / name).rglob("*")
        if p.is_file()
    ]
    if pid is None:
        return observed
    # Nginx may unlink an active temporary file immediately. Directory polling
    # alone is therefore insufficient. Inspect only this owned child process.
    fd_root = Path(f"/proc/{pid}/fd")
    if fd_root.is_dir():
        names = []
        for fd in fd_root.iterdir():
            try:
                names.append(os.readlink(fd))
            except FileNotFoundError:
                pass  # The descriptor closed during this observation.
    else:
        lsof = shutil.which("lsof", path="/usr/sbin:/usr/bin:/sbin:/bin")
        require(lsof is not None, "Owned open-file inspection is unavailable")
        result = subprocess.run(
            [lsof, "-a", "-p", str(pid), "-Fn"],
            env=ENV,
            capture_output=True,
            timeout=5,
            check=False,
        )
        require(result.returncode == 0, "Owned open-file inspection failed")
        names = [
            line[1:]
            for line in result.stdout.decode().splitlines()
            if line.startswith("n")
        ]
    prefixes = tuple(
        str(root / directory) + "/" for directory in ("client_temp", "proxy_temp")
    )
    return observed + [name for name in names if name.startswith(prefixes)]


def materialize(source, policy, root, port, redirect_port, upstream):
    require(
        all(
            type(p) is int and 1024 < p < 65536 and p not in (8000, 3100, 32066)
            for p in (port, redirect_port, upstream)
        )
        and len({port, redirect_port, upstream}) == 3,
        "Unsafe rehearsal target",
    )
    replacements = {
        "http://127.0.0.1:8000": f"http://127.0.0.1:{upstream}",
        "listen 443 ssl;": f"listen 127.0.0.1:{port} ssl;",
        "listen 80;": f"listen 127.0.0.1:{redirect_port};",
        "ssl_certificate /etc/letsencrypt/live/api.jzis.org/fullchain.pem;": f'ssl_certificate "{root}/cert.pem";',
        "ssl_certificate_key /etc/letsencrypt/live/api.jzis.org/privkey.pem;": f'ssl_certificate_key "{root}/key.pem";',
        "include /etc/letsencrypt/options-ssl-nginx.conf;": "ssl_protocols TLSv1.2 TLSv1.3;",
        "ssl_dhparam /etc/letsencrypt/ssl-dhparams.pem;": "# External deployment DH file is not part of this rehearsal.",
        "include /etc/nginx/snippets/sclib-private-intake.conf;": f'include "{root}/private-intake.conf";',
    }
    for old, new in replacements.items():
        require(old in source, "Unknown production configuration shape")
        source = source.replace(old, new)
    # No production certificate, include, bind address or upstream survives.
    active = "\n".join(line.split("#", 1)[0] for line in source.splitlines())
    require(
        "/etc/" not in active and "127.0.0.1:8000" not in active,
        "Unsafe materialized config",
    )
    targets = re.findall(r"\bproxy_pass\s+([^;]+);", active)
    require(
        targets and all(t.startswith(f"http://127.0.0.1:{upstream}/") for t in targets),
        "Unowned upstream in materialized config",
    )
    listeners = re.findall(r"\blisten\s+([^;]+);", active)
    require(
        sorted(listeners)
        == sorted([f"127.0.0.1:{port} ssl", f"127.0.0.1:{redirect_port}"]),
        "Unowned listener in materialized config",
    )
    includes = re.findall(r"\binclude\s+([^;]+);", active)
    require(
        includes == [f'"{root}/private-intake.conf"'] * 4
        and not re.search(r"(?m)^\s*include\s", policy),
        "Unowned include in materialized config",
    )
    (root / "private-intake.conf").write_text(policy)
    for directory in ("client_temp", "proxy_temp"):
        (root / directory).mkdir(exist_ok=True)
    config = (
        f'daemon off; master_process off; pid "{root}/nginx.pid";\n'
        f'error_log "{root}/error.log" warn;\nevents {{ worker_connections 128; }}\nhttp {{\n'
        f'access_log "{root}/access.log";\nclient_body_temp_path "{root}/client_temp";\n'
        f'proxy_temp_path "{root}/proxy_temp";\n{source}\n}}\n'
    )
    (root / "nginx.conf").write_text(config)
    return sha(config.encode())


@contextmanager
def gateway(nginx, source, policy, root, upstream, context):
    port, redirect_port = free_port(), free_port()
    require(port != redirect_port, "Listener allocation collision")
    pin = materialize(source, policy, root, port, redirect_port, upstream)
    args = [
        nginx,
        "-p",
        str(root) + "/",
        "-e",
        str(root / "error.log"),
        "-c",
        str(root / "nginx.conf"),
    ]
    checked = subprocess.run(
        [*args, "-t"], env=ENV, capture_output=True, timeout=10, check=False
    )
    require(
        checked.returncode == 0,
        "Isolated nginx -t failed: " + checked.stderr.decode()[-3000:],
    )
    with (root / "process.log").open("ab") as log:
        process = subprocess.Popen(args, env=ENV, stdout=log, stderr=log)
        try:

            def ready():
                require(process.poll() is None, "Owned Nginx exited before readiness")
                try:
                    with socket.create_connection(("127.0.0.1", port), timeout=0.2):
                        return True
                except OSError:
                    return False

            require(wait_for(ready, 5), "Owned Nginx did not become ready")
            yield port, pin, process.pid
            require(process.poll() is None, "Owned Nginx exited during rehearsal")
        finally:
            if process.poll() is None:
                process.terminate()
                try:
                    process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait(timeout=5)
            require(process.poll() is not None, "Owned Nginx cleanup unverified")


def streaming_probe(port, context, path, root, upstream, pid, *, buffered=False):
    """Pause a real 2 MiB request halfway to observe transient body files."""
    conn = connection(port, context)
    count = len(upstream.records)
    try:
        headers(conn, path, 2 * MIB)
        for part in chunks(MIB):
            conn.send(part)
        if buffered:
            require(
                wait_for(lambda: bool(body_files(root, pid))),
                "Negative control did not expose body spooling",
            )
            require(
                len(upstream.records) == count,
                "Buffered control reached upstream before EOF",
            )
        else:
            require(
                wait_for(
                    lambda: (
                        len(upstream.records) > count
                        and upstream.records[-1]["bytes"] > 0
                    )
                ),
                "Private bytes did not stream before EOF",
            )
            require(
                not body_files(root, pid), "Private body spooled during active upload"
            )
        for part in chunks(MIB):
            conn.send(part)
        response = conn.getresponse()
        require(response.status == 200, "Streaming probe failed")
        response.read()
    finally:
        conn.close()


def response_probe(port, context, path, root, upstream, pid):
    before = len(upstream.records)
    for _ in range(2):
        conn = connection(port, context)
        try:
            headers(conn, path, 0, mode="response")
            response = conn.getresponse()
            require(response.status == 200, "Large private response failed")
            private_headers(response)
            time.sleep(0.05)  # Keep the real response active for file/FD inspection.
            require(not body_files(root, pid), "Private response used a temporary file")
            digest, size = hashlib.sha256(), 0
            while part := response.read(65536):
                digest.update(part)
                size += len(part)
                require(size <= 8 * MIB, "Synthetic response exceeded its bound")
            expected = hashlib.sha256()
            for part in chunks(8 * MIB):
                expected.update(part)
            require(
                size == 8 * MIB and digest.hexdigest() == expected.hexdigest(),
                "Private response changed",
            )
        finally:
            conn.close()
    require(
        len(upstream.records) == before + 2, "Private response was cached or replayed"
    )


def scope_and_rate_probe(port, context, upstream):
    # Neighbor paths and the public API keep the ordinary 20 MiB ceiling.
    for path, private in (
        ("/sclib/v1/search", False),
        (PREFIX + "pilots/review-preflight/", True),
        (PREFIX + "use/requests/outcome", True),
        (PREFIX + "scientific-program-imports/outcome", True),
    ):
        before, conn = len(upstream.records), connection(port, context)
        try:
            headers(conn, path, 20 * MIB + 1)
            response = conn.getresponse()
            require(response.status == 413, "Neighbor route ceiling was widened")
            if private:
                private_headers(response)
            response.read()
            require(
                len(upstream.records) == before, "Oversized neighbor reached upstream"
            )
        finally:
            conn.close()
    for path in ("/sclib/metrics", "/sclib/v1/stats/refresh"):
        before, conn = len(upstream.records), connection(port, context)
        try:
            headers(conn, path, 0)
            response = conn.getresponse()
            require(response.status == 404, "Protected operator route became public")
            response.read()
            require(len(upstream.records) == before, "Protected route reached upstream")
        finally:
            conn.close()
    # Real production per-IP limiter, without spoofed XFF or modified limits.
    statuses = []
    for _ in range(10):
        conn = connection(port, context)
        try:
            headers(conn, PREFIX + "pilots/review-preflight", 0)
            response = conn.getresponse()
            private_headers(response)
            statuses.append(response.status)
            response.read()
        finally:
            conn.close()
    require(
        200 in statuses and 429 in statuses and set(statuses) <= {200, 429},
        "Private rate limiter was not exercised",
    )
    return statuses


def rehearse(nginx, openssl):
    source = (ROOT / "nginx/sclib.conf").read_text()
    policy = (ROOT / "nginx/private-intake.conf").read_text()
    source_contract(source, policy)
    version = subprocess.run(
        [nginx, "-V"], env=ENV, capture_output=True, timeout=10, check=False
    )
    require(version.returncode == 0, "Explicit Nginx binary unavailable")
    report = {
        "version": "sclib-private-ingress-rehearsal/1.0.0",
        "synthetic_only": True,
        "application_or_database_executed": False,
        "deployment_verified": False,
        "source_pins": {
            "nginx/sclib.conf": sha(source.encode()),
            "nginx/private-intake.conf": sha(policy.encode()),
            "nginx/rehearse_private_intake.py": sha(Path(__file__).read_bytes()),
        },
        "nginx_binary_sha256": sha(Path(nginx).read_bytes()),
        "nginx_version": version.stderr.decode(),
        "routes": [],
        "owned_cleanup_verified": False,
    }
    with tempfile.TemporaryDirectory(prefix="sclib-private-ingress-") as temp:
        root = Path(temp).resolve()
        generated = subprocess.run(
            [
                openssl,
                "req",
                "-x509",
                "-newkey",
                "rsa:2048",
                "-nodes",
                "-days",
                "1",
                "-subj",
                "/CN=Synthetic loopback rehearsal",
                "-addext",
                "subjectAltName=IP:127.0.0.1",
                "-keyout",
                str(root / "key.pem"),
                "-out",
                str(root / "cert.pem"),
            ],
            env=ENV,
            capture_output=True,
            timeout=30,
            check=False,
        )
        require(
            generated.returncode == 0, "Synthetic TLS certificate generation failed"
        )
        context = ssl.create_default_context(cafile=str(root / "cert.pem"))
        upstream = Stub()
        server_thread = threading.Thread(target=upstream.serve_forever, daemon=True)
        server_thread.start()
        try:
            for route, limit in LIMITS.items():
                path = PREFIX + route
                with gateway(
                    nginx, source, policy, root, upstream.server_port, context
                ) as (port, pin, _pid):
                    samples = [
                        exchange(port, context, path, limit),
                        exchange(port, context, path, limit, chunked=True),
                    ]
                    count = len(upstream.records)
                    samples.append(
                        exchange(
                            port, context, path, limit + 1, expected=413, send=False
                        )
                    )
                    require(
                        len(upstream.records) == count,
                        "Over-limit declared body reached upstream",
                    )
                    samples.append(
                        exchange(
                            port,
                            context,
                            path + "?SCLIB_SYNTHETIC_PRIVATE_QUERY_77",
                            MIB,
                            expected=403,
                            send=False,
                            mode="deny",
                        )
                    )
                    require(
                        upstream.records[-1]["bytes"] == 0,
                        "Early denial consumed upstream body",
                    )
                    report["routes"].append(
                        {
                            "path": path,
                            "limit_bytes": limit,
                            "rendered_config_sha256": pin,
                            "samples": samples,
                        }
                    )
                # New owned instance for the paused upload: do not relax or
                # consume the production evidence route's burst=2 policy.
                with gateway(
                    nginx, source, policy, root, upstream.server_port, context
                ) as (port, _pin, pid):
                    streaming_probe(port, context, path, root, upstream, pid)
                    report["routes"][-1]["chunked_over_limit"] = exchange(
                        port, context, path, limit + 1, chunked=True, expected=413
                    )
                    require(
                        not body_files(root, pid),
                        "Unexpected private temporary body file",
                    )
                    report["routes"][-1]["streamed_before_eof"] = True
                print(f"Verified synthetic transport: {path}", flush=True)
            with gateway(
                nginx, source, policy, root, upstream.server_port, context
            ) as (port, _pin, pid):
                response_probe(
                    port,
                    context,
                    PREFIX + "pilots/review-preflight",
                    root,
                    upstream,
                    pid,
                )
                report["private_response_bytes_verified"] = 2 * 8 * MIB
            with gateway(
                nginx, source, policy, root, upstream.server_port, context
            ) as (port, _pin, _pid):
                report["rate_limit_statuses"] = scope_and_rate_probe(
                    port, context, upstream
                )
                report["neighbor_limits_and_hidden_routes_verified"] = True
            # A deliberately buffered synthetic control proves that the observer
            # can detect temporary files while a request is still in flight.
            with gateway(
                nginx,
                source,
                policy.replace(
                    "proxy_request_buffering off;", "proxy_request_buffering on;"
                ),
                root,
                upstream.server_port,
                context,
            ) as (port, _pin, pid):
                streaming_probe(
                    port,
                    context,
                    PREFIX + "pilots/review-preflight",
                    root,
                    upstream,
                    pid,
                    buffered=True,
                )
            report["buffering_negative_control_detected"] = True
        finally:
            upstream.shutdown()
            upstream.server_close()
            server_thread.join(timeout=5)
            for thread in upstream.threads:
                thread.join(timeout=6)
            require(
                not server_thread.is_alive()
                and all(not t.is_alive() for t in upstream.threads),
                "Owned upstream cleanup unverified",
            )
        require(not body_files(root), "Temporary body survived completed rehearsal")
        # Control logs can legitimately mention a temp filename, but must not
        # contain synthetic private body, query, cookie or participant markers.
        for name in ("access.log", "error.log", "process.log"):
            data = (root / name).read_bytes() if (root / name).exists() else b""
            require(
                not any(
                    marker in data
                    for marker in (
                        MARKER,
                        b"SCLIB_SYNTHETIC_PRIVATE_QUERY_77",
                        b"SYNTHETIC_COOKIE_77",
                        b"SYNTHETIC_PARTICIPANT_77",
                    )
                ),
                "Private marker reached proxy logs",
            )
        report["private_markers_absent_from_owned_logs"] = True
    require(
        (ROOT / "nginx/sclib.conf").read_text() == source
        and (ROOT / "nginx/private-intake.conf").read_text() == policy,
        "Source changed during rehearsal",
    )
    require(
        sha(Path(__file__).read_bytes())
        == report["source_pins"]["nginx/rehearse_private_intake.py"],
        "Rehearsal implementation changed while running",
    )
    report["owned_cleanup_verified"] = True
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--nginx", required=True, type=Path)
    parser.add_argument("--openssl", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    require(
        not args.output.exists() and not args.output.is_symlink(),
        "Output must be a new private file",
    )
    for binary in (args.nginx, args.openssl):
        require(
            binary.is_absolute() and binary.is_file() and os.access(binary, os.X_OK),
            "Explicit executable required",
        )
    result = rehearse(str(args.nginx.resolve()), str(args.openssl.resolve()))
    fd = os.open(args.output, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "w") as handle:
        json.dump(result, handle, indent=2)
        handle.write("\n")
    print(
        f"Synthetic private ingress verified: {len(result['routes'])} routes; owned processes stopped."
    )


if __name__ == "__main__":
    main()
