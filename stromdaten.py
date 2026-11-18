"""SMARD series and raw-block access shared by the dashboard and scheduled import."""

import os
from bisect import bisect_right
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, time, timedelta
from zoneinfo import ZoneInfo

import psycopg
import requests
from dotenv import load_dotenv

load_dotenv()
BERLIN = ZoneInfo("Europe/Berlin")
GENERATION = {
    "Solar": 4068,
    "Wind an Land": 4067,
    "Wind auf See": 1225,
    "Biomasse": 4066,
    "Wasserkraft": 1226,
    "Sonstige Erneuerbare": 1228,
    "Erdgas": 4071,
    "Steinkohle": 4069,
    "Braunkohle": 1223,
    "Pumpspeicher": 4070,
    "Sonstige Konventionelle": 1227,
}
RENEWABLES = list(GENERATION)[:6]
FORECAST = {
    "Netzlast · Prognose": 411,
    "Solar · Prognose": 125,
    "Wind an Land · Prognose": 123,
    "Wind auf See · Prognose": 3791,
}
LOAD = "Netzlast"
PRICE = "Börsenpreis"
SERIES = {**GENERATION, LOAD: 410, **FORECAST, PRICE: 4169}


def spec(filter_id):
    return ("DE-LU", "quarterhour") if filter_id == 4169 else ("DE", "hour")


def get_json(url, **params):
    r = requests.get(url, params=params, timeout=(4, 15))
    r.raise_for_status()
    return r.json()


def base_url(filter_id):
    region, _ = spec(filter_id)
    return f"https://www.smard.de/app/chart_data/{filter_id}/{region}"


def index(filter_id):
    _, res = spec(filter_id)
    return sorted(get_json(f"{base_url(filter_id)}/index_{res}.json")["timestamps"])


def block(filter_id, stamp):
    region, res = spec(filter_id)
    url = f"{base_url(filter_id)}/{filter_id}_{region}_{res}_{stamp}.json"
    payload = get_json(url)
    if not isinstance(payload.get("series"), list):
        raise KeyError("SMARD-Zeitreihe fehlt")
    return url, payload


def bounds(start, end):
    def midnight(day):
        return int(datetime.combine(day, time.min, BERLIN).timestamp() * 1000)

    return midnight(start), midnight(end + timedelta(days=1))


def archive(filter_id, lo, hi):
    """Include the last block starting before lo (week may straddle request)."""
    region, res = spec(filter_id)
    with psycopg.connect(os.environ["SUPABASE_DB_URL"], connect_timeout=4) as conn:
        rows = conn.execute(
            """
            SELECT payload FROM raw.stromtag_blocks
             WHERE filter_id=%s AND region=%s AND resolution=%s AND block_timestamp < %s
               AND block_timestamp >= COALESCE((
                 SELECT max(block_timestamp) FROM raw.stromtag_blocks
                  WHERE filter_id=%s AND region=%s AND resolution=%s AND block_timestamp <= %s
               ), 0)
             ORDER BY block_timestamp
        """,
            (filter_id, region, res, hi, filter_id, region, res, lo),
        ).fetchall()
    return [row[0] for row in rows]


def load_series(item, lo, hi):
    name, fid = item
    warnings = []
    payloads = []
    if os.getenv("SUPABASE_DB_URL"):
        try:
            payloads = archive(fid, lo, hi)
        except psycopg.Error:
            warnings.append(f"{name}: Archiv nicht verfügbar.")
    values = {t: v for p in payloads for t, v in p["series"] if lo <= t < hi}
    step = 900_000 if name == PRICE else 3_600_000
    # A partly archived range can span multiple SMARD blocks. Fill uncovered
    # intervals from the source, including hours missed by a stopped importer.
    cutoff = hi
    if name not in FORECAST and name != PRICE:
        now = int(datetime.now(BERLIN).timestamp() * 1000)
        cutoff = min(hi, now // step * step)
    if not values or any(values.get(t) is None for t in range(lo, cutoff, step)):
        try:
            stamps = index(fid)
            for stamp in stamps[max(0, bisect_right(stamps, lo) - 1) :]:
                if stamp >= hi:
                    break
                _, payload = block(fid, stamp)
                for t, v in payload["series"]:
                    if lo <= t < hi and (v is not None or t not in values):
                        values[t] = v
        except (requests.RequestException, ValueError, KeyError):
            warnings.append(f"{name}: Abruf bei SMARD unvollständig.")
    return name, values, warnings


def read_window(start, end, items):
    lo, hi = bounds(start, end)
    with ThreadPoolExecutor(max_workers=4) as pool:
        return list(pool.map(lambda item: load_series(item, lo, hi), items))


def border_payload(day):
    return get_json(
        "https://api.energy-charts.info/v2/cbpf",
        country="de",
        start=day.isoformat(),
        end=day.isoformat(),
    )
