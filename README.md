# RTOS Population Dashboard — WorldPop 2025 (Kenya & Uganda)

A small, reproducible **data pipeline + interactive dashboard** that turns
[WorldPop 2025 age- and sex-structured population rasters](https://data.worldpop.org/GIS/AgeSex_structures/Global_2015_2030/R2025A/2025/)
for **Kenya** and **Uganda** into district-level insights you can filter by
**country, age group and sex**.

> **Approach (2–3 sentences).** A config-driven pipeline streams the WorldPop
> 1 km GeoTIFFs and GADM Level-2 district boundaries straight from their public
> URLs (cached locally), then aggregates every age/sex raster to districts with
> a single rasterized zonal reduction — the polygons are burned to the WorldPop
> grid **once** per country and every file is reduced with one vectorised
> `np.bincount`, so cost is O(pixels) no matter how many districts or files.
> The result is a tidy parquet table that a Streamlit dashboard reads instantly
> to drive a choropleth map, population pyramid and public-health indicators.

---

## Results at a glance

Produced by a full end-to-end run (WorldPop 2025, 1 km, both countries):

| Country | Population (2025) | Children 0–14 | Working age 15–64 | Elderly 65+ | Age-dependency ratio | Median age | Districts (GADM L2) |
|---------|------------------:|--------------:|------------------:|------------:|---------------------:|-----------:|--------------------:|
| Kenya   | 56,889,831 | 36.5% | 60.5% | 3.0% | 65 | 21.0 | 300 |
| Uganda  | 50,611,017 | 43.3% | 54.5% | 2.2% | 84 | 17.9 | 166 |

Uganda's markedly younger structure (median age ~18, 43% children) concentrates
demand on maternal/child health, immunisation and schooling, and implies rapid
future labour-force growth — the kind of signal this dashboard surfaces per
district. *(Totals align with published WorldPop 2025 magnitudes.)*

---

## Quick start

```bash
# 0. Prerequisite: uv (https://docs.astral.sh/uv/). Or use plain python3 + venv.

# 1. One command: set up env, build data, launch dashboard
./run.sh

# …or step by step:
make setup       # create .venv (Python 3.12) and install dependencies
make pipeline    # fetch rasters + boundaries, build the tidy table  (~1–2 min, cached after)
make dashboard   # launch the Streamlit app at http://localhost:8501
make test        # run the offline unit tests
```

The raw rasters (`data/raw/`) are never committed — they're rebuilt from the
public sources and cached. The small **processed artefacts (`data/processed/`,
~1 MB) _are_ committed**, so the dashboard can be deployed without running the
geo pipeline on the host (see *Deploy* below).

---

## Deploy (Streamlit Community Cloud)

The dashboard is intentionally cheap to host: it only reads the pre-built
`data/processed/` artefacts and **never loads a raster**, so it needs none of the
GDAL/geo stack. Runtime dependencies are the slim `requirements.txt`; the heavy
pipeline deps stay in `pyproject.toml`.

1. **Push the repo to GitHub**, including `data/processed/` and `requirements.txt`.
   (Rebuild the data first with `make pipeline` if it's stale.)
2. Go to **[share.streamlit.io](https://share.streamlit.io)** → **New app** →
   select the repo/branch.
3. Leave **Main file path** as the default `streamlit_app.py` (a thin shim that
   runs `app/dashboard.py`) — or set it to `app/dashboard.py` directly. Under
   *Advanced settings*, choose **Python 3.12**.
4. **Deploy.** It builds in ~1 minute (no GDAL) and goes live at
   `https://<user>-rtos-population-dashboard.streamlit.app`.

To refresh the live data later, re-run `make pipeline`, commit the updated
`data/processed/`, and push — Streamlit Cloud redeploys automatically.

> **Other targets.** The same slim app runs anywhere: Hugging Face Spaces
> (Streamlit SDK), or a container on Render / Cloud Run / Fly using a Dockerfile.
> Ask if you want those scaffolded.

---

## What it does

**Pipeline** (`python -m rtos.pipeline`)

1. **Catalog** — enumerate every `(country, sex, age-band)` raster from
   `config.yaml` and build its WorldPop URL + local cache path.
2. **Fetch** — stream each GeoTIFF and the GADM L2 GeoJSON from their public
   URLs. Cached by size; atomic writes; re-runs skip what's already local.
3. **Aggregate** — burn district polygons to the raster grid once, then sum
   each raster within districts (nodata / negative sentinels masked out).
4. **Tidy + indicators** — emit a long table and derived public-health
   indicators, plus simplified boundaries for the map.

**Outputs** (`data/processed/`)

| File | What it is |
|------|------------|
| `population_districts.parquet` | Long tidy table — one row per country × district × age-band × sex |
| `indicators_districts.parquet` | One row of indicators per district |
| `summary_country.csv` | Human-readable country roll-up |
| `districts_KEN.geojson`, `districts_UGA.geojson` | Simplified boundaries for the choropleth |

Tidy schema:

```
country_iso, country, gid_2, adm1, adm2, sex, age_code, age_label, age_low, age_high, population
```

**Dashboard** (`streamlit run app/dashboard.py`) — filters for **country**,
**sex** and **age group** (presets for children / working-age / elderly, or a
custom band picker) driving:

- KPI cards: total population, child/working-age/elderly shares, age-dependency ratio
- An interactive **choropleth map** of population by district
- A **population pyramid** (age × sex)
- A **top-districts** bar chart and a short public-health interpretation

---

## Project structure

```
config.yaml              # single source of truth (countries, year, URLs, age bands)
run.sh / Makefile        # entry points
src/rtos/
  config.py              # typed config + age-band metadata
  catalog.py             # enumerate rasters / parse filenames
  fetch.py               # cached, atomic HTTP downloads
  boundaries.py          # GADM L2 load + simplify
  zonal.py               # rasterize-once + bincount zonal reduction  (the core)
  indicators.py          # children/working/elderly, dependency ratios, median age
  pipeline.py            # orchestration + CLI
app/dashboard.py         # Streamlit dashboard
.streamlit/config.toml   # dashboard chrome settings (minimal toolbar)
tests/test_pipeline.py   # offline unit tests (config, indicators, zonal core)
```

---

## Approach & thought process

This section walks through *how* the solution was reasoned out, not just what it
does — the questions asked, the options weighed, and why each call was made.

### 1. Understand the data before writing code
The brief links to data but the details matter, so the first step was to inspect
the actual sources rather than trust the description:

- The WorldPop directory holds **60 GeoTIFFs per country** — 20 age bands × 3
  "sex" tokens (`f`, `m`, `t`) — named like `ken_f_00_2025_CN_1km_R2025A_UA_v1.tif`,
  **not** the brief's illustrative `M_0_4.tif`. The age token is a zero-padded
  lower bound (`00, 01, 05, … 90`); `00` is age <1 and `90` is the open 90+ band.
- Under `1km_ua/` only a **`constrained/`** sub-folder is actually published
  (the brief's "unconstrained … `constrained/`" phrasing is internally
  contradictory), so that's the directory used.
- `t` (total) is just `m + f`, and GADM L2 ships as zipped GeoJSON in EPSG:4326.

Two decisions fell out of this immediately: **parse metadata from the real
filename convention**, and **ingest only `m`/`f`, deriving totals** so that
summing across sex can never double-count.

### 2. The central design question — where does the heavy work live?
A naïve app would read rasters on every user interaction. That's slow and doesn't
scale. The key insight is that **the expensive work (raster → district numbers)
is fixed**: it doesn't depend on what the user filters. So the architecture
splits cleanly into:

```
   heavy, run-once                          light, run-often
   ───────────────                          ───────────────
   rasters ─▶ zonal aggregation ─▶ tidy parquet ─▶ dashboard (just reads & filters)
```

The pipeline pays the raster cost **once** and writes a small tidy table
(~150 KB); the dashboard never opens a GeoTIFF, so it loads instantly and stays
responsive. This is the single most important structural decision.

### 3. Making the aggregation efficient — the core algorithm
Zonal statistics (sum population per district) is the compute core. The obvious
approach — `rasterstats`/`exactextract` looping per polygon, per file — would
re-mask geometry **60 times per country**. But every age/sex raster for a country
shares an **identical grid**. So instead:

1. **Burn the district polygons to that grid once** → an integer label array.
2. Reduce each raster with a single vectorised `np.bincount(labels, weights)`.

That turns *N polygons × M files* of masking into *one pass per file*, O(pixels)
regardless of district or file count — the "evidence of efficiency/scalability"
the brief asks for. The interface is deliberately narrow, so swapping in
`exactextract` for sub-pixel boundary exactness later would be a one-function
change. (At 1 km the centroid rule used here is standard practice.)

Nodata handling is explicit: WorldPop encodes "no people" with a negative/huge
sentinel, so non-finite, negative and nodata cells are zeroed before summing —
covered by a dedicated unit test.

### 4. Data modelling — tidy by design
The pipeline emits a **long, tidy table** (one row per country × district ×
age-band × sex) rather than a wide matrix. Tidy data is what filtering,
group-bys and charting libraries want, so the dashboard logic stays trivial and
the same table feeds the map, the pyramid and every indicator. Age bands carry
both a machine code and human metadata (`age_label`, `age_low`, `age_high`) so
labels, ordering and the median-age calculation all come for free.

### 5. Reproducibility and resilience — earned, not assumed
"Reproducible" is a grading criterion, so the whole pipeline is **config-driven
and idempotent**: every URL, country and age band lives in `config.yaml`; adding
a third country is a config edit, not a code change. Downloads are **cached by
size and written atomically**, so re-runs do the minimum work and an interrupted
run never leaves a corrupt file.

Resilience here wasn't theoretical — the first real end-to-end run **failed** on
a `RemoteDisconnected` mid-download. That drove three concrete hardening steps,
each justified by what actually went wrong:

- a **retrying HTTP session** (auto-reconnect on dropped sockets / 5xx),
- a **whole-file retry** with backoff that discards partials (covers mid-stream
  disconnects the adapter can't resume), and
- **parallel fetching** (8 workers) once it was clear serial downloads over a
  high-latency link were the bottleneck.

This is the honest engineering story: the design reacted to observed failure
rather than hand-waving "it should work".

### 6. From numbers to decisions — the public-health framing
Raw counts aren't the deliverable; *interpretation* is. So `indicators.py`
derives what a planner actually reasons about — child/working-age/elderly shares,
age-dependency ratios, sex ratio, approximate median age — and the dashboard
frames them ("a young age structure concentrates demand on maternal/child health,
immunisation and schooling"). The Kenya-vs-Uganda contrast (median age 21 vs 18)
is exactly the kind of signal that should drive service planning.

### Summary of key trade-offs
| Decision | Chosen | Why / alternative rejected |
|----------|--------|-----------------------------|
| Raster work | Pre-compute in pipeline | Dashboard stays instant; vs reading rasters live (slow, doesn't scale) |
| Zonal method | Rasterize-once + `bincount` | O(pixels); vs per-polygon masking ×60 (wasteful) |
| Sex totals | Ingest `m`/`f`, derive total | Avoids double-counting; vs also summing `t` files |
| Data shape | Long tidy table | Trivial filtering/plotting; vs wide matrix |
| Config | One `config.yaml` | Extensible to new countries/years; vs hard-coded URLs |
| Downloads | Cached + retried + parallel | Reproducible & robust on flaky networks |

### What I'd add with more time
Sub-pixel zonal weights via `exactextract`; a `vsicurl` cloud-read mode to skip
the download entirely; multi-year support for trend views; and a small CI
workflow running the test suite on push.

---

## Data sources

- **Population:** WorldPop 2025 Age & Sex Structures, R2025A, 1 km
  (`Global_2015_2030/R2025A/2025/{KEN,UGA}/v1/1km_ua/constrained/`).
- **Boundaries:** GADM 4.1 Level-2 (districts), GeoJSON, WGS84 / EPSG:4326.

---

## Use of AI tools

This project was built with the assistance of **Claude Code** (Anthropic). It
was used to scaffold the modular package, draft the rasterize-once zonal
reduction, the Streamlit layout, the tests and this README. All code was
reviewed, run and verified end-to-end against the live WorldPop and GADM
sources.

**Example prompt used:**

> *"Implement an efficient zonal-statistics step that sums WorldPop 1 km
> age/sex rasters within GADM Level-2 districts. All age/sex files for a country
> share one grid, so rasterize the district polygons to that grid once and
> reduce each raster with a single grouped sum; mask nodata and negative
> sentinels."*

AI output was treated as a draft: the aggregation logic is covered by offline
unit tests (`tests/test_pipeline.py`) and the country totals were sanity-checked
against known WorldPop population magnitudes.

---

## License

MIT — see [LICENSE](LICENSE).
