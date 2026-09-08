"""Bounded, offline parsing of QE matdyn input and complete ``flfrq`` bytes.

This is an observed-file preflight, not a run importer or a scientific admission.
The native format/unit convention is documented by QEF/q-e commit
770a0b2d12928a67048e2f3da8d10d057e52179e, PHonon/PH/matdyn.f90.
Historical reference outputs use three q columns; current code writes four.
Neither layout establishes which executable produced the supplied bytes.
"""

from __future__ import annotations

import hashlib
import math
import re
from decimal import Decimal, localcontext

VERSION = "qe-matdyn-import/1.0.0"
ADAPTER_ID = "qe-matdyn-flfrq"
MAX_INPUT_BYTES = 256 * 1024
MAX_FREQUENCY_BYTES = 4 * 1024 * 1024
MAX_MODES = 768
MAX_QPOINTS = 1000
MAX_TOTAL_MODES = 200_000
MAX_PHYSICAL_LINES = 50_000
CM_INVERSE_TO_THZ = "0.0299792458"
REFERENCE_COMMIT = "770a0b2d12928a67048e2f3da8d10d057e52179e"
_NUMBER = r"[+-]?(?:[0-9]+(?:\.[0-9]*)?|\.[0-9]+)(?:[eEdD][+-]?[0-9]+)?"
_NUMBER_RE = re.compile(_NUMBER)
_ASSIGNMENT = re.compile(r"([A-Za-z][A-Za-z0-9_]*(?:\(\s*[0-9]+\s*\))?)\s*=\s*")
_HEADER = re.compile(r"\s*&plot\s+nbnd\s*=\s*([0-9]+)\s*,\s*nks\s*=\s*([0-9]+)\s*/\s*", re.I)
_SUPPORTED = {"asr", "flfrc", "flfrq", "q_in_band_form", "q_in_cryst_coord", "dos", "la2f", "loto_2d"}
_BOOL_KEYS = {"q_in_band_form", "q_in_cryst_coord", "dos", "la2f", "loto_2d"}
_ASR = {"no", "simple", "crystal", "one-dim", "zero-dim", "all"}


class MatdynImportError(ValueError):
    """Static reason code only; never source text, paths or provider errors."""


def _fail(code: str):
    raise MatdynImportError(code)


class _Document:
    def __init__(self, raw: bytes, limit: int):
        if type(raw) is not bytes or not 0 < len(raw) <= limit:
            _fail("invalid_file_size_or_type")
        # Count native physical delimiters before decoding or hydrating any
        # per-line objects. A bounded byte file can otherwise contain millions
        # of empty records and exhaust memory in splitlines/list construction.
        physical_lines = raw.count(b"\n") + raw.count(b"\r") - raw.count(b"\r\n")
        if not raw.endswith((b"\r", b"\n")):
            physical_lines += 1
        if physical_lines > MAX_PHYSICAL_LINES:
            _fail("physical_line_limit_exceeded")
        try:
            self.text = raw.decode("utf-8", errors="strict")
        except UnicodeDecodeError:
            _fail("invalid_utf8")
        if any(ord(char) < 32 and char not in "\t\r\n" for char in self.text):
            _fail("unsupported_control_character")
        if any(char in self.text for char in ("\x85", "\u2028", "\u2029")):
            _fail("unsupported_unicode_line_separator")
        self.raw = raw
        self.line_starts = [0]
        self.byte_starts = [0]
        self.lines = []
        start = 0
        byte_start = 0
        for number, line in enumerate(self.text.splitlines(keepends=True), 1):
            if len(line) > 8192:
                _fail("file_line_limit_exceeded")
            self.lines.append((number, start, line.rstrip("\r\n")))
            start += len(line)
            byte_start += len(line.encode("utf-8"))
            self.line_starts.append(start)
            self.byte_starts.append(byte_start)

    def locator(self, start: int, end: int) -> dict:
        from bisect import bisect_right

        line = bisect_right(self.line_starts, start) - 1
        line_start = self.line_starts[line]
        first = self.byte_starts[line] + len(self.text[line_start:start].encode("utf-8"))
        return {"line": line + 1, "start_byte": first,
                "end_byte": first + len(self.text[start:end].encode("utf-8"))}


def _number(raw: str) -> float:
    if len(raw) > 64 or _NUMBER_RE.fullmatch(raw) is None:
        _fail("invalid_numeric_token")
    exponent = re.split("[eEdD]", raw)
    if len(exponent) == 2 and len(exponent[1].lstrip("+-")) > 4:
        _fail("numeric_exponent_limit_exceeded")
    try:
        value = float(raw.replace("D", "e").replace("d", "e"))
    except (ValueError, OverflowError):
        _fail("invalid_numeric_token")
    if not math.isfinite(value):
        _fail("nonfinite_numeric_token")
    # Reject silent float underflow; signed textual zero is still retained.
    if value == 0 and Decimal(raw.replace("D", "e").replace("d", "e")) != 0:
        _fail("numeric_underflow")
    return value


def _tokens(doc: _Document, line: tuple, *, comments=False) -> list[dict]:
    _, offset, text = line
    if comments:
        text = text.split("!", 1)[0]
    tokens = []
    for match in re.finditer(r"\S+", text):
        raw = match.group()
        tokens.append({"raw_text": raw, "value": _number(raw),
                       "locator": doc.locator(offset + match.start(), offset + match.end())})
    return tokens


def _native_tokens(doc: _Document, line: tuple, *, count: int, prefix=0) -> list[dict]:
    """Preserve Fortran fixed-width numbers even when adjacent fields touch."""
    _, offset, text = line
    if len(text) == prefix + count * 10 and not text[:prefix].strip():
        result = []
        for index in range(count):
            start = prefix + index * 10
            field = text[start:start + 10]
            raw = field.strip()
            begin = offset + start + len(field) - len(field.lstrip())
            result.append({"raw_text": raw, "value": _number(raw),
                           "locator": doc.locator(begin, begin + len(raw))})
        return result
    return _tokens(doc, line)


def _mask_comments(text: str) -> str:
    chars = list(text)
    quote = None
    i = 0
    while i < len(chars):
        char = chars[i]
        if quote:
            if char == quote:
                if i + 1 < len(chars) and chars[i + 1] == quote:
                    i += 2
                    continue
                quote = None
        elif char in "'\"":
            quote = char
        elif char == "!":
            while i < len(chars) and chars[i] not in "\r\n":
                chars[i] = " "
                i += 1
            continue
        i += 1
    if quote:
        _fail("unterminated_input_string")
    return "".join(chars)


def _input(doc: _Document) -> tuple[dict, list[str], list[dict] | None]:
    masked = _mask_comments(doc.text)
    header = re.match(r"\s*&input\b", masked, re.I)
    if header is None:
        _fail("invalid_input_namelist")
    cursor = header.end()
    values = {}
    assignments = []
    while True:
        while cursor < len(masked) and (masked[cursor].isspace() or masked[cursor] == ","):
            cursor += 1
        if cursor >= len(masked):
            _fail("unterminated_input_namelist")
        if masked[cursor] == "/":
            cursor += 1
            break
        key_match = _ASSIGNMENT.match(masked, cursor)
        if key_match is None or len(assignments) >= 64:
            _fail("unsupported_input_namelist_syntax")
        name = re.sub(r"\s", "", key_match.group(1)).lower()
        if name in values:
            _fail("duplicate_input_assignment")
        cursor = start = key_match.end()
        if cursor < len(masked) and masked[cursor] in "'\"":
            quote = masked[cursor]
            cursor += 1
            parts = []
            while cursor < len(masked):
                if masked[cursor] == quote:
                    if cursor + 1 < len(masked) and masked[cursor + 1] == quote:
                        parts.append(quote)
                        cursor += 2
                        continue
                    cursor += 1
                    break
                parts.append(masked[cursor])
                cursor += 1
            else:
                _fail("unterminated_input_string")
            value = "".join(parts)
            if not value or len(value) > 256 or "\n" in value or "\r" in value:
                _fail("invalid_input_string")
        else:
            scalar = re.match(r"\.true\.|\.false\.|" + _NUMBER, masked[cursor:], re.I)
            if scalar is None:
                _fail("unsupported_input_value")
            raw = scalar.group()
            cursor += len(raw)
            value = raw.lower() == ".true." if raw.startswith(".") and raw.endswith(".") else _number(raw)
        if cursor < len(masked) and not (masked[cursor].isspace() or masked[cursor] in ",/"):
            _fail("invalid_input_value_boundary")
        values[name] = value
        assignments.append({"name": name, "raw_value": doc.text[start:cursor], "value": value,
                            "locator": doc.locator(start, cursor)})

    reasons = []
    unsupported = []
    for name, value in values.items():
        mass = re.fullmatch(r"amass\(([1-9][0-9]{0,2})\)", name)
        if mass:
            if type(value) is not float or value <= 0:
                _fail("invalid_atomic_mass_setting")
        elif name not in _SUPPORTED:
            unsupported.append(name)
        elif name in _BOOL_KEYS and type(value) is not bool:
            _fail("invalid_boolean_setting")
        elif name in {"asr", "flfrc", "flfrq"} and type(value) is not str:
            _fail("invalid_string_setting")
    if unsupported:
        reasons.append("unsupported_input_setting")
    if values.get("asr", "no").lower() not in _ASR:
        reasons.append("unsupported_asr_setting")
    if "flfrc" not in values or "flfrq" not in values:
        reasons.append("missing_explicit_file_reference")
    if values.get("loto_2d", False):
        reasons.append("unsupported_two_dimensional_treatment")
    if values.get("la2f", False):
        reasons.append("electron_phonon_outputs_not_imported")
    crystal = values.get("q_in_cryst_coord", False)
    if crystal:
        reasons.append("reciprocal_cell_transform_unavailable")

    body = []
    for number, start, line in doc.lines:
        end = start + len(line)
        if end <= cursor:
            continue
        content_start = max(cursor, start)
        content = masked[content_start:end]
        if content.strip():
            body.append((number, content_start, content))
    cards = []
    expected = None
    declared_count = None
    band = values.get("q_in_band_form", False)
    if values.get("dos", False):
        reasons.append("dos_grid_not_supported")
        if body:
            _fail("unexpected_input_after_dos_namelist")
    else:
        if not body or re.fullmatch(r"\s*[0-9]{1,4}\s*", body[0][2]) is None:
            _fail("invalid_declared_qpoint_count")
        declared_count = int(body[0][2])
        if not 1 <= declared_count <= MAX_QPOINTS or len(body) != declared_count + 1:
            _fail("input_qpoint_count_mismatch")
        symbolic = False
        for index, line in enumerate(body[1:], 1):
            number, offset, text = line
            pieces = text.split()
            if band and len(pieces) == 2 and re.fullmatch(r"[A-Za-z][A-Za-z0-9_]{0,15}", pieces[0]):
                if re.fullmatch(r"[0-9]{1,4}", pieces[1]) is None:
                    _fail("invalid_band_segment_count")
                symbolic = True
                count = int(pieces[1])
                components = None
            else:
                components = _tokens(doc, line)
                if len(components) not in ({4} if band else {3, 4}):
                    _fail("invalid_input_qpoint_record")
                count = None
                if band:
                    if re.fullmatch(r"[0-9]{1,4}", components[3]["raw_text"]) is None:
                        _fail("invalid_band_segment_count")
                    count = int(components[3]["raw_text"])
            if count is not None and count > MAX_QPOINTS:
                _fail("band_segment_limit_exceeded")
            cards.append({"index": index, "raw_text": doc.text[offset:offset + len(text)],
                          "locator": doc.locator(offset, offset + len(text)),
                          "components": components, "band_segment_count": count,
                          "fourth_column_semantics": "segment_count" if band else "ignored_by_native_q_reader" if len(pieces) == 4 else None})
        if symbolic:
            reasons.append("symbolic_qpoint_transform_unavailable")
        if band:
            declared_output_count = sum(max(1, card["band_segment_count"]) for card in cards[:-1]) + 1
            if not 1 <= declared_output_count <= MAX_QPOINTS:
                _fail("expanded_qpoint_limit_exceeded")
            if any(card["band_segment_count"] == 0 for card in cards[:-1]):
                reasons.append("zero_length_band_segment_not_supported")
            if not crystal and not symbolic and "zero_length_band_segment_not_supported" not in reasons:
                expected = []
                for left, right in zip(cards, cards[1:], strict=False):
                    count = left["band_segment_count"]
                    for step in range(count):
                        expected.append([left["components"][axis]["value"] +
                                         (right["components"][axis]["value"] - left["components"][axis]["value"]) * step / count
                                         for axis in range(3)])
                expected.append([item["value"] for item in cards[-1]["components"][:3]])
        else:
            declared_output_count = declared_count
            if not crystal:
                expected = [[item["value"] for item in card["components"][:3]] for card in cards]
        if not 1 <= declared_output_count <= MAX_QPOINTS:
            _fail("expanded_qpoint_limit_exceeded")

    observations = {
        "assignments": assignments, "unsupported_settings": sorted(unsupported),
        "declared_flfrc": values.get("flfrc"), "declared_flfrq": values.get("flfrq"),
        "asr": {"value": values.get("asr", "no"), "basis": "explicit" if "asr" in values else "documented_default_not_observed"},
        "q_in_band_form": {"value": band, "basis": "explicit" if "q_in_band_form" in values else "documented_default_not_observed"},
        "q_in_cryst_coord": {"value": crystal, "basis": "explicit" if "q_in_cryst_coord" in values else "documented_default_not_observed"},
        "declared_qpoint_card_count": declared_count,
        "expected_output_qpoint_count": None if values.get("dos", False) else declared_output_count,
        "qpoint_cards": cards,
    }
    return observations, reasons, expected


def _spectrum(doc: _Document) -> dict:
    lines = [line for line in doc.lines if line[2].strip()]
    if not lines or len(lines[0][2]) > 160:
        _fail("invalid_frequency_header")
    header = _HEADER.fullmatch(lines[0][2])
    if header is None:
        _fail("invalid_frequency_header")
    if any(len(group) > 4 for group in header.groups()):
        _fail("frequency_dimension_limit_exceeded")
    modes, count = map(int, header.groups())
    if not 1 <= modes <= MAX_MODES or modes % 3 or not 1 <= count <= MAX_QPOINTS or modes * count > MAX_TOTAL_MODES:
        _fail("frequency_dimension_limit_exceeded")
    cursor = 1
    qpoints = []
    layouts = set()
    for index in range(1, count + 1):
        if cursor >= len(lines):
            _fail("incomplete_frequency_records")
        q_line = lines[cursor]
        q = _native_tokens(doc, q_line, count=4 if len(q_line[2]) == 50 else 3, prefix=10)
        cursor += 1
        if len(q) not in {3, 4}:
            _fail("invalid_frequency_qpoint")
        layouts.add("xyz" if len(q) == 3 else "xyz_weight")
        frequencies = []
        while len(frequencies) < modes:
            if cursor >= len(lines):
                _fail("incomplete_frequency_records")
            values = _native_tokens(doc, lines[cursor], count=min(6, modes - len(frequencies)))
            cursor += 1
            # Native output wraps every six mode values. Accept fewer modes only
            # in the final line; this prevents a missing line consuming q data.
            if len(values) != min(6, modes - len(frequencies)):
                _fail("invalid_frequency_mode_record")
            for value in values:
                value.update({"mode_index": len(frequencies) + 1, "unit": "cm^-1"})
                frequencies.append(value)
        qpoints.append({"index": index, "coordinates": q[:3], "weight": q[3] if len(q) == 4 else None,
                        "frequencies": frequencies})
    if cursor != len(lines):
        _fail("unexpected_frequency_trailing_records")
    if len(layouts) != 1:
        _fail("inconsistent_frequency_qpoint_layout")
    seen = set()
    repeated = []
    for point in qpoints:
        key = tuple(item["value"] for item in point["coordinates"])
        if key in seen:
            repeated.append(point["index"])
        seen.add(key)
    return {"mode_count": modes, "qpoint_count": count, "q_record_layout": next(iter(layouts)),
            "q_coordinate_basis": "cartesian_2pi_over_alat_native_format_convention",
            "frequency_unit": "cm^-1", "frequency_sign_convention": "negative_means_imaginary_mode_not_negative_energy",
            "repeated_qpoint_indices": repeated, "qpoints": qpoints}


def parse_matdyn(*, input_bytes: bytes, frequency_bytes: bytes) -> dict:
    """Return a deterministic complete-byte diagnostic; never execute or persist."""
    input_doc = _Document(input_bytes, MAX_INPUT_BYTES)
    frequency_doc = _Document(frequency_bytes, MAX_FREQUENCY_BYTES)
    observations, reasons, expected = _input(input_doc)
    spectrum = _spectrum(frequency_doc)
    expected_count = observations["expected_output_qpoint_count"]
    if expected_count is not None and expected_count != spectrum["qpoint_count"]:
        _fail("input_output_qpoint_count_mismatch")
    if expected is not None:
        for wanted, point in zip(expected, spectrum["qpoints"], strict=True):
            for value, actual in zip(wanted, point["coordinates"], strict=True):
                if not math.isfinite(value) or abs(value - actual["value"]) > 0.50001e-6:
                    _fail("input_output_qpoint_coordinate_mismatch")
    else:
        reasons.append("input_output_qpoint_coordinates_unverified")
    minimum = None
    minimum_decimal = None
    minimum_q = None
    ties = 0
    negative_modes = 0
    for point in spectrum["qpoints"]:
        for value in point["frequencies"]:
            decimal = Decimal(value["raw_text"].replace("D", "e").replace("d", "e"))
            if decimal < 0:
                negative_modes += 1
            if minimum is None or decimal < minimum_decimal:
                minimum, minimum_q, ties = value, point["index"], 1
                minimum_decimal = decimal
            elif decimal == minimum_decimal:
                ties += 1
    with localcontext() as context:
        context.prec = 100
        normalized = minimum_decimal * Decimal(CM_INVERSE_TO_THZ)
    if not math.isfinite(float(normalized)) or float(normalized) == 0 and normalized != 0:
        _fail("frequency_conversion_not_representable")
    candidate = {
        "property_key": "phonon_min_frequency", "candidate_kind": "parsed_sampled_frequency_summary",
        "value": float(normalized), "unit": "THz", "value_decimal": str(normalized),
        "source_value": minimum["value"], "source_raw_text": minimum["raw_text"], "source_unit": "cm^-1",
        "source_locator": minimum["locator"], "qpoint_index": minimum_q, "mode_index": minimum["mode_index"],
        "minimum_tie_count": ties, "negative_mode_observation_count": negative_modes,
        "conversion": {"version": "signed-wavenumber-to-cyclic-thz/1.0.0", "factor": CM_INVERSE_TO_THZ,
                       "basis": "exact_c_m_per_s_times_100_divided_by_1e12"},
        "scope": "minimum_over_complete_declared_sampled_qpoint_records_only",
        "precision_basis": "rounded_native_frequency_file_not_measurement_uncertainty",
        "state_binding": "unresolved", "structure_binding": "unresolved", "run_binding": "unresolved",
        "disposition": "quarantined" if reasons else "pending_context_and_review",
    }
    return {
        "version": VERSION, "adapter_id": ADAPTER_ID,
        "status": "quarantined" if reasons else "parsed", "reason_codes": sorted(set(reasons)),
        "files": {"input_sha256": hashlib.sha256(input_bytes).hexdigest(),
                  "frequency_sha256": hashlib.sha256(frequency_bytes).hexdigest()},
        "format_reference": {"repository": "QEF/q-e", "commit": REFERENCE_COMMIT,
                             "producer_version": None, "unit_basis": "documented_flfrq_format_not_self_described"},
        "input_observations": observations, "spectrum": spectrum, "property_candidates": [candidate],
        "limitations": ["no_full_brillouin_zone_stability_claim", "no_source_executable_version_attestation",
                        "no_execution_or_convergence_attestation", "no_pressure_temperature_or_structure_inference",
                        "no_harmonic_or_anharmonic_treatment_inference", "no_calculation_cost_inference"],
        "authority": {"scientific_accepted": False, "ml_training_approved": False, "execution_attested": False},
    }
