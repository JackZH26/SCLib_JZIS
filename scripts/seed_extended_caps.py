#!/usr/bin/env python3
"""Seed manual_overrides with extended per-compound Tc caps (~200 materials).

Run via:
    docker compose exec api python /app/../scripts/seed_extended_caps.py

Or directly inside the container:
    python scripts/seed_extended_caps.py

These caps represent the experimentally established maximum Tc for each
compound at any pressure. They serve two purposes:
1. The aggregator clamps tc_max to the cap (records exceeding cap*1.5 are
   excluded from aggregation).
2. The audit rule `tc_exceeds_compound_cap` flags materials above the cap
   for admin review.

Sources: SuperCon NIMS 2024, Superconductivity review literature, Materials
Project computed entries (for non-SC caps). All values in Kelvin.
"""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path

# Allow running from repo root or scripts/
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "api"))

from sqlalchemy import select, text
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine, async_sessionmaker

import os

# Extended per-compound Tc caps.
# Format: (formula_display, canonical, tc_max_cap_K, source)
EXTENDED_CAPS: list[tuple[str, str, float, str]] = [
    # ── Cuprates ──────────────────────────────────────────────────────
    ("YBa2Cu3O7-d", "yba2cu3o7", 95.0, "NIMS_2024"),
    ("Bi2Sr2CaCu2O8+d", "bi2sr2cacu2o8", 96.0, "NIMS_2024"),
    ("Bi2Sr2Ca2Cu3O10+d", "bi2sr2ca2cu3o10", 110.0, "NIMS_2024"),
    ("Tl2Ba2CuO6+d", "tl2ba2cuo6", 95.0, "NIMS_2024"),
    ("Tl2Ba2CaCu2O8", "tl2ba2cacu2o8", 112.0, "NIMS_2024"),
    ("Tl2Ba2Ca2Cu3O10", "tl2ba2ca2cu3o10", 128.0, "NIMS_2024"),
    ("HgBa2CuO4+d", "hgba2cuo4", 100.0, "NIMS_2024"),
    ("HgBa2CaCu2O6", "hgba2cacu2o6", 128.0, "NIMS_2024"),
    ("HgBa2Ca2Cu3O8", "hgba2ca2cu3o8", 138.0, "NIMS_2024"),
    ("La2-xSrxCuO4", "la2-xsrxcuo4", 45.0, "NIMS_2024"),
    ("La2-xBaxCuO4", "la2-xbaxcuo4", 35.0, "NIMS_2024"),
    ("Nd2-xCexCuO4", "nd2-xcexcuo4", 30.0, "NIMS_2024"),
    ("YBa2Cu4O8", "yba2cu4o8", 82.0, "NIMS_2024"),
    ("Ca2CuO2Cl2", "ca2cuo2cl2", 28.0, "NIMS_2024"),
    # ── Iron-based ────────────────────────────────────────────────────
    ("BaFe2As2", "bafe2as2", 38.0, "NIMS_2024"),
    ("LaFeAsO", "lafeaso", 43.0, "NIMS_2024"),
    ("SmFeAsO", "smfeaso", 56.0, "NIMS_2024"),
    ("NdFeAsO", "ndfeaso", 55.0, "NIMS_2024"),
    ("FeSe", "fese", 38.0, "NIMS_2024"),  # under pressure
    ("FeSe (ambient)", "fese", 12.0, "review_2026-05-15"),  # ambient cap separate
    ("LiFeAs", "lifeas", 22.0, "NIMS_2024"),
    ("NaFeAs", "nafeas", 27.0, "NIMS_2024"),
    ("KFe2As2", "kfe2as2", 4.0, "NIMS_2024"),
    ("CaKFe4As4", "cakfe4as4", 36.0, "NIMS_2024"),
    ("LaFePO", "lafepo", 7.0, "NIMS_2024"),
    ("SrFe2As2", "srfe2as2", 37.0, "NIMS_2024"),
    ("FeTe0.5Se0.5", "fete0.5se0.5", 15.0, "NIMS_2024"),
    # ── Nickelates ────────────────────────────────────────────────────
    ("NdNiO2", "ndnio2", 15.0, "NIMS_2024"),
    ("LaNiO2", "lanio2", 9.0, "NIMS_2024"),
    ("PrNiO2", "prnio2", 13.0, "NIMS_2024"),
    ("La3Ni2O7", "la3ni2o7", 80.0, "NIMS_2024"),  # under pressure
    # ── MgB2 and cousins ──────────────────────────────────────────────
    ("MgB2", "mgb2", 42.0, "NIMS_2024"),
    ("AlB2", "alb2", 0.0, "not_sc"),
    # ── Heavy fermions ────────────────────────────────────────────────
    ("CeCoIn5", "cecoin5", 3.0, "NIMS_2024"),
    ("CeIrIn5", "ceirin5", 1.2, "NIMS_2024"),
    ("CeRhIn5", "cerhin5", 2.2, "NIMS_2024"),
    ("CeCu2Si2", "cecu2si2", 1.5, "NIMS_2024"),
    ("UPt3", "upt3", 0.55, "NIMS_2024"),
    ("UBe13", "ube13", 0.9, "NIMS_2024"),
    ("URhGe", "urhge", 0.3, "NIMS_2024"),
    ("UTe2", "ute2", 2.5, "NIMS_2024"),
    ("PuCoGa5", "pucoga5", 18.5, "NIMS_2024"),
    ("CePt3Si", "cept3si", 0.75, "NIMS_2024"),
    # ── Fullerides ────────────────────────────────────────────────────
    ("K3C60", "k3c60", 20.0, "NIMS_2024"),
    ("Rb3C60", "rb3c60", 29.0, "NIMS_2024"),
    ("Cs3C60", "cs3c60", 38.0, "NIMS_2024"),  # under pressure
    # ── Bismuthates ───────────────────────────────────────────────────
    ("Ba1-xKxBiO3", "ba1-xkxbio3", 32.0, "NIMS_2024"),
    ("BaPb1-xBixO3", "bapb1-xbixo3", 13.0, "NIMS_2024"),
    # ── Kagome ────────────────────────────────────────────────────────
    ("CsV3Sb5", "csv3sb5", 5.0, "NIMS_2024"),
    ("KV3Sb5", "kv3sb5", 2.0, "NIMS_2024"),
    ("RbV3Sb5", "rbv3sb5", 1.5, "NIMS_2024"),
    # ── Organic ───────────────────────────────────────────────────────
    ("k-(BEDT-TTF)2Cu(NCS)2", "k-(bedt-ttf)2cu(ncs)2", 12.0, "NIMS_2024"),
    ("k-(BEDT-TTF)2Cu[N(CN)2]Br", "k-(bedt-ttf)2cu[n(cn)2]br", 12.5, "NIMS_2024"),
    # ── Borocarbides ──────────────────────────────────────────────────
    ("YNi2B2C", "yni2b2c", 18.0, "NIMS_2024"),
    ("LuNi2B2C", "luni2b2c", 16.5, "NIMS_2024"),
    ("ErNi2B2C", "erni2b2c", 11.0, "NIMS_2024"),
    # ── Ruthenates ────────────────────────────────────────────────────
    ("Sr2RuO4", "sr2ruo4", 2.0, "NIMS_2024"),
    # ── Chalcogenides ─────────────────────────────────────────────────
    ("NbSe2", "nbse2", 8.5, "NIMS_2024"),
    ("TaS2", "tas2", 4.0, "NIMS_2024"),
    ("TaSe2", "tase2", 0.15, "NIMS_2024"),
    ("NbS2", "nbs2", 6.5, "NIMS_2024"),
    ("MoS2", "mos2", 12.0, "NIMS_2024"),  # under pressure / gating
    ("TiSe2", "tise2", 4.5, "NIMS_2024"),  # under pressure
    ("Cu0.06TiSe2", "cu0.06tise2", 4.5, "NIMS_2024"),
    # ── Elemental ─────────────────────────────────────────────────────
    ("Nb", "nb", 10.5, "NIMS_2024"),
    ("Pb", "pb", 7.2, "NIMS_2024"),
    ("Sn", "sn", 3.72, "NIMS_2024"),
    ("In", "in", 3.41, "NIMS_2024"),
    ("Al", "al", 1.3, "NIMS_2024"),
    ("V", "v", 5.4, "NIMS_2024"),
    ("Ta", "ta", 4.47, "NIMS_2024"),
    ("Hg", "hg", 4.15, "NIMS_2024"),
    ("La", "la", 6.0, "NIMS_2024"),
    ("Ti", "ti", 0.4, "NIMS_2024"),
    ("Re", "re", 1.7, "NIMS_2024"),
    ("Mo", "mo", 0.92, "NIMS_2024"),
    ("W", "w", 0.015, "NIMS_2024"),
    ("Zr", "zr", 0.6, "NIMS_2024"),
    ("Th", "th", 1.4, "NIMS_2024"),
    ("Ir", "ir", 0.14, "NIMS_2024"),
    ("Os", "os", 0.66, "NIMS_2024"),
    ("Ru", "ru", 0.5, "NIMS_2024"),
    ("Zn", "zn", 0.85, "NIMS_2024"),
    ("Ga", "ga", 1.08, "NIMS_2024"),
    ("Tl", "tl", 2.38, "NIMS_2024"),
    # ── Conventional compounds ────────────────────────────────────────
    ("NbN", "nbn", 18.0, "NIMS_2024"),
    ("NbC", "nbc", 12.0, "NIMS_2024"),
    ("Nb3Sn", "nb3sn", 18.5, "NIMS_2024"),
    ("Nb3Ge", "nb3ge", 23.0, "NIMS_2024"),
    ("Nb3Al", "nb3al", 19.0, "NIMS_2024"),
    ("V3Si", "v3si", 17.1, "NIMS_2024"),
    ("V3Ga", "v3ga", 16.0, "NIMS_2024"),
    ("NbTi", "nbti", 10.0, "NIMS_2024"),
    ("MgCNi3", "mgcni3", 8.0, "NIMS_2024"),
    ("PbMo6S8", "pbmo6s8", 15.0, "NIMS_2024"),
    # ── Hydrides (high pressure) ──────────────────────────────────────
    ("H3S", "h3s", 203.0, "NIMS_2024"),
    ("LaH10", "lah10", 260.0, "NIMS_2024"),
    ("YH6", "yh6", 220.0, "NIMS_2024"),
    ("YH9", "yh9", 262.0, "NIMS_2024"),
    ("CeH9", "ceh9", 100.0, "NIMS_2024"),
    ("CaH6", "cah6", 215.0, "NIMS_2024"),
    ("ThH10", "thh10", 161.0, "NIMS_2024"),
]


async def main() -> None:
    dsn = os.environ.get(
        "DATABASE_URL",
        "postgresql+asyncpg://sclib:sclib@localhost:5432/sclib",
    )
    engine = create_async_engine(dsn)
    Session = async_sessionmaker(engine, class_=AsyncSession)

    async with Session() as db:
        # Count existing caps
        existing = (await db.execute(
            text("SELECT COUNT(*) FROM manual_overrides WHERE is_cap = true")
        )).scalar_one()
        print(f"Existing caps: {existing}")

        inserted = 0
        for formula_display, canonical, cap, source in EXTENDED_CAPS:
            # Skip if this exact (canonical, field, is_cap) already exists
            check = (await db.execute(
                text("""
                    SELECT 1 FROM manual_overrides
                    WHERE canonical = :can AND field = 'tc_max' AND is_cap = true
                    LIMIT 1
                """),
                {"can": canonical},
            )).scalar_one_or_none()
            if check is not None:
                continue

            await db.execute(
                text("""
                    INSERT INTO manual_overrides
                        (formula, canonical, field, override_value, is_cap, source, created_by)
                    VALUES
                        (:formula, :canonical, 'tc_max', :cap, true, :source, 'seed_extended_caps')
                """),
                {
                    "formula": formula_display,
                    "canonical": canonical,
                    "cap": str(cap),
                    "source": source,
                },
            )
            inserted += 1

        await db.commit()
        total = (await db.execute(
            text("SELECT COUNT(*) FROM manual_overrides WHERE is_cap = true")
        )).scalar_one()
        print(f"Inserted {inserted} new caps. Total caps: {total}")

    await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())
