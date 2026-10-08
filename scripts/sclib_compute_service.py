#!/usr/bin/env python3
"""Start an isolated loopback staging server. Never accepts a bind-host flag."""
import argparse
import os
from pathlib import Path

import uvicorn
from sclib_compute.api import ServiceConfig, configured_store, create_app


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--data-dir", type=Path, required=True)
    parser.add_argument("--port", type=int, default=8092)
    args = parser.parse_args()
    if not 1024 <= args.port <= 65535:
        parser.error("staging port must be unprivileged")
    if args.config.is_symlink() or args.config.stat().st_mode & 0o007:
        parser.error("configuration must be a private regular file")
    os.umask(0o077)
    config = ServiceConfig.model_validate_json(args.config.read_bytes())
    app = create_app(configured_store(args.data_dir, config), config)
    uvicorn.run(app, host="127.0.0.1", port=args.port, proxy_headers=False, access_log=False, workers=1, log_level="warning")


if __name__ == "__main__":
    main()
