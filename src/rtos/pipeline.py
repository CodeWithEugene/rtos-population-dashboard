"""End-to-end pipeline: WorldPop rasters + GADM districts -> tidy table.

Run it with::

    python -m rtos.pipeline            # all countries in config.yaml
    python -m rtos.pipeline --countries KEN
    python -m rtos.pipeline --force    # ignore cache, re-download

Outputs (under ``data/processed``):
    population_districts.parquet   long tidy table (the dashboard's input)
    indicators_districts.parquet   one row of indicators per district
    summary_country.csv            human-readable country roll-up
    districts_<ISO>.geojson        simplified boundaries for the map
"""
from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

import pandas as pd
import requests

from .boundaries import load_boundaries, write_simplified_geojson
from .catalog import RasterItem, build_catalog
from .config import Config, Country, load_config
from .fetch import fetch_many, make_session
from .indicators import summarise
from .zonal import Grid, rasterize_districts, zonal_sum

TIDY_NAME = "population_districts.parquet"
INDICATORS_NAME = "indicators_districts.parquet"
SUMMARY_NAME = "summary_country.csv"


def _log(msg: str) -> None:
    print(f"[rtos] {msg}", flush=True)


def _country_items(items: list[RasterItem], iso: str) -> list[RasterItem]:
    return [it for it in items if it.country.iso == iso]


def process_country(
    country: Country,
    items: list[RasterItem],
    cfg: Config,
    session: requests.Session,
) -> tuple[pd.DataFrame, "gpd.GeoDataFrame"]:  # noqa: F821
    """Aggregate every raster for one country to district-level population."""
    import geopandas as gpd  # local import keeps module import light

    _log(f"{country.iso}: loading GADM L2 districts")
    gdf = load_boundaries(country, cfg, session=session)
    n = len(gdf)

    # Build the label grid once from the first raster; reuse across all files
    # that share the grid (the common case), recompute only if one differs.
    first = items[0].local_path
    grid = Grid.from_raster(first)
    labels, gids = rasterize_districts(gdf, grid)
    _log(f"{country.iso}: {n} districts rasterized onto {grid.width}x{grid.height} grid")

    base = gdf[["country_iso", "country", "gid_2", "adm1", "adm2"]].copy()
    base = base.set_index("gid_2").loc[gids].reset_index()  # align to label order

    frames: list[pd.DataFrame] = []
    for it in items:
        if grid.matches(it.local_path):
            lab, ids = labels, gids
        else:  # rare: a file on a different grid — rasterize to its own grid
            g2 = Grid.from_raster(it.local_path)
            lab, ids = rasterize_districts(gdf, g2)
        sums = zonal_sum(it.local_path, lab, len(ids))

        f = base.copy()
        f["sex"] = it.sex_label
        f["age_code"] = it.band.code
        f["age_label"] = it.band.label
        f["age_low"] = it.band.low
        f["age_high"] = it.band.high
        f["population"] = sums
        frames.append(f)

    tidy = pd.concat(frames, ignore_index=True)
    tidy["population"] = tidy["population"].round(2)
    return tidy, gdf


def run(
    cfg: Config | None = None,
    countries: list[str] | None = None,
    force: bool = False,
    progress: bool = True,
) -> pd.DataFrame:
    """Execute the full pipeline and write all processed artefacts."""
    t0 = time.time()
    cfg = cfg or load_config()
    cfg.processed_dir.mkdir(parents=True, exist_ok=True)

    catalog = build_catalog(cfg)
    selected = [c for c in cfg.countries if not countries or c.iso in countries]
    if not selected:
        raise SystemExit(f"No matching countries for {countries!r}")

    wanted = [it for it in catalog if it.country in selected]
    _log(f"Fetching {len(wanted)} rasters (cached when possible)…")
    fetch_many([(it.url, it.local_path) for it in wanted], force=force, progress=progress)

    session = make_session()
    all_tidy: list[pd.DataFrame] = []
    try:
        for country in selected:
            items = _country_items(wanted, country.iso)
            tidy, gdf = process_country(country, items, cfg, session)
            all_tidy.append(tidy)

            geo_out = cfg.processed_dir / f"districts_{country.iso}.geojson"
            write_simplified_geojson(gdf, geo_out, cfg.gadm["simplify_tolerance"])
            _log(f"{country.iso}: wrote {geo_out.name}")
    finally:
        session.close()

    tidy = pd.concat(all_tidy, ignore_index=True)

    # ---- write artefacts -------------------------------------------------
    tidy_path = cfg.processed_dir / TIDY_NAME
    tidy.to_parquet(tidy_path, index=False)
    _log(f"Wrote {tidy_path} ({len(tidy):,} rows)")

    ind = summarise(tidy, by=["country_iso", "country", "gid_2", "adm1", "adm2"])
    ind.to_parquet(cfg.processed_dir / INDICATORS_NAME, index=False)

    country_sum = summarise(tidy, by=["country_iso", "country"])
    country_sum.to_csv(cfg.processed_dir / SUMMARY_NAME, index=False)

    _log("Country totals:")
    for _, r in country_sum.iterrows():
        _log(
            f"  {r['country']:<8} pop={r['population']:>14,.0f}  "
            f"child={r['pct_children']:.1f}%  working={r['pct_working_age']:.1f}%  "
            f"elderly={r['pct_elderly']:.1f}%  dep={r['age_dependency_ratio']:.0f}"
        )
    _log(f"Done in {time.time() - t0:.1f}s")
    return tidy


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="WorldPop age/sex population pipeline")
    p.add_argument("--config", type=Path, default=None, help="Path to config.yaml")
    p.add_argument("--countries", nargs="*", help="ISO3 subset, e.g. KEN UGA")
    p.add_argument("--force", action="store_true", help="Ignore cache, re-download")
    p.add_argument("--no-progress", action="store_true", help="Disable progress bars")
    args = p.parse_args(argv)

    cfg = load_config(args.config) if args.config else load_config()
    run(
        cfg,
        countries=[c.upper() for c in args.countries] if args.countries else None,
        force=args.force,
        progress=not args.no_progress,
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
