"""Unit tests for the pipeline's pure logic.

These run fully offline (no network, no downloads): config/metadata parsing,
indicator arithmetic, and the rasterized zonal reduction on a synthetic grid.
"""
from __future__ import annotations

import geopandas as gpd
import numpy as np
import pandas as pd
import pytest
from rasterio.transform import from_origin
from shapely.geometry import box

from rtos.catalog import build_catalog, parse_filename
from rtos.config import load_config
from rtos.indicators import summarise
from rtos.zonal import Grid, rasterize_districts, zonal_sum


# --------------------------------------------------------------------------- #
# Config & metadata                                                            #
# --------------------------------------------------------------------------- #
def test_age_bands_are_well_formed():
    cfg = load_config()
    bands = {b.code: b for b in cfg.age_bands}
    assert bands[0].label == "<1" and bands[0].low == 0 and bands[0].high == 0
    assert bands[1].label == "1-4" and bands[1].high == 4
    assert bands[5].label == "5-9"
    assert bands[90].label == "90+"            # open top band
    assert bands[5].file_token == "05"         # zero-padded


def test_url_and_filename_construction():
    cfg = load_config()
    ken = next(c for c in cfg.countries if c.iso == "KEN")
    band = next(b for b in cfg.age_bands if b.code == 0)
    fname = cfg.raster_filename(ken, "f", band)
    assert fname == "ken_f_00_2025_CN_1km_R2025A_UA_v1.tif"
    assert cfg.raster_url(ken, "f", band).endswith(
        "KEN/v1/1km_ua/constrained/" + fname
    )


def test_parse_filename_roundtrip():
    meta = parse_filename("uga_m_45_2025_CN_1km_R2025A_UA_v1.tif")
    assert meta == {"iso": "UGA", "sex": "m", "age_code": 45, "year": 2025}


def test_parse_filename_rejects_garbage():
    with pytest.raises(ValueError):
        parse_filename("not_a_worldpop_file.tif")


def test_catalog_size_matches_config():
    cfg = load_config()
    cat = build_catalog(cfg)
    expected = len(cfg.countries) * len(cfg.sexes) * len(cfg.age_bands)
    assert len(cat) == expected


# --------------------------------------------------------------------------- #
# Indicators                                                                   #
# --------------------------------------------------------------------------- #
def _toy_frame() -> pd.DataFrame:
    # 100 children, 300 working-age, 100 elderly; sexes balanced.
    rows = [
        # (age_code, age_low, age_high, sex, pop)
        (0, 0, 0, "male", 25), (0, 0, 0, "female", 25),
        (5, 5, 9, "male", 25), (5, 5, 9, "female", 25),
        (30, 30, 34, "male", 75), (30, 30, 34, "female", 75),
        (40, 40, 44, "male", 75), (40, 40, 44, "female", 75),
        (70, 70, 74, "male", 50), (70, 70, 74, "female", 50),
    ]
    return pd.DataFrame(rows, columns=["age_code", "age_low", "age_high", "sex", "population"])


def test_indicator_math():
    out = summarise(_toy_frame()).iloc[0]
    assert out["population"] == 500
    assert out["pct_children"] == pytest.approx(20.0)       # 100/500
    assert out["pct_working_age"] == pytest.approx(60.0)    # 300/500
    assert out["pct_elderly"] == pytest.approx(20.0)        # 100/500
    # dependents 200 / working 300 * 100
    assert out["age_dependency_ratio"] == pytest.approx(200 / 300 * 100)
    assert out["sex_ratio"] == pytest.approx(100.0)         # balanced
    assert 30 <= out["median_age"] <= 40                    # mass centred mid-life


# --------------------------------------------------------------------------- #
# Zonal core (synthetic raster, no network)                                   #
# --------------------------------------------------------------------------- #
def test_zonal_sum_partitions_population(tmp_path):
    import rasterio

    # 4x4 grid, 1-degree pixels, top-left origin at (0, 4). Every cell = 1.
    transform = from_origin(0, 4, 1, 1)
    arr = np.ones((4, 4), dtype="float32")
    path = tmp_path / "toy.tif"
    with rasterio.open(
        path, "w", driver="GTiff", height=4, width=4, count=1,
        dtype="float32", crs="EPSG:4326", transform=transform, nodata=-99999,
    ) as dst:
        dst.write(arr, 1)

    # Two districts splitting the grid into left (x<2) and right halves.
    gdf = gpd.GeoDataFrame(
        {"gid_2": ["LEFT", "RIGHT"]},
        geometry=[box(0, 0, 2, 4), box(2, 0, 4, 4)],
        crs="EPSG:4326",
    )
    grid = Grid.from_raster(path)
    labels, gids = rasterize_districts(gdf, grid)
    sums = zonal_sum(path, labels, len(gids))

    assert gids == ["LEFT", "RIGHT"]
    # Each half is 2 columns x 4 rows = 8 cells of value 1.
    assert sums.tolist() == [8.0, 8.0]


def test_zonal_sum_ignores_nodata(tmp_path):
    import rasterio

    transform = from_origin(0, 2, 1, 1)
    arr = np.array([[5, -99999], [3, 2]], dtype="float32")
    path = tmp_path / "nd.tif"
    with rasterio.open(
        path, "w", driver="GTiff", height=2, width=2, count=1,
        dtype="float32", crs="EPSG:4326", transform=transform, nodata=-99999,
    ) as dst:
        dst.write(arr, 1)

    gdf = gpd.GeoDataFrame(
        {"gid_2": ["ALL"]}, geometry=[box(0, 0, 2, 2)], crs="EPSG:4326"
    )
    grid = Grid.from_raster(path)
    labels, gids = rasterize_districts(gdf, grid)
    sums = zonal_sum(path, labels, len(gids))
    assert sums.tolist() == [10.0]   # 5 + 3 + 2, nodata skipped
