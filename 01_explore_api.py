import requests
import pandas as pd
import plotly.express as px

print("UTC now:    ", pd.Timestamp.utcnow())
print("Local now:  ", pd.Timestamp.now())

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
NUCLEAR_SOURCES = {
    "Kernenergie": 1224,
}

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
for name, id in RENEWABLE_SOURCES.items():
    df = fetch_series(id)
    df = df.rename(columns={"value": f"{name} (MW)"})
    if merged is None:
        merged = df
    else:
        merged = pd.merge(merged, df, on="timestamp")
        merged = merged.set_index("timestamp")

print(merged.tail())

fig = px.line(merged, title="Erneuerbare Stromerzeugung (letzte Woche)")
fig.show()

# print("Fetching data for all renewable sources...")
# renewable_total = sum_sources(RENEWABLE_SOURCES)
# print("Total renewable energy:", renewable_total)

# print("Fetching data for all fossil sources...")
# fossil_total = sum_sources(FOSSIL_SOURCES)
# print("Total fossil energy:", fossil_total)

# print("Renewable share:", renewable_share(renewable_total, fossil_total))

# df = fetch_series(4068)   # Solar
# print(df.tail(10))        # die letzten 10 Zeilen, Timestamp + Value
# print("Zeilen gesamt:", len(df))