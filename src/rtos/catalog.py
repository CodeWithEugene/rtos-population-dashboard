"""Maps config (countries, sexes, age bands) to the actual files on the WorldPop
server, and back: enumerate every raster to fetch, or recover the metadata from
a filename. That two-way mapping keeps the rest of the pipeline declarative.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from .config import AgeBand, Config, Country, load_config

# ken_f_00_2025_CN_1km_R2025A_UA_v1.tif  ->  iso, sex, age code
_FILENAME_RE = re.compile(
    r"^(?P<iso>[a-z]{3})_(?P<sex>[fmt])_(?P<age>\d{2})_(?P<year>\d{4})_", re.IGNORECASE
)


@dataclass(frozen=True)
class RasterItem:
    """One downloadable raster and everything needed to place it in the table."""

    country: Country
    sex: str            # "f" or "m"
    band: AgeBand
    url: str
    local_path: Path
    filename: str

    @property
    def sex_label(self) -> str:
        return {"f": "female", "m": "male", "t": "total"}[self.sex]


def build_catalog(cfg: Config | None = None) -> list[RasterItem]:
    """Enumerate every raster the pipeline should ingest, for all countries."""
    cfg = cfg or load_config()
    items: list[RasterItem] = []
    for country in cfg.countries:
        for sex in cfg.sexes:
            for band in cfg.age_bands:
                fname = cfg.raster_filename(country, sex, band)
                items.append(
                    RasterItem(
                        country=country,
                        sex=sex,
                        band=band,
                        url=cfg.raster_url(country, sex, band),
                        local_path=cfg.raw_dir / "worldpop" / country.iso / fname,
                        filename=fname,
                    )
                )
    return items


def parse_filename(filename: str) -> dict:
    """Recover ``{iso, sex, age_code, year}`` from a WorldPop filename.

    Raises ``ValueError`` on an unexpected name, so a mislabelled file can't
    slip silently into the table.
    """
    m = _FILENAME_RE.match(Path(filename).name)
    if not m:
        raise ValueError(f"Unrecognised WorldPop filename: {filename!r}")
    return {
        "iso": m.group("iso").upper(),
        "sex": m.group("sex").lower(),
        "age_code": int(m.group("age")),
        "year": int(m.group("year")),
    }
