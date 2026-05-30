"""WorldPop 2025 dashboard for Kenya & Uganda.

Reads the pipeline's tidy outputs (never the rasters, so it's instant) and lets
you filter by country, age and sex. Run: ``streamlit run app/dashboard.py``.
"""
from __future__ import annotations

import json
import math
import sys
from pathlib import Path

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

# Make the local package importable when run via `streamlit run`.
REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "src"))

from rtos.config import load_config  # noqa: E402
from rtos.indicators import summarise  # noqa: E402

st.set_page_config(
    page_title="WorldPop 2025: Kenya & Uganda",
    page_icon="🌍",
    layout="wide",
)

# Hide the "Made with Streamlit" footer and tighten the top padding. The
# theme/settings menu stays (via toolbarMode = "viewer" in config.toml).
st.markdown(
    """
    <style>
      footer {visibility: hidden;}
      [data-testid="stHeader"] {background: transparent;}
      .block-container {padding-top: 3.5rem !important;}  /* default ~6rem is too much */
    </style>
    """,
    unsafe_allow_html=True,
)

CFG = load_config()
PROCESSED = CFG.processed_dir
TIDY_PATH = PROCESSED / "population_districts.parquet"

# Stable colour identity per country, reused across every chart.
COUNTRY_COLOR = {"Kenya": "#1f78b4", "Uganda": "#33a02c"}
MALE_COLOR, FEMALE_COLOR = "#2c7fb8", "#dd3497"


# --------------------------------------------------------------------------- #
# Data loading (cached)                                                        #
# --------------------------------------------------------------------------- #
@st.cache_data(show_spinner=False)
def load_tidy() -> pd.DataFrame:
    return pd.read_parquet(TIDY_PATH)


@st.cache_data(show_spinner=False)
def load_geojson(isos: tuple[str, ...]) -> dict:
    """Merge the per-country simplified GeoJSON files into one collection."""
    features = []
    for iso in isos:
        path = PROCESSED / f"districts_{iso}.geojson"
        if path.exists():
            with open(path) as fh:
                features.extend(json.load(fh)["features"])
    return {"type": "FeatureCollection", "features": features}


def _ordered_age_labels(df: pd.DataFrame) -> list[str]:
    return (
        df.drop_duplicates("age_code")
        .sort_values("age_code")["age_label"]
        .tolist()
    )


# --------------------------------------------------------------------------- #
# Guard: data must be built first                                             #
# --------------------------------------------------------------------------- #
if not TIDY_PATH.exists():
    st.title("🌍 WorldPop 2025: Kenya & Uganda")
    st.warning(
        "Processed data not found. Build it first:\n\n"
        "```bash\nmake pipeline   # or: python -m rtos.pipeline\n```"
    )
    st.stop()

tidy = load_tidy()
ALL_AGE_LABELS = _ordered_age_labels(tidy)

# --------------------------------------------------------------------------- #
# Sidebar filters                                                              #
# --------------------------------------------------------------------------- #
st.sidebar.header("Filters")

country_opts = sorted(tidy["country"].unique())
countries = st.sidebar.multiselect("Country", country_opts, default=country_opts)

sex_choice = st.sidebar.radio("Sex", ["Both", "Female", "Male"], horizontal=True)
sex_map = {"Both": ["female", "male"], "Female": ["female"], "Male": ["male"]}
sexes = sex_map[sex_choice]

age_preset = st.sidebar.radio(
    "Age group", ["All ages", "Children (0-14)", "Working age (15-64)",
                  "Elderly (65+)", "Custom"],
)
preset_codes = {
    "Children (0-14)": {0, 1, 5, 10},
    "Working age (15-64)": {15, 20, 25, 30, 35, 40, 45, 50, 55, 60},
    "Elderly (65+)": {65, 70, 75, 80, 85, 90},
}
if age_preset == "Custom":
    chosen_labels = st.sidebar.multiselect(
        "Age bands", ALL_AGE_LABELS, default=ALL_AGE_LABELS
    )
    age_codes = set(
        tidy.loc[tidy["age_label"].isin(chosen_labels), "age_code"].unique()
    )
elif age_preset == "All ages":
    age_codes = set(tidy["age_code"].unique())
else:
    age_codes = preset_codes[age_preset]

st.sidebar.caption(
    "Data: WorldPop 2025 (R2025A, 1 km) · Boundaries: GADM 4.1 Level-2"
)

# --------------------------------------------------------------------------- #
# Apply filters                                                                #
# --------------------------------------------------------------------------- #
if not countries:
    st.info("Select at least one country.")
    st.stop()

mask = (
    tidy["country"].isin(countries)
    & tidy["sex"].isin(sexes)
    & tidy["age_code"].isin(age_codes)
)
view = tidy[mask]

# --------------------------------------------------------------------------- #
# Header + KPI cards                                                           #
# --------------------------------------------------------------------------- #
_n_districts = int(tidy["gid_2"].nunique())
_n_countries = int(tidy["country"].nunique())
_filter_summary = (
    f"{' + '.join(countries)} · {sex_choice} · "
    f"{'all ages' if len(age_codes) == len(ALL_AGE_LABELS) else age_preset}"
)
_pill = (
    "background:#eef2f7; color:#334155; padding:0.22rem 0.65rem;"
    "border-radius:999px; font-size:0.72rem; font-weight:600; letter-spacing:0.02em;"
)
st.markdown(
    f"""
    <div style="text-align:center; padding:0.25rem 0 0.5rem 0;">
      <div style="display:flex; gap:0.4rem; justify-content:center; flex-wrap:wrap;
                  margin-bottom:0.85rem;">
        <span style="{_pill}">WorldPop 2025 · R2025A · 1&nbsp;km</span>
        <span style="{_pill}">GADM L2 districts</span>
        <span style="{_pill}">{_n_countries} countries · {_n_districts} districts</span>
        <span style="{_pill}">EPSG:4326</span>
      </div>
      <div style="font-size:0.74rem; letter-spacing:0.2em; text-transform:uppercase;
                  color:#64748b; font-weight:700;">Public-health population intelligence</div>
      <h1 style="margin:0.25rem 0 0.15rem 0; font-size:2.1rem; line-height:1.2;">
        🌍 WorldPop 2025: Age &amp; Sex Population</h1>
      <div style="color:#475569; font-size:1rem; margin-bottom:0.35rem;">
        Age- and sex-structured population for Kenya &amp; Uganda, summarised to
        districts at 1&nbsp;km resolution.</div>
      <div style="color:#0f766e; font-weight:600; font-size:0.95rem;">
        {_filter_summary}</div>
    </div>
    """,
    unsafe_allow_html=True,
)

def _fmt(value: float, spec: str) -> str:
    """Format a metric, or "n/a" when a ratio is undefined (e.g. dependency
    ratio with only children selected, so no working-age denominator)."""
    return "n/a" if value is None or not math.isfinite(value) else format(value, spec)


ind = summarise(view).iloc[0]
c1, c2, c3, c4, c5 = st.columns(5)
c1.metric("Total population", _fmt(ind["population"], ",.0f"))
c2.metric("Children 0-14", _fmt(ind["pct_children"], ".1f") + "%")
c3.metric("Working age 15-64", _fmt(ind["pct_working_age"], ".1f") + "%")
c4.metric("Elderly 65+", _fmt(ind["pct_elderly"], ".1f") + "%")
c5.metric(
    "Age-dependency ratio",
    _fmt(ind["age_dependency_ratio"], ".0f"),
    help="Dependents (under-15 + 65+) per 100 working-age adults.",
)

# --------------------------------------------------------------------------- #
# Map + pyramid                                                                #
# --------------------------------------------------------------------------- #
left, right = st.columns([3, 2], gap="large")

with left:
    st.subheader("Population by district")
    geojson = load_geojson(tuple(sorted(tidy.loc[tidy["country"].isin(countries),
                                                 "country_iso"].unique())))
    by_district = (
        view.groupby(["gid_2", "adm2", "country"], as_index=False)["population"]
        .sum()
    )
    fig_map = go.Figure(
        go.Choroplethmap(
            geojson=geojson,
            locations=by_district["gid_2"],
            z=by_district["population"],
            featureidkey="properties.gid_2",
            colorscale="YlOrRd",
            marker_opacity=0.75,
            marker_line_width=0.2,
            colorbar_title="People",
            customdata=by_district[["adm2", "country"]],
            hovertemplate="<b>%{customdata[0]}</b> (%{customdata[1]})<br>"
            "%{z:,.0f} people<extra></extra>",
        )
    )
    # Centre on the two-country bounding region.
    fig_map.update_layout(
        map_style="carto-positron",
        map_zoom=4.4,
        map_center={"lat": 0.5, "lon": 33.5},
        margin={"r": 0, "t": 0, "l": 0, "b": 0},
        height=520,
    )
    st.plotly_chart(fig_map, width="stretch")

with right:
    st.subheader("Population pyramid")
    st.caption("Both sexes shown regardless of the sex filter, for comparison.")
    pyr_src = tidy[
        tidy["country"].isin(countries) & tidy["age_code"].isin(age_codes)
    ]
    pyr = (
        pyr_src.groupby(["age_code", "age_label", "sex"], as_index=False)["population"]
        .sum()
        .sort_values("age_code")
    )
    order = pyr.drop_duplicates("age_code")["age_label"].tolist()
    males = pyr[pyr["sex"] == "male"].set_index("age_label")["population"]
    females = pyr[pyr["sex"] == "female"].set_index("age_label")["population"]
    fig_pyr = go.Figure()
    fig_pyr.add_bar(
        y=order, x=[-males.get(a, 0) for a in order], name="Male",
        orientation="h", marker_color=MALE_COLOR,
        hovertemplate="Male %{y}: %{customdata:,.0f}<extra></extra>",
        customdata=[males.get(a, 0) for a in order],
    )
    fig_pyr.add_bar(
        y=order, x=[females.get(a, 0) for a in order], name="Female",
        orientation="h", marker_color=FEMALE_COLOR,
        hovertemplate="Female %{y}: %{x:,.0f}<extra></extra>",
    )
    fig_pyr.update_layout(
        barmode="relative", height=520, bargap=0.08,
        xaxis_title="Population", yaxis_title="Age band",
        legend={"orientation": "h", "y": 1.05},
        margin={"r": 10, "t": 10, "l": 10, "b": 10},
    )
    fig_pyr.update_xaxes(tickformat="~s")
    st.plotly_chart(fig_pyr, width="stretch")

# --------------------------------------------------------------------------- #
# Top districts + interpretation                                              #
# --------------------------------------------------------------------------- #
b1, b2 = st.columns([3, 2], gap="large")
with b1:
    st.subheader("Top 15 districts by population (current filter)")
    top = by_district.sort_values("population", ascending=False).head(15)
    fig_top = go.Figure(
        go.Bar(
            x=top["population"], y=top["adm2"], orientation="h",
            marker_color=[COUNTRY_COLOR.get(c, "#888") for c in top["country"]],
            hovertemplate="%{y}: %{x:,.0f}<extra></extra>",
        )
    )
    fig_top.update_layout(
        height=460, yaxis={"autorange": "reversed"},
        xaxis_title="People", margin={"r": 10, "t": 10, "l": 10, "b": 10},
    )
    fig_top.update_xaxes(tickformat="~s")
    st.plotly_chart(fig_top, width="stretch")

with b2:
    st.subheader("What this means")
    dep = ind["age_dependency_ratio"]
    dep_sentence = (
        f"The **age-dependency ratio of {dep:.0f}** means roughly {dep:.0f} "
        "dependents for every 100 working-age adults. "
        if math.isfinite(dep)
        else ""
    )
    st.markdown(
        f"""
For the current selection ({' + '.join(countries)}),
**{_fmt(ind['pct_children'], '.0f')}%** of people are children under 15 and
**{_fmt(ind['pct_elderly'], '.1f')}%** are 65+. {dep_sentence}

A young age structure like this concentrates demand on **maternal and child
health, immunisation and schooling**, and signals fast future growth in the
labour force. The choropleth highlights where people are concentrated, useful
for siting facilities and planning outbreak response and routine services.
        """
    )
    with st.expander("Indicator definitions & method"):
        st.markdown(
            """
- **Children / Working age / Elderly**: shares of population aged 0-14, 15-64, 65+.
- **Age-dependency ratio**: (children + elderly) ÷ working-age × 100.
- **Sex ratio**: males per 100 females.
- **Method**: each WorldPop 1 km raster is summed within GADM Level-2
  districts via a one-pass rasterized zonal reduction; *total* = male + female.
            """
        )

with st.expander("Preview the tidy data"):
    st.dataframe(
        view.sort_values("population", ascending=False).head(200),
        width="stretch", hide_index=True,
    )

# --------------------------------------------------------------------------- #
# Footer                                                                       #
# --------------------------------------------------------------------------- #
st.divider()
st.markdown(
    '<div style="text-align:center; color:#888; font-size:0.85rem; padding:0.5rem 0;">'
    'A <a href="https://codewitheugene.top/" target="_blank" rel="noopener noreferrer">'
    'CodeWithEugene</a> Creation'
    "</div>",
    unsafe_allow_html=True,
)
