"""Hayashi-Yoshida O(M_i + M_j) overlap covariance & coarse-bar shrunk benchmark (spec §6.2)."""
from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import datetime


@dataclass(frozen=True)
class AsyncCovarianceReport:
    symbols: tuple[str, ...]
    matrix: tuple[tuple[float, ...], ...]
    repair_trace_norm: float
    joint_coverage_ratio: float
    effective_overlap_ratio: float
    stale_mark_share: float


def _log_return_intervals(series: list[tuple[datetime, float]]) -> list[tuple[float, float, float]]:
    ordered = sorted(series, key=lambda x: x[0])
    out: list[tuple[float, float, float]] = []
    for idx in range(1, len(ordered)):
        t0, p0 = ordered[idx - 1]
        t1, p1 = ordered[idx]
        if p0 > 0 and p1 > 0 and t1 > t0:
            out.append((t0.timestamp(), t1.timestamp(), math.log(p1 / p0)))
    return out


def _hy_pair(
    iv_a: list[tuple[float, float, float]],
    iv_b: list[tuple[float, float, float]],
) -> tuple[float, int]:
    """O(M_i + M_j) two-pointer Hayashi-Yoshida covariance sum over overlapping intervals."""
    cov = 0.0
    overlaps = 0
    j = 0
    nb = len(iv_b)
    for a0, a1, ra in iv_a:
        while j < nb and iv_b[j][1] <= a0:
            j += 1
        k = j
        while k < nb and iv_b[k][0] < a1:
            cov += ra * iv_b[k][2]
            overlaps += 1
            k += 1
    return cov, overlaps


def _jacobi_eigen_symmetric(mat: list[list[float]], max_iter: int = 80) -> tuple[list[float], list[list[float]]]:
    """Pure-Python Jacobi eigenvalue decomposition for small/medium symmetric matrices."""
    n = len(mat)
    a = [row[:] for row in mat]
    v = [[1.0 if i == j else 0.0 for j in range(n)] for i in range(n)]
    for _ in range(max_iter):
        max_val = 0.0
        p, q = 0, 1
        for i in range(n):
            for j in range(i + 1, n):
                if abs(a[i][j]) > max_val:
                    max_val = abs(a[i][j])
                    p, q = i, j
        if max_val < 1e-12:
            break
        diff = a[q][q] - a[p][p]
        theta = 0.5 * math.atan2(2.0 * a[p][q], diff) if abs(diff) > 1e-15 else math.pi / 4.0
        c, s = math.cos(theta), math.sin(theta)
        for i in range(n):
            if i != p and i != q:
                aip, aiq = a[i][p], a[i][q]
                a[i][p] = a[p][i] = c * aip - s * aiq
                a[i][q] = a[q][i] = s * aip + c * aiq
        app, aqq, apq = a[p][p], a[q][q], a[p][q]
        a[p][p] = c * c * app - 2.0 * s * c * apq + s * s * aqq
        a[q][q] = s * s * app + 2.0 * s * c * apq + c * c * aqq
        a[p][q] = a[q][p] = 0.0
        for i in range(n):
            vip, viq = v[i][p], v[i][q]
            v[i][p] = c * vip - s * viq
            v[i][q] = s * vip + c * viq
    return [a[i][i] for i in range(n)], v


def _psd_repair(mat: list[list[float]], floor: float = 1e-12) -> tuple[list[list[float]], float]:
    n = len(mat)
    if n == 0:
        return [], 0.0
    if n == 1:
        val = max(floor, mat[0][0])
        return [[val]], abs(val - mat[0][0])
    eigvals, eigvecs = _jacobi_eigen_symmetric(mat)
    clipped = [max(floor, ev) for ev in eigvals]
    repair_trace = sum(abs(c - e) for c, e in zip(clipped, eigvals, strict=True))
    repaired = [[0.0] * n for _ in range(n)]
    for i in range(n):
        for j in range(n):
            repaired[i][j] = sum(eigvecs[i][k] * clipped[k] * eigvecs[j][k] for k in range(n))
    return repaired, repair_trace


def hayashi_yoshida_covariance(
    series_by_symbol: dict[str, list[tuple[datetime, float]]],
    *,
    stale_gap_s: float = 600.0,
) -> AsyncCovarianceReport:
    """Compute O(M_i + M_j) Hayashi-Yoshida overlap covariance with PSD repair and coverage diagnostics."""
    symbols = tuple(sorted(series_by_symbol))
    n = len(symbols)
    intervals = {s: _log_return_intervals(series_by_symbol[s]) for s in symbols}
    raw = [[0.0] * n for _ in range(n)]
    total_overlaps = 0
    total_possible = 0
    stale_count = 0
    total_intervals = 0

    for i, si in enumerate(symbols):
        ivi = intervals[si]
        total_intervals += len(ivi)
        stale_count += sum(1 for t0, t1, _ in ivi if (t1 - t0) > stale_gap_s)
        raw[i][i] = sum(r * r for _, _, r in ivi)
        for j in range(i + 1, n):
            ivj = intervals[symbols[j]]
            cov, ov = _hy_pair(ivi, ivj)
            raw[i][j] = raw[j][i] = cov
            total_overlaps += ov
            total_possible += max(1, min(len(ivi), len(ivj)))

    repaired, trace_norm = _psd_repair(raw)
    active_syms = sum(1 for s in symbols if len(intervals[s]) > 0)
    joint_cov = active_syms / n if n > 0 else 0.0
    overlap_ratio = total_overlaps / total_possible if total_possible > 0 else 1.0
    stale_share = stale_count / total_intervals if total_intervals > 0 else 0.0
    return AsyncCovarianceReport(
        symbols=symbols,
        matrix=tuple(tuple(row) for row in repaired),
        repair_trace_norm=trace_norm,
        joint_coverage_ratio=joint_cov,
        effective_overlap_ratio=overlap_ratio,
        stale_mark_share=stale_share,
    )


def coarse_bar_shrunk_covariance(
    returns_by_symbol: dict[str, list[float]],
    *,
    shrinkage: float = 0.25,
) -> tuple[tuple[str, ...], tuple[tuple[float, ...], ...]]:
    """Synchronized coarse-bar Ledoit-Wolf-style diagonal-shrunk covariance benchmark."""
    symbols = tuple(sorted(returns_by_symbol))
    n = len(symbols)
    if n == 0:
        return (), ()
    t_len = min(len(returns_by_symbol[s]) for s in symbols)
    if t_len < 2:
        eye = tuple(tuple(1e-6 if i == j else 0.0 for j in range(n)) for i in range(n))
        return symbols, eye
    means = [sum(returns_by_symbol[s][:t_len]) / t_len for s in symbols]
    sample = [[0.0] * n for _ in range(n)]
    for i, si in enumerate(symbols):
        ri = returns_by_symbol[si]
        for j in range(i, n):
            rj = returns_by_symbol[symbols[j]]
            cov = sum((ri[t] - means[i]) * (rj[t] - means[j]) for t in range(t_len)) / (t_len - 1)
            sample[i][j] = sample[j][i] = cov
    avg_var = sum(sample[i][i] for i in range(n)) / n
    out = [
        [
            (1.0 - shrinkage) * sample[i][j] + (shrinkage * avg_var if i == j else 0.0)
            for j in range(n)
        ]
        for i in range(n)
    ]
    return symbols, tuple(tuple(row) for row in out)
