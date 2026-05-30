"""Fast zonal aggregation of population rasters by administrative district.

Why this is fast: all age/sex rasters for a country share an identical grid, so
we rasterize the district polygons into an integer label grid once per country
and then reduce every raster with a single ``np.bincount`` group-sum. That turns
N polygon-mask operations per file into one vectorised pass, which is O(pixels)
no matter how many districts or files there are. (If sub-pixel exactness ever
matters, ``exactextract`` could drop in here; at 1 km the centroid rule used
below is standard practice.)
"""
from __future__ import annotations

from dataclasses import dataclass

import geopandas as gpd
import numpy as np
import rasterio
from rasterio.features import rasterize


@dataclass(frozen=True)
class Grid:
    """The georeferencing of a raster: affine transform, pixel size and CRS."""

    transform: rasterio.Affine
    width: int
    height: int
    crs: object

    @classmethod
    def from_raster(cls, path) -> "Grid":
        """Read the grid definition from a raster file."""
        with rasterio.open(path) as src:
            return cls(src.transform, src.width, src.height, src.crs)

    def matches(self, path) -> bool:
        """True if ``path`` has the same size and transform as this grid."""
        with rasterio.open(path) as src:
            return (
                src.width == self.width
                and src.height == self.height
                and src.transform.almost_equals(self.transform)
            )


def rasterize_districts(
    gdf: gpd.GeoDataFrame, grid: Grid
) -> tuple[np.ndarray, list[str]]:
    """Burn districts onto ``grid``; return (label array, ordered gid_2 list).

    Label 0 means "no district"; district ``i`` burns value ``i + 1``.
    Districts are reprojected to the raster CRS if they differ.
    """
    if grid.crs is not None and gdf.crs is not None and gdf.crs != grid.crs:
        gdf = gdf.to_crs(grid.crs)

    gids = gdf["gid_2"].tolist()
    shapes = ((geom, idx + 1) for idx, geom in enumerate(gdf.geometry))
    labels = rasterize(
        shapes,
        out_shape=(grid.height, grid.width),
        transform=grid.transform,
        fill=0,
        dtype="int32",
        all_touched=False,
    )
    return labels, gids


def zonal_sum(path, labels: np.ndarray, n_districts: int) -> np.ndarray:
    """Sum raster values within each district label.

    Returns an array of length ``n_districts``; index ``i`` is the total for the
    district that burned label ``i + 1``. Nodata, non-finite and negative cells
    (WorldPop encodes "no population" with a large negative sentinel) are zeroed.
    """
    with rasterio.open(path) as src:
        data = src.read(1).astype("float64")
        nodata = src.nodata
    valid = np.isfinite(data) & (data >= 0)
    if nodata is not None:
        valid &= data != nodata
    weights = np.where(valid, data, 0.0)

    # bincount over labels 0..n; drop bucket 0 ("no district").
    sums = np.bincount(
        labels.ravel(), weights=weights.ravel(), minlength=n_districts + 1
    )
    return sums[1 : n_districts + 1]
