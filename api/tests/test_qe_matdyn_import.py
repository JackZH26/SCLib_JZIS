"""Strict synthetic format cases; genuine upstream packages have separate canaries."""

import hashlib
import json

import pytest

from services.qe_matdyn_import import (
    MAX_FREQUENCY_BYTES,
    MAX_INPUT_BYTES,
    MAX_PHYSICAL_LINES,
    MatdynImportError,
    parse_matdyn,
)


def input_file(*, settings="", cards="1\n0 0 0", comment=""):
    return (comment + " &input\n asr='simple', flfrc='synthetic.fc', flfrq='synthetic.freq', " +
            settings + "\n /\n" + cards + "\n").encode()


def frequencies(*, modes=3, points=None, weighted=False):
    points = points or [([0, 0, 0], [-1, 0, 2])]
    lines = [f" &plot nbnd={modes}, nks={len(points)} /"]
    for q, values in points:
        lines.append("          " + "".join(f"{x:10.6f}" for x in [*q, *([0.0] if weighted else [])]))
        for i in range(0, len(values), 6):
            lines.append("".join(f"{x:10.4f}" for x in values[i:i + 6]))
    return ("\n".join(lines) + "\n").encode()


def parse(input_bytes=None, frequency_bytes=None):
    return parse_matdyn(input_bytes=input_file() if input_bytes is None else input_bytes,
                        frequency_bytes=frequencies() if frequency_bytes is None else frequency_bytes)


def assert_code(code, **kwargs):
    with pytest.raises(MatdynImportError) as caught:
        parse(**kwargs)
    assert str(caught.value) == code


def test_complete_input_and_native_output_are_deterministic_pending_not_admitted():
    inp, freq = input_file(), frequencies()
    result = parse(inp, freq)
    assert parse(inp, freq) == result
    assert result["status"] == "parsed"
    assert result["reason_codes"] == []
    assert result["files"] == {"input_sha256": hashlib.sha256(inp).hexdigest(),
                               "frequency_sha256": hashlib.sha256(freq).hexdigest()}
    assert set(result["authority"].values()) == {False}
    assert result["format_reference"]["producer_version"] is None
    assert result["spectrum"]["q_record_layout"] == "xyz"
    candidate = result["property_candidates"][0]
    assert candidate["value_decimal"] == "-0.02997924580000"
    assert candidate["value"] == -0.0299792458
    assert candidate["source_unit"] == "cm^-1"
    assert candidate["unit"] == "THz"
    assert candidate["disposition"] == "pending_context_and_review"
    assert candidate["negative_mode_observation_count"] == 1
    assert candidate["state_binding"] == candidate["structure_binding"] == candidate["run_binding"] == "unresolved"
    assert "no_full_brillouin_zone_stability_claim" in result["limitations"]
    assert "no_calculation_cost_inference" in result["limitations"]
    json.dumps(result, allow_nan=False)


def test_complete_wrapped_modes_and_new_four_column_q_layout():
    freq = frequencies(modes=9, weighted=True, points=[([0, 0, 0], list(range(9)))])
    result = parse(frequency_bytes=freq)
    assert result["spectrum"]["mode_count"] == 9
    assert result["spectrum"]["q_record_layout"] == "xyz_weight"
    assert [value["value"] for value in result["spectrum"]["qpoints"][0]["frequencies"]] == list(range(9))


def test_signed_imaginary_frequencies_are_not_absolute_values_or_negative_energy():
    result = parse(frequency_bytes=frequencies(points=[([0, 0, 0], [-15, -2, 1])]))
    candidate = result["property_candidates"][0]
    assert candidate["value"] == pytest.approx(-15 * 0.0299792458)
    assert candidate["negative_mode_observation_count"] == 2


def test_signed_zero_raw_text_and_tied_minima_preserved():
    result = parse(frequency_bytes=frequencies(points=[([0, 0, 0], [-0.0, 0.0, 1])]))
    candidate = result["property_candidates"][0]
    assert candidate["source_raw_text"] == "-0.0000"
    assert candidate["minimum_tie_count"] == 2
    assert candidate["negative_mode_observation_count"] == 0


def test_fixed_width_touching_fields_are_not_lost():
    result = parse(frequency_bytes=frequencies(points=[([0, 0, 0], [12345, -1234, -1234])]))
    assert result["property_candidates"][0]["source_value"] == -1234
    assert result["property_candidates"][0]["minimum_tie_count"] == 2


def test_every_number_locator_slices_exact_original_utf8_bytes():
    inp = input_file(comment="! 合成 fixture\r\n")
    freq = frequencies()
    result = parse(inp, freq)
    for assignment in result["input_observations"]["assignments"]:
        span = assignment["locator"]
        assert inp[span["start_byte"]:span["end_byte"]].decode() == assignment["raw_value"]
    for point in result["spectrum"]["qpoints"]:
        for value in [*point["coordinates"], *point["frequencies"]]:
            span = value["locator"]
            assert freq[span["start_byte"]:span["end_byte"]].decode() == value["raw_text"]
            assert freq[:span["start_byte"]].count(b"\n") + 1 == span["line"]


def test_cartesian_band_expansion_includes_endpoint_and_repeated_qpoints():
    inp = input_file(settings="q_in_band_form=.true.", cards="3\n0 0 0 2\n1 0 0 2\n0 0 0 1")
    freq = frequencies(points=[([x, 0, 0], [0, 1, 2]) for x in [0, 0.5, 1, 0.5, 0]])
    result = parse(inp, freq)
    assert result["status"] == "parsed"
    assert result["spectrum"]["repeated_qpoint_indices"] == [4, 5]
    assert result["input_observations"]["expected_output_qpoint_count"] == 5


def test_native_nonband_fourth_input_scalar_is_retained_not_called_weight():
    result = parse(input_bytes=input_file(cards="1\n0 0 0 7.0"))
    card = result["input_observations"]["qpoint_cards"][0]
    assert card["fourth_column_semantics"] == "ignored_by_native_q_reader"
    assert card["components"][3]["value"] == 7


@pytest.mark.parametrize(("setting", "reason"), [
    ("loto_2d=.true.", "unsupported_two_dimensional_treatment"),
    ("q_in_cryst_coord=.true.", "reciprocal_cell_transform_unavailable"),
    ("la2F=.true.", "electron_phonon_outputs_not_imported"),
    ("read_lr=.true.", "unsupported_input_setting"),
    ("asr_extra='unknown'", "unsupported_input_setting"),
])
def test_unsupported_semantics_quarantine_complete_records_without_silent_discard(setting, reason):
    result = parse(input_bytes=input_file(settings=setting))
    assert result["status"] == "quarantined"
    assert reason in result["reason_codes"]
    assert len(result["spectrum"]["qpoints"][0]["frequencies"]) == 3
    assert result["property_candidates"][0]["disposition"] == "quarantined"


def test_symbolic_band_vertices_are_preserved_but_not_guessed():
    result = parse(input_bytes=input_file(settings="q_in_band_form=.true.", cards="1\ngG 1"))
    assert result["status"] == "quarantined"
    assert "symbolic_qpoint_transform_unavailable" in result["reason_codes"]
    assert result["input_observations"]["qpoint_cards"][0]["components"] is None


def test_dos_mode_is_quarantined_and_not_reinterpreted_as_explicit_q_sampling():
    result = parse(input_bytes=input_file(settings="dos=.true., nk1=2, nk2=2,nk3=2", cards=""))
    assert "dos_grid_not_supported" in result["reason_codes"]
    assert result["input_observations"]["expected_output_qpoint_count"] is None


def test_fortran_d_exponents_comments_and_doubled_quote_strings():
    inp = input_file(settings="amass(1)=2.698d1, custom='a!b''c', ! retained comment\n", cards="1\n0D0 0D0 0D0")
    result = parse(inp)
    items = {item["name"]: item for item in result["input_observations"]["assignments"]}
    assert items["amass(1)"]["value"] == 26.98
    assert items["custom"]["value"] == "a!b'c"
    assert result["status"] == "quarantined"


@pytest.mark.parametrize("value", [None, "text", bytearray(b"text"), b"", b"\xff", b"\0"])
def test_invalid_input_type_encoding_control(value):
    with pytest.raises(MatdynImportError):
        parse(input_bytes=value if value is not None else "not bytes")


@pytest.mark.parametrize(("target", "size"), [("input_bytes", MAX_INPUT_BYTES), ("frequency_bytes", MAX_FREQUENCY_BYTES)])
def test_file_bounds(target, size):
    assert_code("invalid_file_size_or_type", **{target: b" " * (size + 1)})


@pytest.mark.parametrize(("bad", "code"), [
    (b"# E (eV) dos(E)\n0 1\n", "invalid_frequency_header"),
    (b" &plot nbnd=2, nks=1 /\n", "frequency_dimension_limit_exceeded"),
    (b" &plot nbnd=771, nks=1 /\n", "frequency_dimension_limit_exceeded"),
    (b" &plot nbnd=768, nks=1000 /\n", "frequency_dimension_limit_exceeded"),
    (b" &plot nbnd=3, nks=1001 /\n", "frequency_dimension_limit_exceeded"),
    (b" &plot nbnd=3, nks=1 /\n0 0 0\n", "incomplete_frequency_records"),
    (b" &plot nbnd=3, nks=1 /\n0 0 0\n1 2\n", "invalid_frequency_mode_record"),
    (b" &plot nbnd=3, nks=1 /\n0 0 0\n1 2 3 4\n", "invalid_frequency_mode_record"),
    (b" &plot nbnd=3, nks=1 /\n0 0 0\nNaN 0 0\n", "invalid_numeric_token"),
    (b" &plot nbnd=3, nks=1 /\n0 0 0\n1e999 0 0\n", "nonfinite_numeric_token"),
    (b" &plot nbnd=3, nks=1 /\n0 0 0\n1e-999 0 0\n", "numeric_underflow"),
    (b" &plot nbnd=3, nks=1 /\n0 0 0\n1e-999999999999999999 0 0\n", "numeric_exponent_limit_exceeded"),
    (b" &plot nbnd=3, nks=1 /\n0 0 0\n1i 0 0\n", "invalid_numeric_token"),
])
def test_invalid_or_incomplete_output_rejected_not_empty_success(bad, code):
    assert_code(code, frequency_bytes=bad)


def test_unexpected_output_is_not_ignored():
    assert_code("unexpected_frequency_trailing_records", frequency_bytes=frequencies() + b"0 0 0\n")


def test_count_and_coordinate_binding_fail_closed():
    assert_code("input_output_qpoint_count_mismatch", input_bytes=input_file(cards="2\n0 0 0\n0 0 0"))
    assert_code("input_output_qpoint_coordinate_mismatch", input_bytes=input_file(cards="1\n0.1 0 0"))
    parse(input_bytes=input_file(cards="1\n0.0000004 0 0"))
    assert_code("input_output_qpoint_coordinate_mismatch", input_bytes=input_file(cards="1\n0.0000006 0 0"))


@pytest.mark.parametrize(("settings", "code"), [
    ("dos=1", "invalid_boolean_setting"),
    ("flfrq='other'", "duplicate_input_assignment"),
    ("amass(1)=.true.", "invalid_atomic_mass_setting"),
    ("amass(1)=-1", "invalid_atomic_mass_setting"),
    ("custom=1evil", "invalid_input_value_boundary"),
    ("custom=(1,2)", "unsupported_input_value"),
])
def test_malformed_namelist_values_are_not_coerced(settings, code):
    assert_code(code, input_bytes=input_file(settings=settings))


def test_missing_frequency_line_cannot_consume_following_q_record():
    data = b" &plot nbnd=6,nks=2 /\n0 0 0\n0 0 0\n1 2 3 4 5 6\n"
    assert_code("invalid_frequency_mode_record", input_bytes=input_file(cards="2\n0 0 0\n0 0 0"), frequency_bytes=data)


def test_mixed_q_layouts_rejected():
    data = b" &plot nbnd=3,nks=2 /\n0 0 0\n1 2 3\n0 0 0 0\n1 2 3\n"
    assert_code("inconsistent_frequency_qpoint_layout", input_bytes=input_file(cards="2\n0 0 0\n0 0 0"), frequency_bytes=data)


def test_expanded_band_bound_is_checked_before_expansion():
    inp = input_file(settings="q_in_band_form=.true.", cards="3\n0 0 0 1000\n1 0 0 1000\n0 0 0 1")
    assert_code("expanded_qpoint_limit_exceeded", input_bytes=inp)


def test_normalized_frequency_underflow_is_not_silent_zero():
    freq = b" &plot nbnd=3,nks=1 /\n0 0 0\n1e-323 1 2\n"
    assert_code("frequency_conversion_not_representable", frequency_bytes=freq)


@pytest.mark.parametrize("raw", ["١.٠", "１.０", "−1.0"])
def test_non_fortran_unicode_numeric_spelling_rejected(raw):
    freq = (" &plot nbnd=3,nks=1 /\n0 0 0\n" + raw + " 1 2\n").encode()
    assert_code("invalid_numeric_token", frequency_bytes=freq)


@pytest.mark.parametrize("separator", [b"\n", b"\r", b"\r\n"])
def test_physical_line_count_is_bounded_before_line_hydration(separator):
    assert_code("physical_line_limit_exceeded",
                frequency_bytes=separator * (MAX_PHYSICAL_LINES + 1))


def test_four_mebibytes_of_blank_lines_cannot_expand_into_millions_of_records():
    assert_code("physical_line_limit_exceeded", frequency_bytes=b"\n" * MAX_FREQUENCY_BYTES)


def test_final_unterminated_physical_line_counts_toward_bound():
    assert_code("physical_line_limit_exceeded",
                frequency_bytes=b"\n" * MAX_PHYSICAL_LINES + b"0")


@pytest.mark.parametrize("separator", ["\u0085", "\u2028", "\u2029"])
def test_unicode_line_separator_does_not_manufacture_native_frequency_records(separator):
    data = (" &plot nbnd=3,nks=1 /\n0 0 0" + separator + "1 2 3\n").encode()
    assert_code("unsupported_unicode_line_separator", frequency_bytes=data)


@pytest.mark.parametrize("separator", ["\u0085", "\u2028", "\u2029"])
def test_unicode_line_separator_in_input_is_not_silently_interpreted(separator):
    assert_code("unsupported_unicode_line_separator",
                input_bytes=input_file(comment="! UTF-8 注释" + separator + "\n"))


@pytest.mark.parametrize("separator", [b"\n", b"\r", b"\r\n"])
def test_native_line_endings_keep_exact_utf8_byte_locators(separator):
    inp = input_file(comment="! 普通 UTF-8 注释\n").replace(b"\n", separator)
    freq = frequencies().replace(b"\n", separator)
    result = parse(inp, freq)
    for item in result["input_observations"]["assignments"]:
        span = item["locator"]
        assert inp[span["start_byte"]:span["end_byte"]].decode() == item["raw_value"]
    for point in result["spectrum"]["qpoints"]:
        for item in [*point["coordinates"], *point["frequencies"]]:
            span = item["locator"]
            assert freq[span["start_byte"]:span["end_byte"]].decode() == item["raw_text"]
            assert freq[:span["start_byte"]].count(separator) + 1 == span["line"]


def test_safe_error_does_not_echo_source_text():
    secret = b"credential-private-source"
    with pytest.raises(MatdynImportError) as caught:
        parse(frequency_bytes=secret)
    assert secret.decode() not in str(caught.value)
