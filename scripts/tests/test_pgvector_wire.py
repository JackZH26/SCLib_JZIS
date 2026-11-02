import hashlib
import struct

import pytest

from scripts.pgvector_wire import MAGIC, decode_copy, projection_copy,content_projection_copy


def frame(rows):
    payload = bytearray(MAGIC + b"\0" * 8)
    for row in rows:
        payload.extend(struct.pack("!h", len(row)))
        for value in row:
            payload.extend(struct.pack("!i", -1 if value is None else len(value)))
            if value is not None:payload.extend(value)
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


@pytest.mark.parametrize('year',[None,1,1986,2026,9999])
def test_content_copy_retains_exact_year_and_original_vector_bytes(year):
    row=source();encoded=None if year is None else struct.pack('!i',year)
    payload,inventory=content_projection_copy(frame([row+[encoded]]))
    (result,)=decode_copy(payload,fields=7,nullable_fields=(6,))
    assert result[-1]==encoded and result[:5]==row[:5]
    assert result[5]==struct.pack('!hh',768,0)+row[5]
    old_payload,old_inventory=projection_copy(frame([row]))
    assert inventory==old_inventory and decode_copy(old_payload,fields=6)[0]==result[:-1]


@pytest.mark.parametrize('year',[struct.pack('!i',0),struct.pack('!i',-1),struct.pack('!i',10000),b'1',b'\0'*8])
def test_content_copy_rejects_invalid_year_instead_of_reinterpreting_as_unknown(year):
    with pytest.raises(ValueError,match='year'):content_projection_copy(frame([source()+[year]]))


@pytest.mark.parametrize('index',range(7))
def test_only_the_declared_year_can_be_null(index):
    row=source()+[None];row[index]=None
    with pytest.raises(ValueError):content_projection_copy(frame([row]))


def test_api_and_owned_host_converters_ship_identical_contract_bytes():
    from pathlib import Path
    root=Path(__file__).resolve().parents[2]
    assert (root/'scripts/pgvector_wire.py').read_bytes()==(root/'api/services/pgvector_wire.py').read_bytes()
