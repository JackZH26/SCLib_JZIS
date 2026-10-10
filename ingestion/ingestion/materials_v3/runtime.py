"""Resource admission and a host-wide heavy-job lock for native MLX."""

from __future__ import annotations

import fcntl
import json
import os
import platform
import re
import resource
import subprocess
import sys
from contextlib import contextmanager
from pathlib import Path


def runtime_lock():
    """Record the environment actually installed; writing this is not a load receipt."""
    import importlib.metadata
    from .pipeline import implementation_hash

    packages = {
        d.metadata["Name"].lower().replace("_", "-"): d.version
        for d in importlib.metadata.distributions()
        if d.metadata["Name"]
    }
    if packages.get("mlx-lm") != "0.32.0" or packages.get("mlx") != "0.32.3":
        raise ValueError("mlx_runtime_versions_not_pinned")
    info = hardware()
    if not info.get("supported"):
        raise ValueError("runtime_lock_requires_native_mlx_host")
    return {
        "version": "sclib-ner-runtime/1",
        "python": sys.version,
        "os_release": platform.release(),
        "packages": dict(sorted(packages.items())),
        "implementation_sha256": implementation_hash(),
        "hardware": {
            k: info[k] for k in ("architecture", "platform", "cpu_brand", "total_memory_bytes")
        },
        "model_loaded": False,
        "scientific_acceptance": False,
    }


def hardware():
    if sys.platform != "darwin" or platform.machine() != "arm64":
        return {
            "platform": platform.system(),
            "architecture": platform.machine(),
            "supported": False,
        }

    def read(*args):
        return subprocess.check_output(args, text=True, timeout=10).strip()

    total = int(read("/usr/sbin/sysctl", "-n", "hw.memsize"))
    vm = read("/usr/bin/vm_stat")
    page = int(re.search(r"page size of (\d+) bytes", vm).group(1))
    values = {key: int(number) for key, number in re.findall(r"([^\n:]+):\s+(\d+)\.", vm)}
    available = page * sum(
        values.get(k, 0) for k in ("Pages free", "Pages inactive", "Pages speculative")
    )
    return {
        "platform": "macos_arm64",
        "architecture": "arm64",
        "supported": True,
        "total_memory_bytes": total,
        "reclaimable_memory_estimate_bytes": available,
        "estimate_basis": "vm_stat_free_inactive_speculative",
        "swap_usage_raw": read("/usr/sbin/sysctl", "-n", "vm.swapusage"),
        "cpu_brand": read("/usr/sbin/sysctl", "-n", "machdep.cpu.brand_string"),
    }


def admission(info, *, budget_gib=32, headroom_gib=12, expected_peak_gib=24):
    if not info.get("supported"):
        raise ValueError("mlx_requires_native_macos_arm64")
    if info["total_memory_bytes"] < (budget_gib + headroom_gib) * 1024**3:
        raise ValueError("insufficient_total_memory")
    if not 0 < expected_peak_gib <= budget_gib:
        raise ValueError("invalid_memory_admission_profile")
    # Initial 24 GiB is a smoke-test admission estimate, not a measured profile.
    # The 32 GiB cap and 12 GiB live headroom guard remain independent limits.
    if info["reclaimable_memory_estimate_bytes"] < (expected_peak_gib + headroom_gib) * 1024**3:
        raise ValueError("insufficient_current_memory_headroom")


@contextmanager
def heavy_lock(path: Path):
    """Share this exact lock with the QE supervisor; no independent heavy jobs."""
    path.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(path, os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW, 0o600)
    try:
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise ValueError("another_heavy_job_is_running") from None
        yield
    finally:
        os.close(fd)


def model_pin():
    return json.loads(Path(__file__).with_name("model-pin.json").read_bytes())


def verify_model(model_path: Path, model_manifest: Path, revision: str):
    import hashlib

    manifest = json.loads(model_manifest.read_bytes())
    pin = model_pin()
    if manifest.get("revision") != revision or revision != pin["revision"]:
        raise ValueError("model_manifest_revision_mismatch")
    if manifest.get("model_id") != pin["model_id"]:
        raise ValueError("model_manifest_identity_mismatch")
    entries = manifest.get("files", [])
    if not isinstance(entries, list) or any(
        not isinstance(e, dict) or not isinstance(e.get("path"), str) for e in entries
    ):
        raise ValueError("model_manifest_invalid")
    names = [e["path"] for e in entries]
    expected = {e["path"]: e for e in pin["files"]}
    if len(names) != len(set(names)) or set(names) != set(expected):
        raise ValueError("model_manifest_incomplete_or_duplicated")
    for entry in entries:
        known = expected[entry["path"]]
        if entry.get("sha256") != known["sha256"] or entry.get("bytes") != known["bytes"]:
            raise ValueError("model_manifest_differs_from_pinned_upstream")
        path = (model_path / entry["path"]).resolve()
        if not path.is_relative_to(model_path.resolve()) or not path.is_file():
            raise ValueError("model_file_outside_snapshot_or_missing")
        if path.stat().st_size != known["bytes"]:
            raise ValueError("model_file_size_mismatch")
        sha = hashlib.sha256()
        with path.open("rb") as handle:
            for piece in iter(lambda: handle.read(1024 * 1024), b""):
                sha.update(piece)
        if sha.hexdigest() != entry["sha256"]:
            raise ValueError("model_file_hash_mismatch")
    index = json.loads((model_path / "model.safetensors.index.json").read_bytes())
    shards = {name for name in names if name.endswith(".safetensors")}
    if set(index["weight_map"].values()) != shards:
        raise ValueError("model_manifest_weight_index_mismatch")


def process_memory_bytes():
    peak = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    return int(peak if sys.platform == "darwin" else peak * 1024)


def memory_observation(metal_peak_bytes):
    rss = process_memory_bytes()
    # Unified-memory allocations can appear in both counters. Report both and
    # use their maximum alongside host headroom, never claim a disjoint sum.
    return {
        "process_peak_rss_bytes": rss,
        "metal_peak_bytes": metal_peak_bytes,
        "observed_peak_bytes": max(rss, metal_peak_bytes),
        "accounting": "max_rss_metal_with_host_headroom",
    }
