import streamlit as st
import requests
import pandas as pd
import plotly.express as px

st.set_page_config(layout="wide", page_title="Energy Monitor")

st.title("Energy Monitor ⚡")

@st.cache_data(ttl=3600) # Cache für 1 Stunde, damit wir nicht bei jedem Refresh die API bombardieren
def fetch_series(filter_id):
    region = "DE"
    resolution = "hour"

    # --- Call 1: INDEX ---
    index_url = f"https://www.smard.de/app/chart_data/{filter_id}/{region}/index_{resolution}.json"
    try:
        index_response = requests.get(index_url, timeout=10)
        index_response.raise_for_status()
        index_data = index_response.json()
    except (requests.RequestException, ValueError) as e:
        st.error(f"Konnte Index-Daten für Filter {filter_id} nicht laden: {e}")
        st.stop()
    last_ts = index_data['timestamps'][-4:]  # nur die letzten 4 Wochen-Blöcke -> begrenzt Zeitraum-Slider auf ~4 Wochen

    frames = []                                        # leere Sammelliste
    for ts in last_ts:                         # über jeden Timestamp einzeln
        data_url = f"https://www.smard.de/app/chart_data/{filter_id}/{region}/{filter_id}_{region}_{resolution}_{ts}.json"
        try:
            data_response = requests.get(data_url, timeout=10)
            data_response.raise_for_status()
            series_data = data_response.json()
        except (requests.RequestException, ValueError) as e:
            st.error(f"Konnte Daten für Filter {filter_id} (Zeitstempel {ts}) nicht laden: {e}")
            st.stop()
        df_part = pd.DataFrame(series_data["series"], columns=["timestamp", "value"]).dropna()
        frames.append(df_part)                         # diesen Wochen-Teil sammeln

    df = pd.concat(frames)                              # alle 4 Wochen untereinander stapeln
    df["timestamp"] = (
        pd.to_datetime(df["timestamp"], unit="ms", utc=True)
          .dt.tz_convert("Europe/Berlin")
    )
    return df


RENEWABLE_SOURCES = {
    "Solar": 4068,
    "Wind Onshore": 4067,
    "Wind Offshore": 1225,
    "Biomasse": 4066,
    "Wasserkraft": 1226,
    # "Sonstige Erneuerbare": 1228,   # erstmal weglassen, kümmern wir uns später drum
}
FOSSIL_SOURCES = {
    "Erdgas": 4071,
    "Steinkohle": 4069,
    "Braunkohle": 1223,
}
COLORS = {
    "Solar (MW)": "#f9d71c",        # gelb (Sonne)
    "Wind Onshore (MW)": "#1f77b4", # blau
    "Wind Offshore (MW)": "#17becf",# türkis
    "Biomasse (MW)": "#2ca02c",     # grün
    "Wasserkraft (MW)": "#1fa8a8",  # blaugrün
    "Erdgas (MW)": "#ff7f0e",       # orange
    "Steinkohle (MW)": "#7f7f7f",   # grau
    "Braunkohle (MW)": "#8c564b",   # braun
}
COLORS_PCT = {key.replace(" (MW)", " (%)"): value for key, value in COLORS.items()}

ALL_SOURCES = {**RENEWABLE_SOURCES, **FOSSIL_SOURCES}

GRANULARITY = {
    "Stunde": "h",
    "Tag": "D",
    "Woche": "W",
}

def renewable_share(renewable_total, fossil_total):
    total = renewable_total + fossil_total
    if total == 0:
        return 0
    return renewable_total / total

merged = None
for name, source_id in ALL_SOURCES.items():
    df = fetch_series(source_id)
    df = df.rename(columns={"value": f"{name} (MW)"})
    if merged is None:
        merged = df
    else:
        merged = pd.merge(merged, df, on="timestamp")

verbrauch = fetch_series(410)

merged = merged.set_index("timestamp")
verbrauch = verbrauch.set_index("timestamp")

last_update = merged.index[-1]

min_date = merged.index.min().date()
max_date = merged.index.max().date()

with st.sidebar:
    st.header("Filter")
    choice = st.radio("Granularität", list(GRANULARITY.keys()))
    date_range = st.date_input(
        "Zeitraum",
        value=(min_date, max_date),
        min_value=min_date,
        max_value=max_date,
    )

freq = GRANULARITY[choice]

if isinstance(date_range, tuple) and len(date_range) == 2:
    start = pd.Timestamp(date_range[0]).tz_localize("Europe/Berlin")
    end = pd.Timestamp(date_range[1]).tz_localize("Europe/Berlin")
    mask = (merged.index >= start) & (merged.index <= end)
    merged = merged[mask]
    verbrauch = verbrauch.loc[start:end]

merged_resampled = merged.resample(freq).sum()
merged_pct = merged_resampled.div(merged_resampled.sum(axis=1), axis=0) * 100
merged_pct.columns = [col.replace(" (MW)", " (%)") for col in merged_pct.columns]

renewable_cols = [f"{name} (MW)" for name in RENEWABLE_SOURCES]
fossil_cols = [f"{name} (MW)" for name in FOSSIL_SOURCES]

renewable_total = merged[renewable_cols].sum().sum()
fossil_total = merged[fossil_cols].sum().sum()
gesamt = renewable_total + fossil_total

solar_anteil = merged["Solar (MW)"].sum() / gesamt if gesamt else 0
wind_anteil = (
    merged["Wind Onshore (MW)"].sum() + merged["Wind Offshore (MW)"].sum()
) / gesamt if gesamt else 0

renewable_pro_stunde = merged[renewable_cols].sum(axis=1)
renewable_pro_stunde, verbrauch_pro_stunde = renewable_pro_stunde.align(
    verbrauch["value"], join="inner"
)
ueberschuss_anteil = (renewable_pro_stunde > verbrauch_pro_stunde).mean()

verbrauch_total = verbrauch["value"].sum()
deckungsgrad = min(renewable_total / verbrauch_total, 1.0) if verbrauch_total else 0
share = renewable_share(renewable_total, fossil_total)

st.caption(f"Datenstand: {last_update.strftime('%d.%m.%Y %H:%M')} Uhr")

col1, col2, col3, col4 = st.columns(4)
with col1:
    st.metric("Deckungsgrad", f"{deckungsgrad * 100:.1f} %")
with col2:
    st.metric("Anteil Erneuerbare", f"{share * 100:.1f} %")
with col3:
    st.metric("Solar-Anteil", f"{solar_anteil * 100:.1f} %")
with col4:
    st.metric("Wind-Anteil", f"{wind_anteil * 100:.1f} %")

col5, = st.columns(1)
with col5:
    st.metric("Überschuss-Stunden", f"{ueberschuss_anteil * 100:.1f} %")



fig = px.line(
    merged_resampled,
    color_discrete_map=COLORS,
    labels={"timestamp": "Zeit", "value": "Erzeugung (MWh)", "variable": "Energiequelle"},
    title="Stromerzeugung nach Quelle",
)
fig.update_traces(hovertemplate="<b>%{fullData.name}</b>: %{y:.1f} MW<br>%{x|%d.%m.%Y %H:%M}<extra></extra>")
st.plotly_chart(fig)


fig = px.area(
    merged_pct,
    color_discrete_map=COLORS_PCT,
    labels={"timestamp": "Zeit", "value": "Anteil (%)", "variable": "Energiequelle"},
    title="Anteil am Strommix",
)
fig.update_traces(hovertemplate="<b>%{fullData.name}</b>: %{y:.1f} %<br>%{x|%d.%m.%Y %H:%M}<extra></extra>")
st.plotly_chart(fig)