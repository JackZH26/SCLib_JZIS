#!/usr/bin/env python3
"""B.2: Formal statistical analysis of the 50-80 K Tc density valley.

Tests:
- H0 baseline: smooth log-linear interpolation between left-peak (30-40 K) and right-peak (80-100 K) density
- Poisson p-value for observed bin count vs expected under H0
- Bin-width sensitivity: 5, 10, 15 K bins
- Multiple-testing correction: Bonferroni over the candidate bin locations
- KDE alternative test: Silverman-bandwidth Gaussian KDE on log Tc; test for local minimum
- Bootstrap CI on depth ratio rho

Output: audit/refresh_2026_05_26/valley_statistics.csv
"""
from __future__ import annotations

import csv
from pathlib import Path

import numpy as np
from scipy import stats
from scipy.stats import gaussian_kde

def _pick_snapshot_dir() -> Path:
    """Use --snapshot-dir CLI arg if provided, else the most recent audit/refresh_*."""
    import sys
    repo = Path(__file__).resolve().parent.parent
    for i, arg in enumerate(sys.argv):
        if arg == "--snapshot-dir" and i + 1 < len(sys.argv):
            return Path(sys.argv[i + 1]).resolve()
    candidates = sorted(repo.glob("audit/refresh_*"))
    return candidates[-1] if candidates else (repo / "audit" / "refresh_2026_05_26")

OUT = _pick_snapshot_dir()


def _load_5k_bins() -> dict[int, int]:
    """Load q11b_tc_5k_bins.csv from the chosen snapshot dir.
    Skips the psql '(N rows)' trailer line."""
    path = OUT / "q11b_tc_5k_bins.csv"
    bins: dict[int, int] = {}
    with path.open() as f:
        reader = csv.DictReader(f)
        for row in reader:
            try:
                bins[int(row["tc_low"])] = int(row["records"])
            except (KeyError, ValueError, TypeError):
                # Trailer rows like "(23 rows)" give None values; skip.
                continue
    if not bins:
        raise RuntimeError(f"Failed to load 5K bins from {path}")
    return bins

TC_BINS_5K = _load_5k_bins()


def hypothetical_record_list_from_bins(bins: dict[int, int]) -> np.ndarray:
    """Reconstruct an approximate per-record Tc array from binned counts (for KDE).
    Place each record at bin-center."""
    arr = []
    for bin_lo, n in bins.items():
        center = bin_lo + 2.5
        arr.extend([center] * n)
    return np.array(arr, dtype=float)


def poisson_test(observed: int, expected: float) -> float:
    """One-sided lower-tail Poisson p-value: P(N <= observed | lambda=expected)."""
    if expected <= 0:
        return 1.0
    return stats.poisson.cdf(observed, expected)


def main() -> int:
    rng = np.random.default_rng(42)

    print("="*70)
    print(f"B.2 — Valley statistical rigor (snapshot: {OUT.name})")
    print("="*70)

    bins = TC_BINS_5K
    print(f"\nFull bin counts (0-110 K, 5K bins):")
    for k in sorted(bins.keys()):
        print(f"  [{k:3d}, {k+5:3d}) K: {bins[k]:5d}")

    # ----- 1. Define candidate valley region (50-80 K) and neighbouring peaks
    valley_range = (50, 80)
    left_peak_range = (30, 40)
    right_peak_range = (80, 95)

    valley_bins = [k for k in bins if valley_range[0] <= k < valley_range[1]]
    n_valley = sum(bins[k] for k in valley_bins)
    width_valley = valley_range[1] - valley_range[0]
    density_valley_per_K = n_valley / width_valley

    n_left_peak = sum(bins[k] for k in bins if left_peak_range[0] <= k < left_peak_range[1])
    width_left = left_peak_range[1] - left_peak_range[0]
    density_left = n_left_peak / width_left

    n_right_peak = sum(bins[k] for k in bins if right_peak_range[0] <= k < right_peak_range[1])
    width_right = right_peak_range[1] - right_peak_range[0]
    density_right = n_right_peak / width_right

    print(f"\nValley vs neighbouring peaks:")
    print(f"  Left peak  (30-40 K): n={n_left_peak}, density={density_left:.1f} per K")
    print(f"  Valley     (50-80 K): n={n_valley}, density={density_valley_per_K:.1f} per K")
    print(f"  Right peak (80-95 K): n={n_right_peak}, density={density_right:.1f} per K")

    # ----- 2. Poisson test under H0 = log-linear baseline
    # H0: the density in the valley region is the geometric mean of left/right peak densities
    h0_density = np.sqrt(density_left * density_right)
    h0_expected_n = h0_density * width_valley
    p_poisson_raw = poisson_test(n_valley, h0_expected_n)

    print(f"\nPoisson test (H0 = log-linear interpolation between peaks):")
    print(f"  H0 density   = sqrt({density_left:.1f} * {density_right:.1f}) = {h0_density:.1f} per K")
    print(f"  H0 expected  = {h0_density:.1f} * {width_valley} = {h0_expected_n:.1f} records")
    print(f"  Observed     = {n_valley} records")
    print(f"  Raw p-value  = P(N <= {n_valley} | lambda={h0_expected_n:.1f}) = {p_poisson_raw:.2e}")

    # Bonferroni correction: K candidate valley locations between the two peaks
    n_candidate_valleys = 8  # roughly 7 distinct 30-K-wide windows between 20 and 100 K
    p_bonferroni = min(1.0, p_poisson_raw * n_candidate_valleys)
    print(f"  Bonferroni adj (K={n_candidate_valleys}): p = {p_bonferroni:.2e}")

    # ----- 3. Depth ratio with bootstrap CI
    min_valley_bin = min(bins[k] for k in valley_bins)
    valley_argmin = [k for k in valley_bins if bins[k] == min_valley_bin][0]
    # Use 65 K bin specifically (per paper definition)
    valley_5k_count_at_65 = bins[65]
    rho_point = valley_5k_count_at_65 / min(density_left * 5, density_right * 5)
    print(f"\nDepth ratio at 65 K bin:")
    print(f"  Min 5K bin in 50-80 K: at [{valley_argmin}, {valley_argmin+5}) K = {min_valley_bin} records")
    print(f"  rho = {valley_5k_count_at_65} / min({density_left * 5:.0f}, {density_right * 5:.0f}) = {rho_point:.3f}")

    # Bootstrap CI on rho by resampling the underlying record set
    records = hypothetical_record_list_from_bins(bins)
    boot_rhos = []
    for _ in range(2000):
        sample = rng.choice(records, size=len(records), replace=True)
        # recompute bin counts
        h_v, _ = np.histogram(sample[(sample >= 65) & (sample < 70)], bins=[65, 70])
        h_l, _ = np.histogram(sample[(sample >= 30) & (sample < 40)], bins=[30, 40])
        h_r, _ = np.histogram(sample[(sample >= 80) & (sample < 95)], bins=[80, 95])
        d_left = h_l[0] / 10
        d_right = h_r[0] / 15
        if min(d_left, d_right) > 0:
            rho = h_v[0] / min(d_left * 5, d_right * 5)
            boot_rhos.append(rho)
    boot_rhos = np.array(boot_rhos)
    rho_ci = np.percentile(boot_rhos, [2.5, 97.5])
    print(f"  Bootstrap 95% CI on rho: [{rho_ci[0]:.3f}, {rho_ci[1]:.3f}]  (B=2000)")

    # ----- 4. Bin-width sensitivity (5, 10, 15 K)
    print(f"\nBin-width sensitivity for valley depth:")
    for bw in (5, 10, 15):
        h_valley, _ = np.histogram(records[(records >= 50) & (records < 80)], bins=range(50, 81, bw))
        min_v = h_valley.min() if len(h_valley) else 0
        h_l, _ = np.histogram(records[(records >= 30) & (records < 40)], bins=range(30, 41, bw))
        h_r, _ = np.histogram(records[(records >= 80) & (records < 95)], bins=range(80, 96, bw))
        max_neighbour = max(h_l.max(), h_r.max()) if len(h_l) and len(h_r) else 1
        rho_bw = min_v / max_neighbour if max_neighbour > 0 else float("nan")
        print(f"  bin-width {bw:2d} K: valley min={min_v}, max neighbour={max_neighbour}, rho={rho_bw:.3f}")

    # ----- 5. KDE alternative test
    print(f"\nKDE-based alternative test:")
    # Take records in 0-110 K
    rec_in_range = records[(records > 0) & (records <= 110)]
    kde = gaussian_kde(rec_in_range, bw_method="silverman")
    x_grid = np.linspace(20, 100, 200)
    f = kde(x_grid)
    # Find local minimum near 65 K
    near_65 = (x_grid >= 50) & (x_grid <= 80)
    f_valley = f[near_65]
    x_valley = x_grid[near_65]
    idx_min = np.argmin(f_valley)
    print(f"  KDE valley centre: T = {x_valley[idx_min]:.1f} K, density = {f_valley[idx_min]:.4f}")
    # Compare to neighbouring max
    left_max = f[(x_grid >= 30) & (x_grid <= 40)].max()
    right_max = f[(x_grid >= 80) & (x_grid <= 100)].max()
    rho_kde = f_valley[idx_min] / min(left_max, right_max)
    print(f"  KDE depth ratio: rho_KDE = {rho_kde:.3f}")

    # ----- Write to CSV
    rows = [
        ("n_valley_50_80", n_valley),
        ("n_left_peak_30_40", n_left_peak),
        ("n_right_peak_80_95", n_right_peak),
        ("density_left_per_K", round(density_left, 2)),
        ("density_right_per_K", round(density_right, 2)),
        ("density_valley_per_K", round(density_valley_per_K, 2)),
        ("h0_density_per_K_logmean", round(h0_density, 2)),
        ("h0_expected_n_in_30K_window", round(h0_expected_n, 1)),
        ("poisson_p_raw_one_sided", f"{p_poisson_raw:.2e}"),
        ("poisson_p_bonferroni_K8", f"{p_bonferroni:.2e}"),
        ("rho_at_65K_bin_5K", round(rho_point, 3)),
        ("rho_bootstrap_CI_low", round(rho_ci[0], 3)),
        ("rho_bootstrap_CI_high", round(rho_ci[1], 3)),
        ("kde_valley_centre_K", round(x_valley[idx_min], 1)),
        ("kde_depth_ratio", round(rho_kde, 3)),
    ]
    with (OUT / "valley_statistics.csv").open("w") as f:
        w = csv.writer(f)
        w.writerow(["metric", "value"])
        for r in rows:
            w.writerow(r)

    print(f"\nWrote {OUT / 'valley_statistics.csv'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
