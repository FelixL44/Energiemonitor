import streamlit as st
import requests
import pandas as pd
import plotly.express as px

st.title("Energy Monitor ⚡")

@st.cache_data(ttl=3600) # Cache für 1 Stunde, damit wir nicht bei jedem Refresh die API bombardieren
def fetch_series(filter_id):
    region = "DE"
    resolution = "hour"

    # --- Call 1: INDEX ---
    index_url = f"https://www.smard.de/app/chart_data/{filter_id}/{region}/index_{resolution}.json"
    index_response = requests.get(index_url)
    index_data = index_response.json()
    last_ts = index_data['timestamps'][-4:]

    frames = []                                        # leere Sammelliste
    for ts in last_ts:                         # über jeden Timestamp einzeln
        data_url = f"https://www.smard.de/app/chart_data/{filter_id}/{region}/{filter_id}_{region}_{resolution}_{ts}.json"
        data_response = requests.get(data_url)
        series_data = data_response.json()
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
choice = st.radio("Granularität", list(GRANULARITY.keys()), horizontal=True)
freq = GRANULARITY[choice]

def sum_sources(source_dict):
    total = 0
    for source, id in source_dict.items():
        df = fetch_series(id)
        latest_value = df["value"].dropna().iloc[-1]
        print(f"{source} latest value:", latest_value)
        total += latest_value
    return total

def renewable_share(renewable_total, fossil_total):
    total = renewable_total + fossil_total
    if total == 0:
        return 0
    return renewable_total / total

merged = None
for name, id in ALL_SOURCES.items():
    df = fetch_series(id)
    df = df.rename(columns={"value": f"{name} (MW)"})
    if merged is None:
        merged = df
    else:
        merged = pd.merge(merged, df, on="timestamp")



merged = merged.set_index("timestamp")   # ← einmal, nach der Schleife

# --- Zeitraum-Slider: ZUERST filtern ---
min_date = merged.index.min()
max_date = merged.index.max()
date_range = st.slider(
    "Zeitraum",
    min_value=min_date.to_pydatetime(),
    max_value=max_date.to_pydatetime(),
    value=(min_date.to_pydatetime(), max_date.to_pydatetime()),
)
mask = (merged.index >= date_range[0]) & (merged.index <= date_range[1])
merged = merged[mask]

merged_resampled = merged.resample(freq).sum()
merged_pct = merged_resampled.div(merged_resampled.sum(axis=1), axis=0) * 100
merged_pct.columns = [col.replace(" (MW)", " (%)") for col in merged_pct.columns]

last_update = merged.index[-1]

renewable_cols = [f"{name} (MW)" for name in RENEWABLE_SOURCES]
fossil_cols = [f"{name} (MW)" for name in FOSSIL_SOURCES]
labels={"timestamp": "Zeit", "value": "Erzeugung (MWh)", "variable": "Energiequelle"}
title="Stromerzeugung nach Quelle"

# Block 3: letzte Zeile + Summen
latest = merged.iloc[-1]
renewable_total = merged[renewable_cols].sum().sum()
fossil_total = merged[fossil_cols].sum().sum()

st.caption(f"Datenstand: {last_update.strftime('%d.%m.%Y %H:%M')} Uhr")

# Block 4: Share + Kachel
share = renewable_share(renewable_total, fossil_total)
st.metric("Anteil Erneuerbare (Zeitraum)", f"{share * 100:.1f} %")


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