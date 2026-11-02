import hashlib
import struct

import pytest

from scripts.pgvector_wire import MAGIC, decode_copy, projection_copy


def frame(rows):
    payload = bytearray(MAGIC + b"\0" * 8)
    for row in rows:
        payload.extend(struct.pack("!h", len(row)))
        for value in row:
            payload.extend(struct.pack("!i", len(value)))
            payload.extend(value)
    return bytes(payload + struct.pack("!h", -1))


def source(identifier=b"ig62_example", raw=None):
    raw = (
        raw
        if raw is not None
        else struct.pack("!768f", 1.0000001192092896, *([0.0] * 767))
    )
    return [
        identifier,
        b"arxiv:example",
        b"a" * 64,
        hashlib.sha256(raw).hexdigest().encode(),
        b"b" * 64,
        raw,
        b"\x01",
    ]


def test_import_retains_every_network_order_float32_byte():
    row = source()
    payload, inventory = projection_copy(frame([row]))
    (result,) = decode_copy(payload, fields=6)
    assert result[:5] == row[:5]
    assert result[5] == struct.pack("!hh", 768, 0) + row[5]
    assert inventory == [(row[0].decode(), row[2].decode(), row[3].decode())]


@pytest.mark.parametrize("bits", [0x7FC00000, 0x7F800000, 0xFF800000, 0x80000000])
def test_rejects_nonfinite_and_negative_zero_even_with_matching_hash(bits):
    raw = struct.pack("!I", bits) + struct.pack("!767f", 1.0, *([0.0] * 766))
    with pytest.raises(ValueError, match="Noncanonical"):
        projection_copy(frame([source(raw=raw)]))


@pytest.mark.parametrize(
    "mutation", ["content_binding", "hash", "dimension", "zero", "duplicate", "order"]
)
def test_rejects_invalid_source_or_inventory(mutation):
    row = source()
    rows = [row]
    if mutation == "content_binding":
        row[-1] = b"\x00"
    elif mutation == "hash":
        row[3] = b"f" * 64
    elif mutation == "dimension":
        row[5] = row[5][4:]
    elif mutation == "zero":
        row[5] = b"\0" * 3072
        row[3] = hashlib.sha256(row[5]).hexdigest().encode()
    elif mutation == "duplicate":
        rows.append(source())
    else:
        rows = [source(b"z"), source(b"a")]
    with pytest.raises(ValueError):
        projection_copy(frame(rows))


@pytest.mark.parametrize(
    "payload",
    [
        b"",
        MAGIC,
        frame([]) + b"extra",
        frame([source()])[:-1],
        MAGIC + struct.pack("!ii", 1, 0) + b"\xff\xff",
    ],
)
def test_rejects_truncated_or_extended_copy_frames(payload):
    with pytest.raises(ValueError):
        decode_copy(payload, fields=7)
