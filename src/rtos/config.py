"""Loads config.yaml and exposes it as typed objects, so nothing else in the
code hard-codes a URL, age band or country. Add a country by editing the YAML.
"""
from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

import yaml

# Repository root = two levels up from this file (src/rtos/config.py -> repo).
REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_CONFIG_PATH = REPO_ROOT / "config.yaml"


@dataclass(frozen=True)
class Country:
    iso: str          # e.g. "KEN"
    name: str         # e.g. "Kenya"

    @property
    def iso_lower(self) -> str:
        return self.iso.lower()


@dataclass(frozen=True)
class AgeBand:
    """A single WorldPop 5-year age class, keyed by its lower-bound code."""

    code: int         # 0, 1, 5, 10, ... 90
    low: int          # inclusive lower age
    high: int         # inclusive upper age (capped at 120 for the open band)
    label: str        # human label, e.g. "5-9", "<1", "90+"

    @property
    def file_token(self) -> str:
        """Two-digit zero-padded token used in WorldPop filenames (00, 01, 05)."""
        return f"{self.code:02d}"


def _build_age_bands(codes: list[int]) -> list[AgeBand]:
    """Turn the list of lower-bound codes into fully described age bands."""
    ordered = sorted(codes)
    bands: list[AgeBand] = []
    for i, code in enumerate(ordered):
        is_last = i == len(ordered) - 1
        if code == 0:
            low, high, label = 0, 0, "<1"
        elif is_last:
            # Open-ended top band (e.g. 90+).
            low, high, label = code, 120, f"{code}+"
        else:
            nxt = ordered[i + 1]
            low, high = code, nxt - 1
            label = f"{low}-{high}"
        bands.append(AgeBand(code=code, low=low, high=high, label=label))
    return bands


@dataclass(frozen=True)
class Config:
    raw_config: dict
    config_path: Path

    # ---- paths -----------------------------------------------------------
    @property
    def data_dir(self) -> Path:
        return self._resolve(self.raw_config["paths"]["data_dir"])

    @property
    def raw_dir(self) -> Path:
        return self._resolve(self.raw_config["paths"]["raw"])

    @property
    def processed_dir(self) -> Path:
        return self._resolve(self.raw_config["paths"]["processed"])

    def _resolve(self, rel: str) -> Path:
        p = Path(rel)
        return p if p.is_absolute() else (REPO_ROOT / p)

    # ---- domain ----------------------------------------------------------
    @property
    def countries(self) -> list[Country]:
        return [Country(**c) for c in self.raw_config["countries"]]

    @property
    def age_bands(self) -> list[AgeBand]:
        return _build_age_bands(self.raw_config["age_codes"])

    @property
    def sexes(self) -> list[str]:
        return list(self.raw_config["worldpop"]["sexes"])

    @property
    def worldpop(self) -> dict:
        return self.raw_config["worldpop"]

    @property
    def gadm(self) -> dict:
        return self.raw_config["gadm"]

    # ---- URL / filename builders ----------------------------------------
    def raster_filename(self, country: Country, sex: str, band: AgeBand) -> str:
        return self.worldpop["filename_template"].format(
            iso=country.iso_lower, sex=sex, age=band.file_token
        )

    def raster_url(self, country: Country, sex: str, band: AgeBand) -> str:
        wp = self.worldpop
        return "/".join(
            [
                wp["base_url"].rstrip("/"),
                country.iso,
                wp["version"],
                wp["resolution_dir"],
                self.raster_filename(country, sex, band),
            ]
        )

    def gadm_filename(self, country: Country) -> str:
        return self.gadm["filename_template"].format(
            iso=country.iso, level=self.gadm["level"]
        )

    def gadm_url(self, country: Country) -> str:
        return f"{self.gadm['base_url'].rstrip('/')}/{self.gadm_filename(country)}"


@lru_cache(maxsize=None)
def load_config(path: str | Path | None = None) -> Config:
    """Load and cache the project configuration."""
    cfg_path = Path(path) if path else DEFAULT_CONFIG_PATH
    with open(cfg_path, "r", encoding="utf-8") as fh:
        raw = yaml.safe_load(fh)
    return Config(raw_config=raw, config_path=cfg_path)
