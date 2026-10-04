"""Static acceptance checks for supply-chain and DAST workflow invariants."""

from __future__ import annotations

import json
import hashlib
import os
import re
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
WORKFLOW_DIR = ROOT / ".github" / "workflows"
# Public formula/numeric token hashes in the frozen AB2H24 paper table. Only
# these introducing lines are excepted; the original scientific bytes stay pinned.
AB2H24_DIGEST_COMMIT = "f3c7b9f01c7b174e96a55b425b1c9166f337e3cc"
AB2H24_DIGEST_FILE = "frontend/public/research-pilots/discovery-ab2h24-source-table-2026-10-04.json"
AB2H24_DIGEST_SHA = "e63ab6df2fd73daf92cb75f0c7efda804cfda595a302f63e8b99fb55eaa9f362"
AB2H24_DIGEST_LINES = tuple(114 + row * 59 + field * 5 for row in range(21) for field in range(4))
REVIEWED_AB2H24_DIGEST_FINGERPRINTS = {
    f"{AB2H24_DIGEST_COMMIT}:{AB2H24_DIGEST_FILE}:generic-api-key:{line}"
    for line in AB2H24_DIGEST_LINES
}
LAH10_DIGEST_COMMIT = "97c2d5f00c443f9a67f59d4ad15ec5c687d06406"
LAH10_DIGEST_FILE = "frontend/public/research-pilots/discovery-lah10-pressure-series-2026-10-04.json"
LAH10_DIGEST_SHA = "f80b7b855c154163dc4a18d02489fc8c97882154abc735ff6582fddaf0804e9c"
LAH10_DIGEST_LINES = (387, 408, 423, 438, 453, 468, 483, 498, 512, 533, 548, 563, 578, 593, 608, 623, 637, 658, 673, 688, 703, 718, 733, 748, 762, 783, 798, 813, 828, 843, 858, 873, 887, 908, 923, 938, 953, 968, 983, 998, 1012, 1033, 1048, 1063, 1078, 1093, 1108, 1123, 1137, 1158, 1173, 1188, 1203, 1218, 1233, 1248)
REVIEWED_LAH10_DIGEST_FINGERPRINTS = {
    f"{LAH10_DIGEST_COMMIT}:{LAH10_DIGEST_FILE}:generic-api-key:{line}"
    for line in LAH10_DIGEST_LINES
}
# These positions were independently checked against the captured public source
# spans. Pin both the original commit and the full immutable file bytes: a new
# source revision must receive its own review, rather than inherit an exception.
SOURCE_DIGEST_COMMIT = "374e9b34a3ddc8aefb76792f07879b5b53ee965f"
REVIEWED_SOURCE_DIGESTS = {
    "frontend/public/research-pilots/materials-source-observations-2026-10-02.json": (
        "ac144451b2f03ca2e0e3dbd9ec27748e8257e1cac86473f384d6e5c34ea5f43e",
        (59, 128, 198, 266, 328, 333, 425, 515, 605, 707, 811, 915),
    ),
    "frontend/public/research-pilots/materials-source-followup-2026-10-02.json": (
        "c4014251af24bb8618f718ecd65edd13cc6c4afa00f7b0f82fa9ea29f192c1f8",
        (
            81, 478, 485, 492, 499, 506, 513, 652, 659, 790, 797, 804, 811,
            822, 829, 836, 843, 1040, 1051, 1058, 1065, 1072, 1079, 1090,
            1097, 1216, 1227, 1343, 1350, 1373, 1519, 1526, 1533, 1544,
            1551, 1670, 1677, 1688, 1695, 1813, 1824, 1922, 1929, 2081,
            2092, 2103, 2235, 2246, 2253, 2260, 2267, 2407, 2418, 2425,
            2526, 2533, 2680, 2691, 2837, 2844, 2851, 2862, 2869, 2876,
            2883, 2890, 2989, 2996, 3007, 3100, 3107, 3215, 3222, 3229,
            3240, 3333, 3340, 3347, 3925, 3932, 4018, 4025, 4130, 4239,
            4246, 4253, 4334,
        ),
    ),
}
REVIEWED_SOURCE_DIGEST_FINGERPRINTS = {
    f"{SOURCE_DIGEST_COMMIT}:{path}:generic-api-key:{line}"
    for path, (_, lines) in REVIEWED_SOURCE_DIGESTS.items()
    for line in lines
}
# Pressure/table expression identities are SHA-256 values, independently checked
# against the original v2 tuples. Pin the introducing commit and complete files;
# new revisions require a separate review and exact fingerprint registration.
PRESSURE_TABLE_DIGEST_COMMIT = "119b1ccd52e419ffb75cd818e3bf382d7878d4f6"
REVIEWED_PRESSURE_TABLE_DIGESTS = {
    "frontend/public/research-pilots/materials-pressure-table-bitecl-2026-10-02.json": (
        "01b164002ff2e092dd7f52cbba095acf3ae31322b97d25346b4f211d7cb5f5b3",
        (11, 135, 223, 297, 371, 501),
    ),
    "frontend/public/research-pilots/materials-pressure-table-mo-column-2-2026-10-02.json": (
        "2e3652462a9ae3e5610b24cc86dbedad237423ab8d0f61234e9589468c1db149",
        (11, 147, 283, 419, 555, 677),
    ),
    "frontend/public/research-pilots/materials-pressure-table-mo-column-3-2026-10-02.json": (
        "93fc3388cc32ab05c0a1e985d917aff256b1c6ba5eaf337ade209dceae3eaa9d",
        (11, 147, 283, 419, 555, 677),
    ),
    "frontend/public/research-pilots/materials-pressure-table-sources-2026-10-02.json": (
        "788144f67d439d0a5051e3b5144c988311e5423ccfa56402beb5566744ebe284",
        (58, 182, 270, 344, 418, 548, 678, 814, 950, 1086, 1222, 1344, 1424, 1560, 1696, 1832, 1968, 2090),
    ),
}
REVIEWED_PRESSURE_TABLE_DIGEST_FINGERPRINTS = {
    f"{PRESSURE_TABLE_DIGEST_COMMIT}:{path}:generic-api-key:{line}"
    for path, (_, lines) in REVIEWED_PRESSURE_TABLE_DIGESTS.items()
    for line in lines
}
# Reviewed immutable findings only. See the batch82 triage and original scan;
# new fixture revisions must be scanned and reviewed, never covered by a glob.
REVIEWED_FIXTURE_FINGERPRINTS = {
    # Recovery R8: SECRET_TRIAGE_MATERIALS_2026-10-02_R8.md.
    '01c42e51ae9f815c3997a33b44f5dc8ba117ae1f:frontend/tests/fixtures/discovery-main-barrier-native.materials20261002r8.wire.json:generic-api-key:1',
    '01c42e51ae9f815c3997a33b44f5dc8ba117ae1f:frontend/tests/fixtures/ml-pilot-attestations-native.materials20261002r8.wire.json:generic-api-key:1',
    '01c42e51ae9f815c3997a33b44f5dc8ba117ae1f:frontend/tests/fixtures/ml-pilot-participant-native.materials20261002r8.wire.json:generic-api-key:1',

    # Recovery R7: SECRET_TRIAGE_MATERIALS_2026-10-02_R7.md.
    'f4f3eba860bb7b4f4f00a2beb4829a167198707a:frontend/tests/fixtures/ml-pilot-attestations-native.materials20261002r7.wire.json:generic-api-key:1',
    'f4f3eba860bb7b4f4f00a2beb4829a167198707a:frontend/tests/fixtures/ml-pilot-participant-native.materials20261002r7.wire.json:generic-api-key:1',

    # Recovery R6: SECRET_TRIAGE_MATERIALS_2026-10-02_R6.md.
    '49020f06b2a3459379033985ab9cc60a1a26f5e3:frontend/tests/fixtures/discovery-main-barrier-native.materials20261002r6.wire.json:generic-api-key:1',
    '49020f06b2a3459379033985ab9cc60a1a26f5e3:frontend/tests/fixtures/ml-pilot-attestations-native.materials20261002r6.wire.json:generic-api-key:1',
    '49020f06b2a3459379033985ab9cc60a1a26f5e3:frontend/tests/fixtures/ml-pilot-participant-native.materials20261002r6.wire.json:generic-api-key:1',

    # Recovery R5: SECRET_TRIAGE_MATERIALS_2026-10-02_R5.md.
    '44872224e1a75ae36e9863ed756df0d7471d424e:frontend/tests/fixtures/discovery-main-barrier-native.materials20261002r5.wire.json:generic-api-key:1',
    '44872224e1a75ae36e9863ed756df0d7471d424e:frontend/tests/fixtures/ml-pilot-attestations-native.materials20261002r5.wire.json:generic-api-key:1',
    '44872224e1a75ae36e9863ed756df0d7471d424e:frontend/tests/fixtures/ml-pilot-participant-native.materials20261002r5.wire.json:generic-api-key:1',

    # Recovery R3: SECRET_TRIAGE_MATERIALS_2026-10-02_R3.md.
    '8b8b04fd048720f47917fc518e08b8089bf431be:frontend/tests/fixtures/discovery-main-barrier-native.materials20261002r3.wire.json:generic-api-key:1',
    '8b8b04fd048720f47917fc518e08b8089bf431be:frontend/tests/fixtures/ml-pilot-attestations-native.materials20261002r3.wire.json:generic-api-key:1',
    '8b8b04fd048720f47917fc518e08b8089bf431be:frontend/tests/fixtures/ml-pilot-participant-native.materials20261002r3.wire.json:generic-api-key:1',

    # Scientific reference R2: SECRET_TRIAGE_MATERIALS_2026-10-02_R2.md.
    '5b6e90305f6e783ec1127827b6f4bcc7c06f720f:frontend/tests/fixtures/discovery-main-barrier-native.materials20261002r2.wire.json:generic-api-key:1',
    '5b6e90305f6e783ec1127827b6f4bcc7c06f720f:frontend/tests/fixtures/ml-pilot-attestations-native.materials20261002r2.wire.json:generic-api-key:1',
    '5b6e90305f6e783ec1127827b6f4bcc7c06f720f:frontend/tests/fixtures/ml-pilot-participant-native.materials20261002r2.wire.json:generic-api-key:1',

    # Final enrichment batch: SECRET_TRIAGE_MATERIALS_2026-10-02.md.
    '6dfd994fb41b0160500512ab1d606b1c3a1b2b82:frontend/tests/fixtures/discovery-main-barrier-native.materials20261002.wire.json:generic-api-key:1',
    '6dfd994fb41b0160500512ab1d606b1c3a1b2b82:frontend/tests/fixtures/ml-pilot-attestations-native.materials20261002.wire.json:generic-api-key:1',
    '6dfd994fb41b0160500512ab1d606b1c3a1b2b82:frontend/tests/fixtures/ml-pilot-participant-native.materials20261002.wire.json:generic-api-key:1',

    # Materials upgrade: SECRET_TRIAGE_MATERIALS_2026-10-01.md.
    'f54eac6f28c655bad338ae726c571e6b97ac4c0c:frontend/tests/fixtures/discovery-main-barrier-native.materials20261001.wire.json:generic-api-key:1',
    'f54eac6f28c655bad338ae726c571e6b97ac4c0c:frontend/tests/fixtures/ml-pilot-attestations-native.materials20261001.wire.json:generic-api-key:1',
    'f54eac6f28c655bad338ae726c571e6b97ac4c0c:frontend/tests/fixtures/ml-pilot-participant-native.materials20261001.wire.json:generic-api-key:1',

    # Root-site release: SECRET_TRIAGE_SITE_2026-09-30.md.
    '650d1ef21f5554e0e0e0bfffb67270203ebbb1e3:frontend/tests/fixtures/ml-pilot-attestations-native.site20260930.wire.json:generic-api-key:1',
    '650d1ef21f5554e0e0e0bfffb67270203ebbb1e3:frontend/tests/fixtures/ml-pilot-participant-native.site20260930.wire.json:generic-api-key:1',

    # Site integration: SECRET_TRIAGE_SITE_2026-09-24.md.
    'c6b8d125a7d110a22cf8d1b349bd3d5f25e7bf38:frontend/tests/fixtures/discovery-main-barrier-native.site20260924.wire.json:generic-api-key:1',
    'c6b8d125a7d110a22cf8d1b349bd3d5f25e7bf38:frontend/tests/fixtures/ml-pilot-attestations-native.site20260924.wire.json:generic-api-key:1',
    'c6b8d125a7d110a22cf8d1b349bd3d5f25e7bf38:frontend/tests/fixtures/ml-pilot-participant-native.site20260924.wire.json:generic-api-key:1',

    # Materials pagination: SECRET_TRIAGE_MATERIALS_2026-09-24.md.
    '128331840e8b8e3756262156df345e7e68f216a5:frontend/tests/fixtures/discovery-main-barrier-native.delivery20260924r2.wire.json:generic-api-key:1',
    '128331840e8b8e3756262156df345e7e68f216a5:frontend/tests/fixtures/ml-pilot-attestations-native.delivery20260924r2.wire.json:generic-api-key:1',
    '128331840e8b8e3756262156df345e7e68f216a5:frontend/tests/fixtures/ml-pilot-participant-native.delivery20260924r2.wire.json:generic-api-key:1',

    # September 24: exact UUID request keys reviewed in SECRET_TRIAGE_2026-09-24.md.
    '7c85356fab990e3390142e680d410cf5ded1b25c:frontend/tests/fixtures/discovery-main-barrier-native.delivery20260924r1.wire.json:generic-api-key:1',
    '7c85356fab990e3390142e680d410cf5ded1b25c:frontend/tests/fixtures/ml-pilot-attestations-native.delivery20260924r1.wire.json:generic-api-key:1',
    '7c85356fab990e3390142e680d410cf5ded1b25c:frontend/tests/fixtures/ml-pilot-participant-native.delivery20260924r1.wire.json:generic-api-key:1',

    # September 23 r4: exact decoded synthetic request keys; retained triage receipt.
    'f09b90e58b28aa549dbd1516acb276979a2378c5:frontend/tests/fixtures/ml-pilot-attestations-native.delivery20260923r4.wire.json:generic-api-key:1',
    'f09b90e58b28aa549dbd1516acb276979a2378c5:frontend/tests/fixtures/ml-pilot-participant-native.delivery20260923r4.wire.json:generic-api-key:1',

    # September 23 r3: exact decoded synthetic request keys; retained triage receipt.
    '9c3d348a53ae7acf62fd64c026de675d9b0693b0:frontend/tests/fixtures/ml-pilot-attestations-native.delivery20260923r3.wire.json:generic-api-key:1',
    '9c3d348a53ae7acf62fd64c026de675d9b0693b0:frontend/tests/fixtures/ml-pilot-participant-native.delivery20260923r3.wire.json:generic-api-key:1',

    # September 23 r2: exact decoded synthetic request keys; retained triage receipt.
    '473c429de54f067c7befa282a189328b9ccf6bf2:frontend/tests/fixtures/ml-pilot-attestations-native.delivery20260923r2.wire.json:generic-api-key:1',
    '473c429de54f067c7befa282a189328b9ccf6bf2:frontend/tests/fixtures/ml-pilot-participant-native.delivery20260923r2.wire.json:generic-api-key:1',

    # September 23 r1: exact decoded synthetic request keys; retained triage receipt.
    '6c0225303feb30178f8504eba66e1bc1b0f516d3:frontend/tests/fixtures/discovery-main-barrier-native.delivery20260923r1.wire.json:generic-api-key:1',
    '6c0225303feb30178f8504eba66e1bc1b0f516d3:frontend/tests/fixtures/ml-pilot-attestations-native.delivery20260923r1.wire.json:generic-api-key:1',
    '6c0225303feb30178f8504eba66e1bc1b0f516d3:frontend/tests/fixtures/ml-pilot-participant-native.delivery20260923r1.wire.json:generic-api-key:1',

    # September 22 r10: exact decoded synthetic request keys; retained triage receipt.
    '7a86652628acc9548b4feabcc40bf92ac52a89a9:frontend/tests/fixtures/discovery-main-barrier-native.delivery20260922r10.wire.json:generic-api-key:1',
    '7a86652628acc9548b4feabcc40bf92ac52a89a9:frontend/tests/fixtures/ml-pilot-attestations-native.delivery20260922r10.wire.json:generic-api-key:1',
    '7a86652628acc9548b4feabcc40bf92ac52a89a9:frontend/tests/fixtures/ml-pilot-participant-native.delivery20260922r10.wire.json:generic-api-key:1',

    # September 22 r9: exact decoded synthetic request keys.
    'ddce46287d35c013f0c3df623509eab3b3eaec1d:frontend/tests/fixtures/discovery-main-barrier-native.delivery20260922r9.wire.json:generic-api-key:1',
    'ddce46287d35c013f0c3df623509eab3b3eaec1d:frontend/tests/fixtures/ml-pilot-attestations-native.delivery20260922r9.wire.json:generic-api-key:1',
    'ddce46287d35c013f0c3df623509eab3b3eaec1d:frontend/tests/fixtures/ml-pilot-participant-native.delivery20260922r9.wire.json:generic-api-key:1',

    # September 22 r8: exact decoded synthetic request keys.
    '83adc706fec25985fab4e12626249cc11f71dd14:frontend/tests/fixtures/discovery-main-barrier-native.delivery20260922r8.wire.json:generic-api-key:1',
    '83adc706fec25985fab4e12626249cc11f71dd14:frontend/tests/fixtures/ml-pilot-attestations-native.delivery20260922r8.wire.json:generic-api-key:1',
    '83adc706fec25985fab4e12626249cc11f71dd14:frontend/tests/fixtures/ml-pilot-participant-native.delivery20260922r8.wire.json:generic-api-key:1',

    # September 22 r7: exact decoded synthetic request keys.
    'eeecd636b4e6e4e56005a261b09b437e1584917d:frontend/tests/fixtures/discovery-main-barrier-native.delivery20260922r7.wire.json:generic-api-key:1',
    'eeecd636b4e6e4e56005a261b09b437e1584917d:frontend/tests/fixtures/ml-pilot-attestations-native.delivery20260922r7.wire.json:generic-api-key:1',
    'eeecd636b4e6e4e56005a261b09b437e1584917d:frontend/tests/fixtures/ml-pilot-participant-native.delivery20260922r7.wire.json:generic-api-key:1',

    # September 22 r6: exact decoded synthetic request keys.
    '40bde0d4654af4565764fa40a0dc5e5de23b9200:frontend/tests/fixtures/discovery-main-barrier-native.delivery20260922r6.wire.json:generic-api-key:1',
    '40bde0d4654af4565764fa40a0dc5e5de23b9200:frontend/tests/fixtures/ml-pilot-attestations-native.delivery20260922r6.wire.json:generic-api-key:1',
    '40bde0d4654af4565764fa40a0dc5e5de23b9200:frontend/tests/fixtures/ml-pilot-participant-native.delivery20260922r6.wire.json:generic-api-key:1',

    # September 22 r5: exact decoded synthetic request keys.
    'a3436b508d87ccfa307c266f7dcada10c404bd9a:frontend/tests/fixtures/discovery-main-barrier-native.delivery20260922r5.wire.json:generic-api-key:1',
    'a3436b508d87ccfa307c266f7dcada10c404bd9a:frontend/tests/fixtures/ml-pilot-attestations-native.delivery20260922r5.wire.json:generic-api-key:1',
    'a3436b508d87ccfa307c266f7dcada10c404bd9a:frontend/tests/fixtures/ml-pilot-participant-native.delivery20260922r5.wire.json:generic-api-key:1',

    # September 22 r4: exact decoded synthetic request keys.
    '2a3e548d454c2434f34948c26fe1e2a73daa2242:frontend/tests/fixtures/discovery-main-barrier-native.delivery20260922r4.wire.json:generic-api-key:1',
    '2a3e548d454c2434f34948c26fe1e2a73daa2242:frontend/tests/fixtures/ml-pilot-attestations-native.delivery20260922r4.wire.json:generic-api-key:1',
    '2a3e548d454c2434f34948c26fe1e2a73daa2242:frontend/tests/fixtures/ml-pilot-participant-native.delivery20260922r4.wire.json:generic-api-key:1',

    # September 22 r3: individually decoded synthetic request keys.
    'ae860ae6960fbaa002252676b9925093412d8344:frontend/tests/fixtures/discovery-main-barrier-native.delivery20260922r3.wire.json:generic-api-key:1',
    'ae860ae6960fbaa002252676b9925093412d8344:frontend/tests/fixtures/ml-pilot-attestations-native.delivery20260922r3.wire.json:generic-api-key:1',
    'ae860ae6960fbaa002252676b9925093412d8344:frontend/tests/fixtures/ml-pilot-participant-native.delivery20260922r3.wire.json:generic-api-key:1',

    # September 22: exact synthetic keys and the public frontend API source hash.
    '5d3095a9fc71d6e5f9c83752035135383afe4fc0:docs/reviews/2026-09-05/delivery-2026-09-22/timeline-display-acceptance.json:generic-api-key:6',
    '5d3095a9fc71d6e5f9c83752035135383afe4fc0:frontend/tests/fixtures/discovery-main-barrier-native.delivery20260922r2.wire.json:generic-api-key:1',
    '5d3095a9fc71d6e5f9c83752035135383afe4fc0:frontend/tests/fixtures/ml-pilot-attestations-native.delivery20260922r1.wire.json:generic-api-key:1',
    '5d3095a9fc71d6e5f9c83752035135383afe4fc0:frontend/tests/fixtures/ml-pilot-attestations-native.delivery20260922r2.wire.json:generic-api-key:1',
    '5d3095a9fc71d6e5f9c83752035135383afe4fc0:frontend/tests/fixtures/ml-pilot-participant-native.delivery20260922r1.wire.json:generic-api-key:1',
    '5d3095a9fc71d6e5f9c83752035135383afe4fc0:frontend/tests/fixtures/ml-pilot-participant-native.delivery20260922r2.wire.json:generic-api-key:1',

    # r9 receipts: three synthetic request-key archives and one public source-file digest.
    'f390087e544cbe3b71c7f7016687b9e8ad8aac23:docs/reviews/2026-09-05/delivery-2026-09-21/remote-release/anomaly-sparse-source-comparison.json:generic-api-key:2',
    'f390087e544cbe3b71c7f7016687b9e8ad8aac23:frontend/tests/fixtures/discovery-main-barrier-native.delivery20260921r9.wire.json:generic-api-key:1',
    'f390087e544cbe3b71c7f7016687b9e8ad8aac23:frontend/tests/fixtures/ml-pilot-attestations-native.delivery20260921r9.wire.json:generic-api-key:1',
    'f390087e544cbe3b71c7f7016687b9e8ad8aac23:frontend/tests/fixtures/ml-pilot-participant-native.delivery20260921r9.wire.json:generic-api-key:1',

    'f189aea10183ef7ea8ed66ee2d66249c151433de:frontend/tests/fixtures/ml-pilot-attestations-native.delivery20260921r8.wire.json:generic-api-key:1',
    'f189aea10183ef7ea8ed66ee2d66249c151433de:frontend/tests/fixtures/ml-pilot-participant-native.delivery20260921r8.wire.json:generic-api-key:1',

    '2540ee9498d11f5e42e81376b8ef8bc64ceb2f0b:frontend/tests/fixtures/discovery-main-barrier-native.delivery20260921r6.wire.json:generic-api-key:1',
    '2540ee9498d11f5e42e81376b8ef8bc64ceb2f0b:frontend/tests/fixtures/discovery-main-barrier-native.delivery20260921r7.wire.json:generic-api-key:1',
    '2540ee9498d11f5e42e81376b8ef8bc64ceb2f0b:frontend/tests/fixtures/ml-pilot-attestations-native.delivery20260921r6.wire.json:generic-api-key:1',
    '2540ee9498d11f5e42e81376b8ef8bc64ceb2f0b:frontend/tests/fixtures/ml-pilot-attestations-native.delivery20260921r7.wire.json:generic-api-key:1',
    '2540ee9498d11f5e42e81376b8ef8bc64ceb2f0b:frontend/tests/fixtures/ml-pilot-participant-native.delivery20260921r6.wire.json:generic-api-key:1',
    '2540ee9498d11f5e42e81376b8ef8bc64ceb2f0b:frontend/tests/fixtures/ml-pilot-participant-native.delivery20260921r7.wire.json:generic-api-key:1',

    'd0aa52f1de7842e9a76ef47f8e5ec7d8d5589333:frontend/tests/fixtures/discovery-main-barrier-native.delivery20260921r5.wire.json:generic-api-key:1',
    'd0aa52f1de7842e9a76ef47f8e5ec7d8d5589333:frontend/tests/fixtures/ml-pilot-attestations-native.delivery20260921r5.wire.json:generic-api-key:1',
    'd0aa52f1de7842e9a76ef47f8e5ec7d8d5589333:frontend/tests/fixtures/ml-pilot-participant-native.delivery20260921r5.wire.json:generic-api-key:1',
    'b5e32d20142b5d3496fd63b5f21d3c5e58bb10c9:frontend/tests/fixtures/discovery-main-barrier-native.delivery20260921r4.wire.json:generic-api-key:1',
    'b5e32d20142b5d3496fd63b5f21d3c5e58bb10c9:frontend/tests/fixtures/ml-pilot-attestations-native.delivery20260921r4.wire.json:generic-api-key:1',
    'b5e32d20142b5d3496fd63b5f21d3c5e58bb10c9:frontend/tests/fixtures/ml-pilot-participant-native.delivery20260921r4.wire.json:generic-api-key:1',
    'c16f164fdfe5f1ec56fc1a05cf11d9f974894998:frontend/tests/fixtures/ml-pilot-attestations-native.delivery20260921r3.wire.json:generic-api-key:1',
    'c16f164fdfe5f1ec56fc1a05cf11d9f974894998:frontend/tests/fixtures/ml-pilot-participant-native.delivery20260921r3.wire.json:generic-api-key:1',
    '83096af42d7cab7e0e8be6893581b4d122074b75:frontend/tests/fixtures/discovery-main-barrier-native.delivery20260921r2.wire.json:generic-api-key:1',
    '83096af42d7cab7e0e8be6893581b4d122074b75:frontend/tests/fixtures/ml-pilot-attestations-native.delivery20260921r2.wire.json:generic-api-key:1',
    '83096af42d7cab7e0e8be6893581b4d122074b75:frontend/tests/fixtures/ml-pilot-participant-native.delivery20260921r2.wire.json:generic-api-key:1',
    '20f85421348da25118508aa34c40307fece6579a:frontend/tests/fixtures/discovery-main-barrier-native.delivery20260921.wire.json:generic-api-key:1',
    '20f85421348da25118508aa34c40307fece6579a:frontend/tests/fixtures/ml-pilot-attestations-native.delivery20260921.wire.json:generic-api-key:1',
    '20f85421348da25118508aa34c40307fece6579a:frontend/tests/fixtures/ml-pilot-participant-native.delivery20260921.wire.json:generic-api-key:1',

    '2374b5a42608300257316a3a49245e077e53a1ec:frontend/tests/fixtures/discovery-main-barrier-native.delivery20260915r2.wire.json:generic-api-key:1',
    '2374b5a42608300257316a3a49245e077e53a1ec:frontend/tests/fixtures/ml-pilot-attestations-native.delivery20260915r2.wire.json:generic-api-key:1',
    '2374b5a42608300257316a3a49245e077e53a1ec:frontend/tests/fixtures/ml-pilot-participant-native.delivery20260915r2.wire.json:generic-api-key:1',

    'a05fb46d83909107cdb221bbc5ac2c619edb4a49:frontend/tests/fixtures/discovery-main-barrier-native.batch75.wire.json:generic-api-key:1',
    'a05fb46d83909107cdb221bbc5ac2c619edb4a49:frontend/tests/fixtures/discovery-main-barrier-native.batch82.wire.json:generic-api-key:1',
    'a05fb46d83909107cdb221bbc5ac2c619edb4a49:frontend/tests/fixtures/discovery-main-barrier-native.delivery20260915.wire.json:generic-api-key:1',
    'a05fb46d83909107cdb221bbc5ac2c619edb4a49:frontend/tests/fixtures/ml-pilot-attestations-native.batch74.wire.json:generic-api-key:1',
    'a05fb46d83909107cdb221bbc5ac2c619edb4a49:frontend/tests/fixtures/ml-pilot-attestations-native.batch75.wire.json:generic-api-key:1',
    'a05fb46d83909107cdb221bbc5ac2c619edb4a49:frontend/tests/fixtures/ml-pilot-attestations-native.batch82.wire.json:generic-api-key:1',
    'a05fb46d83909107cdb221bbc5ac2c619edb4a49:frontend/tests/fixtures/ml-pilot-attestations-native.delivery20260915.wire.json:generic-api-key:1',
    'a05fb46d83909107cdb221bbc5ac2c619edb4a49:frontend/tests/fixtures/ml-pilot-participant-native.batch74.wire.json:generic-api-key:1',
    'a05fb46d83909107cdb221bbc5ac2c619edb4a49:frontend/tests/fixtures/ml-pilot-participant-native.batch75.wire.json:generic-api-key:1',
    'a05fb46d83909107cdb221bbc5ac2c619edb4a49:frontend/tests/fixtures/ml-pilot-participant-native.batch82.wire.json:generic-api-key:1',
    'a05fb46d83909107cdb221bbc5ac2c619edb4a49:frontend/tests/fixtures/ml-pilot-participant-native.delivery20260915.wire.json:generic-api-key:1',

    (
        "00718749b6eb15926ae8cbfc58e02a9432488815:"
        "frontend/tests/fixtures/discovery-governance/provenance.json:generic-api-key:860"
    ),
    (
        "00718749b6eb15926ae8cbfc58e02a9432488815:"
        "frontend/tests/fixtures/discovery-selection/provenance.json:generic-api-key:217"
    ),
    (
        "02949468802db042e56645e2932b08863a174074:"
        "frontend/tests/fixtures/ml-pilot-attestations-native.batch73.wire.json:generic-api-key:1"
    ),
    (
        "02949468802db042e56645e2932b08863a174074:"
        "frontend/tests/fixtures/ml-pilot-participant-native.batch73.wire.json:generic-api-key:1"
    ),
    (
        "2cff9326c29b8f441f6436ad98ce47466455697f:"
        "frontend/tests/fixtures/discovery-main-barrier-native.batch55.wire.json:generic-api-key:83"
    ),
    (
        "2cff9326c29b8f441f6436ad98ce47466455697f:"
        "frontend/tests/fixtures/discovery-main-barrier-native.batch56.wire.json:generic-api-key:83"
    ),
    (
        "2cff9326c29b8f441f6436ad98ce47466455697f:"
        "frontend/tests/fixtures/discovery-main-barrier-native.wire.json:generic-api-key:83"
    ),
    (
        "30a8b475608ffbba429ccb5f3ab10275714605e6:"
        "frontend/tests/fixtures/source-task-operations-http.json:generic-api-key:150"
    ),
    (
        "30a8b475608ffbba429ccb5f3ab10275714605e6:"
        "frontend/tests/fixtures/source-task-operations-http.json:generic-api-key:188"
    ),
    (
        "30a8b475608ffbba429ccb5f3ab10275714605e6:"
        "frontend/tests/fixtures/source-task-operations-http.json:generic-api-key:225"
    ),
    (
        "30a8b475608ffbba429ccb5f3ab10275714605e6:"
        "frontend/tests/fixtures/source-task-operations-http.json:generic-api-key:276"
    ),
    (
        "30a8b475608ffbba429ccb5f3ab10275714605e6:"
        "frontend/tests/fixtures/source-task-operations-http.json:generic-api-key:469"
    ),
    (
        "30a8b475608ffbba429ccb5f3ab10275714605e6:"
        "frontend/tests/fixtures/source-task-operations-http.json:generic-api-key:68"
    ),
    (
        "30a8b475608ffbba429ccb5f3ab10275714605e6:"
        "frontend/tests/fixtures/source-task-operations-http.json:generic-api-key:81"
    ),
    (
        "531975a02ed78e212b6902314ad53328dc29f83f:"
        "frontend/tests/fixtures/discovery-scientific-provenance.json:generic-api-key:67"
    ),
    (
        "634265d7cd2323a077045d4042ee8dbdabe86f19:"
        "frontend/tests/fixtures/discovery-main-barrier-native.batch67.wire.json:generic-api-key:1"
    ),
    (
        "add2b2ae76b28588a9eb9aa82dca1d8eae8d30ad:"
        "frontend/tests/fixtures/discovery-main-barrier-native.batch57.wire.json:generic-api-key:83"
    ),
    (
        "add2b2ae76b28588a9eb9aa82dca1d8eae8d30ad:"
        "frontend/tests/fixtures/discovery-main-barrier-native.wire.json:generic-api-key:83"
    ),
    (
        "c482a478492d537071676e997616fa6b7d74710b:"
        "frontend/tests/fixtures/discovery-selection/provenance.json:generic-api-key:1"
    ),
    (
        "c4b8fb5cb0dcd04e37406be5014e298b108ee9e5:"
        "frontend/tests/fixtures/discovery-main-barrier-native.batch59.wire.json:generic-api-key:83"
    ),
    (
        "c4b8fb5cb0dcd04e37406be5014e298b108ee9e5:"
        "frontend/tests/fixtures/discovery-main-barrier-native.wire.json:generic-api-key:1"
    ),
    (
        "c6f05f1ca757f692d3f5169768b2fd75c6f685eb:"
        "docs/reviews/2026-09-05/issues-discovery-rag.json:generic-api-key:183"
    ),
    (
        "cc769d8df206ba64f4633b3a4802199623dfd82b:"
        "frontend/tests/fixtures/discovery-main-barrier-native.batch58.wire.json:generic-api-key:83"
    ),
    (
        "cc769d8df206ba64f4633b3a4802199623dfd82b:"
        "frontend/tests/fixtures/discovery-main-barrier-native.wire.json:generic-api-key:83"
    ),
    (
        "d42d0dd4ed0ae263fd7b4720982e1ed670bc4598:"
        "frontend/tests/fixtures/discovery-main-barrier-native.batch52.wire.json:generic-api-key:83"
    ),
    (
        "d42d0dd4ed0ae263fd7b4720982e1ed670bc4598:"
        "frontend/tests/fixtures/discovery-main-barrier-native.batch54.wire.json:generic-api-key:83"
    ),
    (
        "d42d0dd4ed0ae263fd7b4720982e1ed670bc4598:"
        "frontend/tests/fixtures/discovery-main-barrier-native.wire.json:generic-api-key:83"
    ),
    (
        "dc716fba4ce14b26623cc70cdd3f5b0c49b0a2f7:"
        "frontend/tests/fixtures/discovery-main-barrier-native.batch72.wire.json:generic-api-key:1"
    ),
    (
        "dc716fba4ce14b26623cc70cdd3f5b0c49b0a2f7:"
        "frontend/tests/fixtures/ml-pilot-attestations-native.batch72.wire.json:generic-api-key:1"
    ),
    (
        "dc716fba4ce14b26623cc70cdd3f5b0c49b0a2f7:"
        "frontend/tests/fixtures/ml-pilot-participant-native.batch72.wire.json:generic-api-key:1"
    ),
    (
        "dd4fb7746a8e7707951884f521088e0a262f5d33:"
        "frontend/tests/fixtures/discovery-main-barrier-native.batch68.wire.json:generic-api-key:1"
    ),
    (
        "dd4fb7746a8e7707951884f521088e0a262f5d33:"
        "frontend/tests/fixtures/discovery-main-barrier-native.batch69.wire.json:generic-api-key:1"
    ),
    (
        "dd4fb7746a8e7707951884f521088e0a262f5d33:"
        "frontend/tests/fixtures/discovery-main-barrier-native.batch70.wire.json:generic-api-key:1"
    ),
    (
        "dd4fb7746a8e7707951884f521088e0a262f5d33:"
        "frontend/tests/fixtures/discovery-main-barrier-native.batch71.wire.json:generic-api-key:1"
    ),
    (
        "dd4fb7746a8e7707951884f521088e0a262f5d33:"
        "frontend/tests/fixtures/ml-pilot-participant-native.batch70.wire.json:generic-api-key:1"
    ),
    (
        "dd4fb7746a8e7707951884f521088e0a262f5d33:"
        "frontend/tests/fixtures/ml-pilot-participant-native.batch71.wire.json:generic-api-key:1"
    ),
}
PINNED_ACTION = re.compile(r"^\s*-?\s*uses:\s+[^\s@]+@[0-9a-f]{40}(?:\s+#.*)?$")


class SecurityWorkflowTests(unittest.TestCase):
    def test_all_remote_actions_are_pinned_to_full_commit_sha(self) -> None:
        for workflow in sorted(WORKFLOW_DIR.glob("*.yml")):
            for line_number, line in enumerate(workflow.read_text().splitlines(), 1):
                if "uses:" not in line or "uses: ./" in line:
                    continue
                self.assertRegex(
                    line,
                    PINNED_ACTION,
                    f"{workflow.name}:{line_number} must pin uses: to a full SHA",
                )

    def test_dast_targets_only_ephemeral_loopback_services(self) -> None:
        dast = (WORKFLOW_DIR / "dast.yml").read_text()
        self.assertIn("sclib_dast", dast)
        self.assertIn("127.0.0.1:8000", dast)
        self.assertIn("127.0.0.1:3000", dast)
        self.assertNotIn("jzis.org", dast)
        self.assertNotIn("72.62.251.29", dast)

    def test_security_workflow_covers_required_scanners(self) -> None:
        security = (WORKFLOW_DIR / "security.yml").read_text()
        for required in (
            "github/codeql-action/init@",
            "gitleaks/gitleaks-action@",
            "pip-audit==2.9.0",
            "pnpm audit --prod --audit-level high",
            "aquasecurity/trivy-action@",
            "version: v0.70.0",
        ):
            self.assertIn(required, security)
        self.assertIn("working-directory: api", security)
        self.assertIn("working-directory: ingestion", security)
        self.assertNotIn("uv --quiet export --project", security)

    def test_gitleaks_exceptions_are_exact_fingerprints(self) -> None:
        ignore_file = ROOT / ".gitleaksignore"
        fingerprints = [
            line
            for line in ignore_file.read_text().splitlines()
            if line and not line.startswith("#")
        ]
        self.assertEqual(len(fingerprints), len(set(fingerprints)))
        self.assertEqual(
            set(fingerprints),
            {
                (
                    "d60f0db35de7e46d3f6e1a6907886b134feacef1:"
                    "README.md:curl-auth-header:133"
                ),
                (
                    "7596ef2e5928c46e2b0da6bcfaf48ab6fabe3d35:"
                    "api/tests/test_unified_auth.py:generic-api-key:319"
                ),
                (
                    "3477605e37393b8430068d38a822b758816bc025:"
                    "PROJECT_SPEC.md:generic-api-key:892"
                ),
                (
                    "c499146b223562c5099ab971a149392067ca047e:"
                    "api/tests/test_session_security.py:generic-api-key:17"
                ),
                (
                    "c499146b223562c5099ab971a149392067ca047e:"
                    "api/tests/test_session_security.py:generic-api-key:54"
                ),
            } | REVIEWED_FIXTURE_FINGERPRINTS | REVIEWED_SOURCE_DIGEST_FINGERPRINTS | REVIEWED_PRESSURE_TABLE_DIGEST_FINGERPRINTS | REVIEWED_AB2H24_DIGEST_FINGERPRINTS | REVIEWED_LAH10_DIGEST_FINGERPRINTS,
        )

    def test_ab2h24_exceptions_recompute_public_literal_hashes(self) -> None:
        raw = (ROOT / AB2H24_DIGEST_FILE).read_bytes()
        self.assertEqual(hashlib.sha256(raw).hexdigest(), AB2H24_DIGEST_SHA)
        metadata = json.loads(raw)
        source_lines = raw.decode().splitlines()
        triage = json.loads((ROOT / "docs/reviews/2026-10-05/discovery-source-digests/secret-triage.json").read_text())
        self.assertEqual(triage["commit"], AB2H24_DIGEST_COMMIT)
        self.assertEqual(triage["file"], AB2H24_DIGEST_FILE)
        self.assertEqual(triage["file_sha256"], AB2H24_DIGEST_SHA)
        self.assertEqual(triage["source_text_sha256"], metadata["source"]["derived_text_sha256"])
        self.assertEqual(triage["findings"], 84)
        self.assertEqual(triage["source_tokens_recomputed"], 84)
        self.assertEqual(len(triage["entries"]), 84)
        self.assertEqual({entry["fingerprint"] for entry in triage["entries"]}, REVIEWED_AB2H24_DIGEST_FINGERPRINTS)
        tokens = [(row, field, locator) for row in metadata["rows"] for field, locator in row["field_locators"].items()]
        self.assertEqual(len(tokens), 84)
        for line, (row, field, locator), entry in zip(AB2H24_DIGEST_LINES, tokens, triage["entries"]):
            token = row["formula"] if field == "formula" else row[field]["raw_value"]
            digest = hashlib.sha256(token.encode()).hexdigest()
            self.assertEqual(locator["token_sha256"], digest)
            self.assertEqual(locator["char_end"] - locator["char_start"], len(token))
            self.assertEqual(entry, {
                "fingerprint": f"{AB2H24_DIGEST_COMMIT}:{AB2H24_DIGEST_FILE}:generic-api-key:{line}",
                "line": line, "row_id": row["id"], "field": field,
                "char_start": locator["char_start"], "char_end": locator["char_end"], "literal_sha256": digest,
            })
            self.assertRegex(source_lines[line - 1], r'^\s*"token_sha256": "[0-9a-f]{64}"[,]?$')
            self.assertIn(digest, source_lines[line - 1])

    def test_lah10_exceptions_recompute_public_literal_hashes(self) -> None:
        raw = (ROOT / LAH10_DIGEST_FILE).read_bytes()
        self.assertEqual(hashlib.sha256(raw).hexdigest(), LAH10_DIGEST_SHA)
        data = json.loads(raw)
        triage = json.loads((ROOT / "docs/reviews/2026-10-05/discovery-source-digests/lah10-secret-triage.json").read_text())
        self.assertEqual(triage["file_sha256"], LAH10_DIGEST_SHA)
        self.assertEqual(triage["source_text_sha256"], data["source"]["derived_text_sha256"])
        self.assertEqual(triage["commit"], LAH10_DIGEST_COMMIT)
        self.assertEqual(triage["file"], LAH10_DIGEST_FILE)
        self.assertEqual(triage["findings"], 56)
        self.assertEqual(triage["source_tokens_recomputed"], 56)
        self.assertEqual({x["fingerprint"] for x in triage["entries"]}, REVIEWED_LAH10_DIGEST_FINGERPRINTS)
        tokens = []
        for row in data["rows"]:
            tokens.append((row["id"], "formula", row["formula"], row["formula_locator"]))
            tokens.extend((row["id"], key, value["raw_value"], value["locator"]) for key, value in row.items() if isinstance(value, dict) and "raw_value" in value)
        self.assertEqual(len(tokens), 56)
        self.assertEqual(len(triage["entries"]), 56)
        for line, (row_id, field, token, locator), entry in zip(LAH10_DIGEST_LINES, tokens, triage["entries"]):
            digest = hashlib.sha256(token.encode()).hexdigest()
            self.assertEqual(digest, locator["token_sha256"])
            self.assertEqual(entry, {"fingerprint": f"{LAH10_DIGEST_COMMIT}:{LAH10_DIGEST_FILE}:generic-api-key:{line}", "line": line, "row_id": row_id, "field": field, "char_start": locator["char_start"], "char_end": locator["char_end"], "literal_sha256": digest})
            self.assertIn(digest, raw.decode().splitlines()[line - 1])
            self.assertRegex(raw.decode().splitlines()[line - 1], r'^\s*"token_sha256": "[0-9a-f]{64}"[,]?$')

    def test_pressure_table_exceptions_bind_exact_expression_hash_lines(self) -> None:
        self.assertEqual(len(REVIEWED_PRESSURE_TABLE_DIGEST_FINGERPRINTS), 36)
        unique_keys = set()
        for path, (file_sha, lines) in REVIEWED_PRESSURE_TABLE_DIGESTS.items():
            raw = (ROOT / path).read_bytes()
            self.assertEqual(hashlib.sha256(raw).hexdigest(), file_sha)
            source_lines = raw.decode("utf-8").splitlines()
            metadata = json.loads(raw)
            self.assertIs(metadata["scientific_acceptance"], False)
            self.assertEqual(metadata["canonical_promotions"], 0)
            self.assertEqual(metadata["status"], "pending")
            self.assertEqual(metadata["selected_result_association"], "unestablished")
            keys = {entry["expression_key"] for entry in metadata["entries"]}
            self.assertEqual(len(keys), len(lines))
            for line in lines:
                self.assertRegex(source_lines[line - 1], r'^\s*"expression_key": "[0-9a-f]{64}",$')
                self.assertIn(json.loads("{" + source_lines[line - 1].strip().rstrip(",") + "}")["expression_key"], keys)
            unique_keys.update(keys)
        self.assertEqual(len(unique_keys), 18)

    def test_source_digest_exceptions_bind_exact_public_bytes_and_audit(self) -> None:
        triage = json.loads(
            (ROOT / "docs/reviews/2026-10-02/materials-source-observations/secret-triage.json")
            .read_text()
        )
        self.assertEqual(triage["version"], "materials-source-span-secret-triage/1.0.0")
        self.assertEqual(triage["reviewed_findings"], 99)
        self.assertEqual(triage["exact_fingerprints"], 99)
        for key in ("broad_rules_disabled", "path_or_commit_globs_used", "raw_projection_files_rewritten"):
            self.assertIs(triage[key], False)
        self.assertEqual(triage["original_scan_exit_code"], 1)
        self.assertEqual(triage["original_scan_scope"], f"HEAD ancestors at {SOURCE_DIGEST_COMMIT}")
        entries = triage["entries"]
        self.assertEqual(len(entries), 99)
        self.assertEqual({entry["fingerprint"] for entry in entries}, REVIEWED_SOURCE_DIGEST_FINGERPRINTS)
        for path, (file_sha, lines) in REVIEWED_SOURCE_DIGESTS.items():
            raw = (ROOT / path).read_bytes()
            self.assertEqual(hashlib.sha256(raw).hexdigest(), file_sha)
            source_lines = raw.decode("utf-8").splitlines()
            file_entries = [entry for entry in entries if entry["file"] == path]
            self.assertEqual(sorted(entry["line"] for entry in file_entries), sorted(lines))
            self.assertEqual(len(file_entries), len(lines))
            for entry in file_entries:
                self.assertEqual(entry["commit"], SOURCE_DIGEST_COMMIT)
                self.assertEqual(entry["rule_id"], "generic-api-key")
                self.assertEqual(entry["source_field"], "token_sha256")
                self.assertEqual(entry["file_sha256"], file_sha)
                self.assertEqual(
                    entry["fingerprint"],
                    f"{SOURCE_DIGEST_COMMIT}:{path}:generic-api-key:{entry['line']}",
                )
                self.assertIs(entry["exact_original_line_verified"], True)
                self.assertEqual(
                    entry["classification"],
                    "Public captured-source text-span SHA-256 digest; not an authentication credential",
                )
                self.assertRegex(
                    source_lines[entry["line"] - 1],
                    r'^\s*"token_sha256": "[0-9a-f]{64}"[,]?$',
                )
        self.assertEqual(triage["independent_review"], {
            "receipt_sha256": "22f72393e9480346f2a1324f4d21e780adcf746a71ce30fc4d12a86df6d88772",
            "archive_manifest_sha256": "a458961cd00d7213ac7b96c860954b093eb7dd575d6861022ba9b58fc451607a",
            "original_capture_digest_fields_recomputed": 100,
            "original_capture_digest_mismatches": 0,
            "exact_fingerprint_set_verified": True,
            "scientific_acceptance": False,
        })

    def test_release_binds_scan_signature_and_provenance_to_digest(self) -> None:
        release = (WORKFLOW_DIR / "release-images.yml").read_text()
        for required in (
            "workflows: [Test]",
            "github.event.workflow_run.head_sha",
            "Require matching Security success",
            "actions/workflows/security.yml/runs",
            ".head_sha == $sha",
            "needs: verify-security",
            "@${{ steps.build.outputs.digest }}",
            "cosign sign --yes",
            "actions/attest-build-provenance@",
            "anchore/sbom-action@",
            "aquasecurity/trivy-action@",
            "limit-severities-for-sarif: true",
            '${{ matrix.component }}.sha',
        ):
            self.assertIn(required, release)
        self.assertNotIn(":latest", release)

    def test_deploy_consumes_only_verified_release_digests(self) -> None:
        deploy = (WORKFLOW_DIR / "deploy.yml").read_text()
        compose = (ROOT / "docker-compose.prod.yml").read_text()
        installer = (ROOT / "scripts" / "install_cosign.sh").read_text()
        for required in (
            "workflows: [Release images]",
            "actions/download-artifact@",
            "^sha256:[0-9a-f]{64}$",
            "cosign verify",
            "scripts/check_error_budget.py",
            "--no-build",
        ):
            self.assertIn(required, deploy)
        self.assertNotIn("docker compose build", deploy)
        self.assertNotRegex(deploy, r"(?<!no-)--build\b")
        for variable in (
            "SCLIB_FRONTEND_IMAGE",
            "SCLIB_API_IMAGE",
            "SCLIB_INGESTION_IMAGE",
        ):
            self.assertIn(f"${{{variable}:?", compose)
        self.assertIn('readonly VERSION="v3.0.6"', installer)
        self.assertIn("EXPECTED_SHA256", installer)

    def test_production_api_command_survives_entrypoint_override(self) -> None:
        compose = (ROOT / "docker-compose.prod.yml").read_text()
        api_block = compose.split("\n  ingestion:", 1)[0]
        self.assertIn("entrypoint:", api_block)
        self.assertIn("command:", api_block)
        self.assertIn("- uvicorn", api_block)
        self.assertIn('- "8000"', api_block)

    @unittest.skipUnless(shutil.which("docker"), "Docker CLI is required for Compose resolution")
    def test_production_applications_do_not_inherit_infrastructure_passwords(self) -> None:
        # Exercise actual Compose env_file/override precedence with synthetic
        # credentials. No daemon, containers, database or real .env is used.
        with tempfile.TemporaryDirectory(prefix="sclib-compose-env-") as directory:
            env_file = Path(directory) / ".env"
            runtime_url = "postgresql+asyncpg://sclib_runtime:" + "application-only@postgres/sclib"
            env_file.write_text(
                "DB_PASSWORD=infrastructure-only\n"
                "GRAFANA_ADMIN_PASSWORD=monitoring-only\n"
                f"DATABASE_URL={runtime_url}\n"
            )
            environment = {key: value for key, value in os.environ.items()
                           if key in {"PATH", "HOME", "LANG", "LC_ALL", "TMPDIR", "SYSTEMROOT"}}
            environment.update({f"SCLIB_{name.upper()}_IMAGE":
                                f"ghcr.io/jackzh26/sclib-{name}@sha256:" + "1" * 64
                                for name in ("api", "frontend", "ingestion")})
            result = subprocess.run(
                ["docker", "compose", "--project-directory", directory,
                 "--env-file", str(env_file), "--profile", "observability", "--profile", "tools",
                 "-f", str(ROOT / "docker-compose.yml"),
                 "-f", str(ROOT / "docker-compose.prod.yml"), "config", "--format", "json"],
                env=environment, capture_output=True, text=True, timeout=30,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            services = json.loads(result.stdout)["services"]
            for name in ("api", "ingestion"):
                with self.subTest(service=name):
                    actual = services[name]["environment"]
                    self.assertEqual(actual["DB_PASSWORD"], "")
                    self.assertEqual(actual["GRAFANA_ADMIN_PASSWORD"], "")
                    self.assertEqual(actual["DATABASE_URL"], runtime_url)
            self.assertEqual(services["postgres"]["environment"]["POSTGRES_PASSWORD"], "infrastructure-only")
            self.assertEqual(services["grafana"]["environment"]["GF_SECURITY_ADMIN_PASSWORD"], "monitoring-only")
            self.assertEqual(services["migration"]["environment"]["DATABASE_URL"], "")
            self.assertIn("SCLIB_MIGRATION_DATABASE_URL_FILE", services["migration"]["environment"])

    def test_scheduled_jobs_reuse_last_signed_release_manifest(self) -> None:
        deploy = (WORKFLOW_DIR / "deploy.yml").read_text()
        ingest = (WORKFLOW_DIR / "ingest-daily.yml").read_text()
        cron = (ROOT / "scripts" / "cron_daily_ingest.sh").read_text()
        aggregate = (ROOT / "scripts" / "sclib-daily-aggregate.sh").read_text()

        self.assertIn(".env.release", deploy)
        self.assertIn('mv -f "$release_env"', deploy)
        self.assertIn("bash scripts/cron_daily_ingest.sh", ingest)
        for script in (cron, aggregate):
            self.assertIn(".env.release", script)
            self.assertIn("docker-compose.prod.yml", script)
        self.assertNotIn('source "${SCLIB_ROOT}/.env"', cron)

    def test_runtime_images_remove_build_package_managers(self) -> None:
        api = (ROOT / "api" / "Dockerfile").read_text()
        ingestion = (ROOT / "ingestion" / "Dockerfile").read_text()
        frontend = (ROOT / "frontend" / "Dockerfile").read_text()
        for dockerfile in (api, ingestion):
            self.assertIn("/usr/local/lib/python3.11/site-packages/pip*", dockerfile)
            self.assertIn("/usr/local/lib/python3.11/site-packages/setuptools*", dockerfile)
            self.assertIn("/root/.cache/uv", dockerfile)
            self.assertIn("/bin/uvx", dockerfile)
        self.assertIn("apk upgrade --no-cache", frontend)
        self.assertIn("/usr/local/lib/node_modules/npm", frontend)
        self.assertIn("/usr/local/bin/corepack", frontend)

    def test_deploy_connection_and_manual_redeploy_are_fail_closed(self) -> None:
        deploy = (WORKFLOW_DIR / "deploy.yml").read_text()
        for required in (
            "workflow_dispatch:",
            "release_run_id:",
            '.name == "Release images"',
            '.path == ".github/workflows/release-images.yml"',
            '.head_branch == "main"',
            '.conclusion == "success"',
            "secrets.VPS2_HOST",
            "secrets.VPS2_USER",
            "secrets.VPS2_DEPLOY_PATH",
            "secrets.VPS2_HOST_FINGERPRINT",
            "fingerprint:",
            "scripts/backup_postgres.sh",
            "steps.images.outputs.target_sha",
        ):
            self.assertIn(required, deploy)
        for prohibited in (
            "host: 72.62.251.29",
            "username: root",
            "git reset --hard",
            "StrictHostKeyChecking=no",
            "script_stop:",
        ):
            self.assertNotIn(prohibited, deploy)
        self.assertLess(
            deploy.index("scripts/backup_postgres.sh"),
            deploy.index('run --rm --no-deps migration'),
        )

    def test_ingest_uses_the_same_verified_ssh_connection(self) -> None:
        ingest = (WORKFLOW_DIR / "ingest-daily.yml").read_text()
        for required in (
            "secrets.VPS2_HOST",
            "secrets.VPS2_USER",
            "secrets.VPS2_DEPLOY_PATH",
            "secrets.VPS2_HOST_FINGERPRINT",
            "fingerprint:",
        ):
            self.assertIn(required, ingest)
        for prohibited in (
            "host: 72.62.251.29",
            "username: root",
            "StrictHostKeyChecking=no",
            "script_stop:",
        ):
            self.assertNotIn(prohibited, ingest)

    def test_ingest_retries_only_the_connection_preflight(self) -> None:
        ingest = (WORKFLOW_DIR / "ingest-daily.yml").read_text()
        for required in (
            "id: ssh_preflight_primary",
            "continue-on-error: true",
            "if: steps.ssh_preflight_primary.outcome == 'failure'",
            "Back off after transient SSH failure",
            "Retry VPS2 SSH connectivity",
            "timeout: 2m",
        ):
            self.assertIn(required, ingest)
        self.assertEqual(ingest.count('script: "true"'), 2)
        self.assertEqual(ingest.count("bash scripts/cron_daily_ingest.sh"), 1)

    def test_dependabot_tracks_every_package_ecosystem(self) -> None:
        dependabot = (ROOT / ".github" / "dependabot.yml").read_text()
        for ecosystem in ("github-actions", "pip", "npm", "docker-compose"):
            self.assertRegex(
                dependabot,
                rf'package-ecosystem:\s+["\']?{re.escape(ecosystem)}["\']?',
            )

    def test_observability_config_validation_matches_runtime_versions(self) -> None:
        compose = (ROOT / "docker-compose.yml").read_text()
        workflow = (WORKFLOW_DIR / "test.yml").read_text()
        for image, tool_image in (
            (
                "prom/prometheus:v3.13.1-distroless",
                "prom/prometheus:v3.13.1",
            ),
            (
                "quay.io/prometheus/alertmanager:v0.33.1",
                "quay.io/prometheus/alertmanager:v0.33.1",
            ),
        ):
            self.assertIn(image, compose)
            self.assertIn(tool_image, workflow)
        self.assertIn("grafana/grafana:13.1.0", compose)


if __name__ == "__main__":
    unittest.main()
