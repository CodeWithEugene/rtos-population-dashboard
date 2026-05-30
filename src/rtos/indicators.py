"""Derived public-health indicators from the tidy population table.

These are the numbers a planner actually reasons about: the broad age structure
(children / working-age / elderly), dependency ratios that drive demand on
schools, jobs and health services, the sex ratio, and an approximate median age.
All functions operate on a *long* tidy frame and are agnostic to how it was
filtered, so the dashboard reuses them on any country/age/sex selection.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

# Coarse, policy-relevant age groups (by WorldPop lower-bound code).
CHILD_CODES = {0, 1, 5, 10}                       # 0-14
WORKING_CODES = {15, 20, 25, 30, 35, 40, 45, 50, 55, 60}  # 15-64
ELDERLY_CODES = {65, 70, 75, 80, 85, 90}          # 65+


def age_group(code: int) -> str:
    if code in CHILD_CODES:
        return "children"
    if code in WORKING_CODES:
        return "working_age"
    return "elderly"


def add_age_group(df: pd.DataFrame) -> pd.DataFrame:
    out = df.copy()
    out["age_group"] = out["age_code"].map(age_group)
    return out


def _grouped_median_age(sub: pd.DataFrame) -> float:
    """Approximate median age via the grouped-median formula on age bands."""
    g = (
        sub.groupby(["age_low", "age_high"], as_index=False)["population"]
        .sum()
        .sort_values("age_low")
    )
    total = g["population"].sum()
    if total <= 0:
        return float("nan")
    cum = g["population"].cumsum()
    half = total / 2.0
    idx = int((cum >= half).values.argmax())
    row = g.iloc[idx]
    width = (row["age_high"] - row["age_low"]) + 1
    cf_before = cum.iloc[idx] - row["population"]
    freq = row["population"] if row["population"] > 0 else 1.0
    return float(row["age_low"] + ((half - cf_before) / freq) * width)


def summarise(df: pd.DataFrame, by: list[str] | None = None) -> pd.DataFrame:
    """Compute indicators, optionally grouped by columns in ``by``.

    Expects columns: population, age_code, age_low, age_high, sex.
    Returns one row per group with totals, percentages and ratios.
    """
    df = add_age_group(df)
    keys = by or []
    records = []
    grouped = [((), df)] if not keys else list(df.groupby(keys))

    for key, sub in grouped:
        total = sub["population"].sum()
        by_group = sub.groupby("age_group")["population"].sum()
        children = float(by_group.get("children", 0.0))
        working = float(by_group.get("working_age", 0.0))
        elderly = float(by_group.get("elderly", 0.0))
        males = float(sub.loc[sub["sex"] == "male", "population"].sum())
        females = float(sub.loc[sub["sex"] == "female", "population"].sum())

        rec = {
            "population": float(total),
            "children": children,
            "working_age": working,
            "elderly": elderly,
            "pct_children": _safe_pct(children, total),
            "pct_working_age": _safe_pct(working, total),
            "pct_elderly": _safe_pct(elderly, total),
            # Dependents per 100 working-age people.
            "age_dependency_ratio": _safe_ratio(children + elderly, working) * 100,
            "child_dependency_ratio": _safe_ratio(children, working) * 100,
            "old_age_dependency_ratio": _safe_ratio(elderly, working) * 100,
            "sex_ratio": _safe_ratio(males, females) * 100,  # males per 100 females
            "median_age": _grouped_median_age(sub),
        }
        if keys:
            rec.update(dict(zip(keys, key if isinstance(key, tuple) else (key,))))
        records.append(rec)

    cols = (keys or []) + [
        "population", "children", "working_age", "elderly",
        "pct_children", "pct_working_age", "pct_elderly",
        "age_dependency_ratio", "child_dependency_ratio",
        "old_age_dependency_ratio", "sex_ratio", "median_age",
    ]
    return pd.DataFrame.from_records(records)[cols]


def _safe_pct(part: float, whole: float) -> float:
    return float(100.0 * part / whole) if whole else 0.0


def _safe_ratio(a: float, b: float) -> float:
    return float(a / b) if b else np.nan
