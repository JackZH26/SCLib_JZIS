"""Fixed initialization-only guardian entrypoint; never selected by queued data."""

from __future__ import annotations

import argparse
import math
import os
import select
import shutil
import time
from pathlib import Path

from .contracts import JobSpec, canonical
from .native_contract import available_memory_bytes, read_regular
from .native_supervisor import supervise
from .pbesol_execution import descriptor_data, load_profile, read_staged, require, sha
from .pbesol_result_custody import strict_json


def require_live_lease(work):
    lease = strict_json(read_regular(work.parent / "lease.json", 4096), 4096)
    require(
        type(lease) is dict and set(lease) == {"lease_until_unix"},
        "guardian lease shape invalid",
    )
    until = lease["lease_until_unix"]
    require(
        type(until) in {int, float} and math.isfinite(until) and until > time.time(),
        "PBEsol lease expired before launch",
    )


def validate_launch_request(request, profile):
    require(
        type(request) is dict
        and set(request)
        == {
            "runtime",
            "spec",
            "descriptor",
            "work",
            "remaining_wall_seconds",
            "local_profile",
            "launch_deadline_unix",
        },
        "closed PBEsol guardian request required",
    )
    spec = JobSpec.model_validate(request["spec"])
    require(
        canonical(request["spec"]) == canonical(spec.model_dump(mode="json")),
        "complete PBEsol JobSpec required",
    )
    require(
        request["runtime"] == profile.runtime.model_dump(mode="json")
        and request["local_profile"] == profile.identity(),
        "guardian local runtime/profile mismatch",
    )
    work = Path(request["work"])
    require(
        work.is_absolute()
        and str(work) == request["work"]
        and ".." not in work.parts
        and work.name == "work",
        "canonical PBEsol work path required",
    )
    projection = read_staged(spec, work, profile)
    expected = descriptor_data(projection, profile)
    require(
        canonical(request["descriptor"]) == canonical(expected),
        "guardian descriptor differs from staged input",
    )
    saved = strict_json(read_regular(work.parent / "descriptor.json", 8192), 8192)
    require(
        canonical(saved) == canonical(expected), "guardian saved descriptor differs"
    )
    # Evaluate time after the bounded file and executable checks, just before launch.
    now = time.time()
    remaining, deadline = (
        request["remaining_wall_seconds"],
        request["launch_deadline_unix"],
    )
    require(
        type(remaining) in {int, float}
        and math.isfinite(remaining)
        and 0 < remaining <= spec.resources.wall_seconds,
        "PBEsol remaining wall budget invalid",
    )
    require(
        type(deadline) in {int, float}
        and math.isfinite(deadline)
        and now < deadline <= spec.deadline_unix,
        "PBEsol launch deadline expired or exceeds JobSpec",
    )
    require_live_lease(work)
    return projection


def run_guardian(request_path, parent_fd, profile_path, profile_sha256):
    profile = load_profile(profile_path, profile_sha256)
    raw_request = read_regular(request_path, 256 * 1024)
    request = strict_json(raw_request, 256 * 1024)
    require(
        request_path == Path(request["work"]).parent / "request.json",
        "guardian request/work location mismatch",
    )
    projection = validate_launch_request(request, profile)
    original_remaining = request["remaining_wall_seconds"]

    def before_launch():
        # Re-open independently immediately before the shared loop's Popen.
        current = load_profile(profile_path, profile_sha256)
        require(current == profile, "guardian profile changed before launch")
        require(
            sha(read_regular(request_path, 256 * 1024)) == sha(raw_request),
            "guardian request changed before launch",
        )
        checked = validate_launch_request(request, current)
        require(
            checked == projection, "guardian staged projection changed before launch"
        )
        require(
            available_memory_bytes() >= current.runtime.min_available_memory_bytes,
            "available memory fell below PBEsol launch floor",
        )
        require(
            shutil.disk_usage(Path(request["work"])).free
            >= current.runtime.min_free_bytes + current.runtime.max_scratch_bytes,
            "available disk fell below PBEsol launch floor",
        )
        require(
            not (
                select.select([parent_fd], [], [], 0)[0]
                and os.read(parent_fd, 1) == b""
            ),
            "worker disconnected before PBEsol launch",
        )
        # Resource inspection may take seconds. Check the lease again after it,
        # immediately before the final wall-clock budget and process creation.
        require_live_lease(Path(request["work"]))
        request["remaining_wall_seconds"] = min(
            original_remaining, request["launch_deadline_unix"] - time.time()
        )
        require(
            request["remaining_wall_seconds"] > 0,
            "PBEsol wall envelope expired before launch",
        )

    return supervise(
        request, parent_fd, descriptor=projection, before_launch=before_launch
    )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--request", type=Path, required=True)
    parser.add_argument("--parent-fd", type=int, required=True)
    parser.add_argument("--profile-config", type=Path, required=True)
    parser.add_argument("--profile-sha256", required=True)
    args = parser.parse_args()
    run_guardian(args.request, args.parent_fd, args.profile_config, args.profile_sha256)


if __name__ == "__main__":
    main()
