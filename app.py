import streamlit as st
import requests
import pandas as pd
import plotly.express as px

st.title("German Energy Monitor ⚡")

def fetch_series(filter_id):
    region = "DE"
    resolution = "hour"

    # --- Call 1: INDEX ---
    index_url = f"https://www.smard.de/app/chart_data/{filter_id}/{region}/index_{resolution}.json"
    index_response = requests.get(index_url)
    index_data = index_response.json()
    last_ts = index_data['timestamps'][-1]

    # --- Call 2: DATA ---
    data_url = f"https://www.smard.de/app/chart_data/{filter_id}/{region}/{filter_id}_{region}_{resolution}_{last_ts}.json"
    data_response = requests.get(data_url)
    series_data = data_response.json()

    # --- DataFrame ---
    df = pd.DataFrame(series_data["series"], columns=["timestamp", "value"]).dropna()
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

ALL_SOURCES = {**RENEWABLE_SOURCES, **FOSSIL_SOURCES}

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

renewable_cols = [f"{name} (MW)" for name in RENEWABLE_SOURCES]
fossil_cols = [f"{name} (MW)" for name in FOSSIL_SOURCES]

# Block 3: letzte Zeile + Summen
latest = merged.iloc[-1]
renewable_now = latest[renewable_cols].sum()
fossil_now = latest[fossil_cols].sum()

# Block 4: Share + Kachel
share = renewable_share(renewable_now, fossil_now)
st.metric("Anteil Erneuerbare (jetzt)", f"{share * 100:.1f} %")
st.caption("Basis: 8 Hauptquellen, ohne Kernkraft/Sonstige")

st.line_chart(merged)