import requests
import pandas as pd

def fetch_series(filter_id):
    region = "DE"
    resolution = "hour"

    index_url = f"https://www.smard.de/app/chart_data/{filter_id}/{region}/index_{resolution}.json"
    index_response = requests.get(index_url)
    index_data = index_response.json()
    last_ts = index_data['timestamps'][-4:]

    frames = []
    for ts in last_ts:
        data_url = f"https://www.smard.de/app/chart_data/{filter_id}/{region}/{filter_id}_{region}_{resolution}_{ts}.json"
        data_response = requests.get(data_url)
        series_data = data_response.json()
        df_part = pd.DataFrame(series_data["series"], columns=["timestamp", "value"]).dropna()
        frames.append(df_part)

    df = pd.concat(frames)
    df["timestamp"] = pd.to_datetime(df["timestamp"], unit="ms", utc=True).dt.tz_convert("Europe/Berlin")
    return df

# --- Erkundung ---
df = fetch_series(410)      # 410 als ARGUMENT übergeben, nicht hardcoden
print(df.head())
print(df.tail())
print(df.info())