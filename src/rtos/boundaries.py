"""GADM Level-2 administrative boundaries (districts).

Downloads the zipped GeoJSON, loads it, and normalises the columns the rest of
the pipeline relies on: ``gid_2`` (stable id), ``adm1`` (region/province) and
``adm2`` (district). Geometries are kept full-resolution for zonal statistics;
a separately-simplified copy is written for the dashboard map so the browser
stays responsive.
"""
from __future__ import annotations

import zipfile
from pathlib import Path

import geopandas as gpd
import requests

from .config import Config, Country, load_config
from .fetch import fetch_file

# GADM standard column names -> our tidy names.
_RENAME = {"GID_2": "gid_2", "NAME_1": "adm1", "NAME_2": "adm2", "GID_0": "iso"}


def _extract_json(zip_path: Path) -> Path:
    """Extract the single GeoJSON from a GADM .json.zip next to the archive."""
    with zipfile.ZipFile(zip_path) as zf:
        members = [n for n in zf.namelist() if n.lower().endswith(".json")]
        if not members:
            raise ValueError(f"No .json found inside {zip_path}")
        target = zip_path.parent / Path(members[0]).name
        if not target.exists():
            zf.extract(members[0], path=zip_path.parent)
            # Flatten in case the archive stored a nested path.
            extracted = zip_path.parent / members[0]
            if extracted != target:
                extracted.replace(target)
        return target


def load_boundaries(
    country: Country,
    cfg: Config | None = None,
    session: requests.Session | None = None,
) -> gpd.GeoDataFrame:
    """Fetch (cached) and load GADM L2 districts for one country, normalised."""
    cfg = cfg or load_config()
    dest = cfg.raw_dir / "gadm" / cfg.gadm_filename(country)
    fetch_file(cfg.gadm_url(country), dest, session=session)
    gdf = gpd.read_file(_extract_json(dest))

    keep = {k: v for k, v in _RENAME.items() if k in gdf.columns}
    gdf = gdf.rename(columns=keep)
    gdf["country_iso"] = country.iso
    gdf["country"] = country.name
    if gdf.crs is None:  # GADM ships WGS84; assert it explicitly.
        gdf = gdf.set_crs(4326)

    cols = ["country_iso", "country", "gid_2", "adm1", "adm2", "geometry"]
    return gdf[[c for c in cols if c in gdf.columns]].reset_index(drop=True)


def write_simplified_geojson(
    gdf: gpd.GeoDataFrame, out_path: Path, tolerance: float
) -> Path:
    """Write a topology-light GeoJSON copy for the dashboard choropleth."""
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.unlink(missing_ok=True)  # GeoJSON driver won't overwrite in place
    slim = gdf.copy()
    slim["geometry"] = slim.geometry.simplify(tolerance, preserve_topology=True)
    slim.to_file(out_path, driver="GeoJSON")
    return out_path
