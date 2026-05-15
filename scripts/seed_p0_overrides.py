#!/usr/bin/env python3
"""Seed refuted_claims and manual_overrides tables for P0 hotfixes.

Run AFTER alembic migration 0025 has been applied::

    cd /path/to/SCLib
    python scripts/seed_p0_overrides.py

Uses a sync psycopg2 connection (same DSN as alembic). Idempotent —
checks for existing rows by (canonical, field) before inserting.
"""
from __future__ import annotations

import os
import sys

import sqlalchemy as sa
from sqlalchemy import create_engine, text

# ---------------------------------------------------------------------------
# Connection
# ---------------------------------------------------------------------------

DATABASE_URL = os.environ.get(
    "DATABASE_URL",
    "postgresql://sclib:sclib@localhost:5432/sclib",
)
# Ensure sync driver (psycopg2), not asyncpg
DSN = DATABASE_URL.replace("postgresql+asyncpg://", "postgresql://")
engine = create_engine(DSN)


# ---------------------------------------------------------------------------
# 1. Refuted claims  (Step 0.2)
# ---------------------------------------------------------------------------

REFUTED_CLAIMS = [
    # (formula, canonical, claim_type, claimed_tc, refutation_doi, refutation_year, notes)
    (
        "LK-99", "lk-99", "room_temp_sc", 400.0,
        "10.1038/s41586-023-06774-2", 2023,
        "Cu₂S impurity; sample not superconducting. Multiple independent replications failed.",
    ),
    (
        "LK99", "lk99", "room_temp_sc", 400.0,
        "10.1038/s41586-023-06774-2", 2023,
        "Alternate spelling of LK-99; same refutation.",
    ),
    (
        "Pb₁₀₋ₓCuₓ(PO₄)₆O", "pb10-xcux(po4)6o", "room_temp_sc", 400.0,
        "10.1038/s41586-023-06774-2", 2023,
        "LK-99 full formula; refuted.",
    ),
    (
        "CSH", "csh", "room_temp_sc", 288.0,
        "10.1038/s41586-022-05294-9", 2023,
        "Dias et al. carbonaceous sulfur hydride; Nature paper retracted 2022.",
    ),
    (
        "LaH₁₀", "lah10", "tc_value", 260.0,
        None, 2023,
        "Dias/Salamat LaH₁₀ claims under scrutiny; original data anomalies. "
        "Note: LaH₁₀ IS a real superconductor (Drozdov 2019), but Dias Tc values disputed.",
    ),
    (
        "AgB₂", "agb2", "superconductor", None,
        None, None,
        "No confirmed superconductivity in AgB₂ despite early claims by analogy with MgB₂.",
    ),
    (
        "Sr₂CuO₃₊δ", "sr2cuo3+d", "room_temp_sc", 350.0,
        None, None,
        "Room-temperature SC claim in cuprate film; not reproduced.",
    ),
    (
        "ZrZn₂", "zrzn2", "superconductor", None,
        None, None,
        "Reported p-wave SC in itinerant ferromagnet; subsequent studies attribute signal to surface Zn.",
    ),
]

# ---------------------------------------------------------------------------
# 2. Manual overrides — exact corrections  (Step 0.3, part 1)
# ---------------------------------------------------------------------------

# (formula, canonical, field, override_value, is_cap, source, reason)
EXACT_OVERRIDES = [
    # --- Top-20 review E1: BSCCO Hc2 ---
    (
        "Bi₂Sr₂CaCu₂O₈₊δ", "bi2sr2cacu2o8", "hc2_tesla", "300",
        False, "review_2026-05-15",
        "E1: Was 19000T (Oe→T unit error). Literature: c-axis ~60-110T, ab ~250-400T. Set ~300T.",
    ),
    # --- Top-20 review E2: YBCO-O6+x tc_max ---
    (
        "YBa₂Cu₃O₆₊ₓ", "yba2cu3o6+x", "tc_max", "93",
        False, "review_2026-05-15",
        "E2: Was 135K (Hg-1223 Tc mis-assigned to YBCO variant). YBCO max = 93K.",
    ),
    # --- Top-20 review E3: LSCO tc_max + tc_ambient ---
    (
        "La₂₋ₓSrₓCuO₄", "la2-xsrxcuo4", "tc_max", "38",
        False, "review_2026-05-15",
        "E3: Was 90K. Optimal doping x≈0.15 Tc=38K; high-pressure max ~45K.",
    ),
    (
        "La₂₋ₓSrₓCuO₄", "la2-xsrxcuo4", "tc_ambient", "38",
        False, "review_2026-05-15",
        "E3: Was 58K. Ambient-pressure LSCO Tc=38K at optimal doping.",
    ),
    # --- Top-20 review E4: FeSe tc_ambient ---
    (
        "FeSe", "fese", "tc_ambient", "8.5",
        False, "review_2026-05-15",
        "E4: Was 68K (FeSe/STO thin-film value). Bulk FeSe at ambient pressure = 8.5K.",
    ),
    # --- Top-20 review E5: Sr₂RuO₄ ---
    (
        "Sr₂RuO₄", "sr2ruo4", "tc_max", "1.5",
        False, "review_2026-05-15",
        "E5: Was 3K. Consensus Tc = 1.5K (Maeno 1994, confirmed by multiple groups).",
    ),
    (
        "Sr₂RuO₄", "sr2ruo4", "tc_ambient", "1.5",
        False, "review_2026-05-15",
        "E5: Was 2.5K. Ambient Tc = 1.5K.",
    ),
    (
        "Sr₂RuO₄", "sr2ruo4", "pairing_symmetry", '"unknown"',
        False, "review_2026-05-15",
        "E5: Was p-wave. Pustogow et al. Nature 574, 72 (2019) NMR refuted chiral p-wave.",
    ),
    # --- Top-20 review: MgB₂ ---
    (
        "MgB₂", "mgb2", "tc_max", "39",
        False, "review_2026-05-15",
        "Was 43K. Nagamatsu 2001: Tc = 39K (universally accepted).",
    ),
    (
        "MgB₂", "mgb2", "lambda_eph", "0.87",
        False, "review_2026-05-15",
        "Was 2.5. Allen-Dynes/Eliashberg λ_eph = 0.87 (σ-band) or ~1.0 (effective two-gap).",
    ),
    # --- Top-20 review: CsV₃Sb₅ ---
    (
        "CsV₃Sb₅", "csv3sb5", "tc_ambient", "2.5",
        False, "review_2026-05-15",
        "Was 4.6K. Ortiz et al. PRL 2020: Tc = 2.5K.",
    ),
    # --- Top-20 review: UTe₂ ---
    (
        "UTe₂", "ute2", "tc_ambient", "2.0",
        False, "review_2026-05-15",
        "Was 2.6K. Ran et al. Science 2019: Tc ≈ 1.6–2.0K. Use 2.0K upper value.",
    ),
]

# ---------------------------------------------------------------------------
# 3. Manual overrides — per-compound caps  (Step 0.3, part 2)
# ---------------------------------------------------------------------------

CAP_OVERRIDES = [
    # (formula, canonical, field, cap_value, source, reason)
    (
        "La₂₋ₓSrₓCuO₄", "la2-xsrxcuo4", "tc_max", "45",
        "Schilling 1993 (high-pressure)",
        "Highest credible Tc for LSCO: ~45K under pressure. Above this = mis-assignment.",
    ),
    (
        "FeSe", "fese", "tc_ambient", "12",
        "Medvedev 2009",
        "Bulk FeSe Tc = 8.5K ambient, up to ~37K under 7GPa. Ambient cap 12K generous.",
    ),
    (
        "Sr₂RuO₄", "sr2ruo4", "tc_max", "2.0",
        "Maeno 2012 review",
        "Tc = 1.5K, max reported ~1.5K. Cap at 2.0K to allow small measurement variation.",
    ),
    (
        "MgB₂", "mgb2", "tc_max", "42",
        "Buzea & Yamashita 2001 review",
        "Tc = 39K, no credible report above 40K. Cap at 42K.",
    ),
    (
        "NbSe₂", "nbse2", "tc_max", "8.5",
        "Frindt 1972; Yokoya 2001",
        "Bulk Tc = 7.2K, thin film up to ~8K. Cap at 8.5K.",
    ),
    (
        "Nb", "nb", "tc_max", "10.5",
        "Finnemore 1966",
        "Elemental Nb Tc = 9.25K. Thin films up to ~10K. Cap at 10.5K.",
    ),
    (
        "Al", "al", "tc_max", "1.3",
        "Phillips 1959",
        "Elemental Al Tc = 1.175K. Cap at 1.3K.",
    ),
    (
        "CeCoIn₅", "cecoin5", "tc_max", "3.0",
        "Petrovic 2001",
        "Tc = 2.3K. Cap at 3.0K.",
    ),
    (
        "UTe₂", "ute2", "tc_max", "2.5",
        "Ran 2019",
        "Tc ≈ 2.0K. Cap at 2.5K.",
    ),
    (
        "CsV₃Sb₅", "csv3sb5", "tc_max", "5.0",
        "Ortiz 2020",
        "Tc = 2.5K. Under pressure up to ~8K but we cap ambient at 5.0K.",
    ),
    (
        "YBa₂Cu₃O₇₋δ", "yba2cu3o7", "tc_max", "95",
        "Wu 1987",
        "Optimal Tc = 92-93K. Cap at 95K. Above this = likely data from Tl/Hg cuprate.",
    ),
    (
        "Bi₂Sr₂CaCu₂O₈₊δ", "bi2sr2cacu2o8", "tc_max", "96",
        "Maeda 1988",
        "Bi-2212 Tc ≈ 85-92K. Cap at 96K.",
    ),
    (
        "HgBa₂CuO₄₊δ", "hgba2cuo4", "tc_max", "100",
        "Putilin 1993",
        "Hg-1201 Tc ≈ 94-97K. Cap at 100K.",
    ),
    (
        "YNi₂B₂C", "yni2b2c", "tc_max", "18",
        "Cava 1994",
        "Tc = 15.6K. Cap at 18K.",
    ),
    (
        "LiFeAs", "lifeas", "tc_max", "22",
        "Tapp 2008",
        "Tc = 18K. Cap at 22K.",
    ),
    (
        "Tl₂Ba₂CuO₆₊δ", "tl2ba2cuo6", "tc_max", "95",
        "Shimakawa 1994",
        "Tl-2201 Tc ≈ 80-90K. Cap at 95K.",
    ),
]


def seed() -> None:
    with engine.begin() as conn:
        # ---- Refuted claims ----
        existing_refuted = {
            row[0]
            for row in conn.execute(
                text("SELECT canonical FROM refuted_claims")
            ).fetchall()
        }
        inserted_refuted = 0
        for formula, canonical, claim_type, claimed_tc, doi, year, notes in REFUTED_CLAIMS:
            if canonical in existing_refuted:
                continue
            conn.execute(
                text("""
                    INSERT INTO refuted_claims
                        (formula, canonical, claim_type, claimed_tc,
                         refutation_doi, refutation_year, notes)
                    VALUES (:formula, :canonical, :claim_type, :claimed_tc,
                            :doi, :year, :notes)
                """),
                {
                    "formula": formula,
                    "canonical": canonical,
                    "claim_type": claim_type,
                    "claimed_tc": claimed_tc,
                    "doi": doi,
                    "year": year,
                    "notes": notes,
                },
            )
            inserted_refuted += 1
        print(f"refuted_claims: inserted {inserted_refuted}, skipped {len(REFUTED_CLAIMS) - inserted_refuted}")

        # ---- Manual overrides (exact) ----
        existing_overrides = {
            (row[0], row[1], row[2])
            for row in conn.execute(
                text("SELECT canonical, field, is_cap FROM manual_overrides")
            ).fetchall()
        }
        inserted_exact = 0
        for formula, canonical, field, value, is_cap, source, reason in EXACT_OVERRIDES:
            key = (canonical, field, is_cap)
            if key in existing_overrides:
                continue
            conn.execute(
                text("""
                    INSERT INTO manual_overrides
                        (formula, canonical, field, override_value, is_cap, source, reason)
                    VALUES (:formula, :canonical, :field, :value, :is_cap, :source, :reason)
                """),
                {
                    "formula": formula,
                    "canonical": canonical,
                    "field": field,
                    "value": value,
                    "is_cap": is_cap,
                    "source": source,
                    "reason": reason,
                },
            )
            inserted_exact += 1
        print(f"manual_overrides (exact): inserted {inserted_exact}")

        # ---- Manual overrides (caps) ----
        inserted_caps = 0
        for formula, canonical, field, cap_value, source, reason in CAP_OVERRIDES:
            key = (canonical, field, True)
            if key in existing_overrides:
                continue
            conn.execute(
                text("""
                    INSERT INTO manual_overrides
                        (formula, canonical, field, override_value, is_cap, source, reason)
                    VALUES (:formula, :canonical, :field, :value, TRUE, :source, :reason)
                """),
                {
                    "formula": formula,
                    "canonical": canonical,
                    "field": field,
                    "value": cap_value,
                    "source": source,
                    "reason": reason,
                },
            )
            inserted_caps += 1
        print(f"manual_overrides (caps): inserted {inserted_caps}")

    print("Done.")


if __name__ == "__main__":
    seed()
