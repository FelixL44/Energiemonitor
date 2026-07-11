import os
import requests
import psycopg
from psycopg.types.json import Json
from dotenv import load_dotenv
import time
import sys

load_dotenv()
CONN_STRING = os.environ["SUPABASE_DB_URL"]
FILTER_IDS = [4068, 4067, 1225, 4066, 1226, 4071, 4069, 1223]

def list_block_timestamps(filter_id: int) -> list[int]:
    REGION = "DE"
    RESOLUTION = "hour"
    # 1. Index-URL bauen (index_{RESOLUTION}.json, OHNE timestamp)
    index_url = f"https://www.smard.de/app/chart_data/{filter_id}/{REGION}/index_{RESOLUTION}.json"

    # 2. holen + raise_for_status
    response = requests.get(index_url, timeout=30)
    response.raise_for_status()

    # 3. return response.json()["timestamps"]
    return response.json()["timestamps"]

def fetch_and_store_block(
    conn: psycopg.Connection, filter_id: int, block_timestamp: int
) -> None:
    """
    Worker: holt EINEN SMARD-Block und schreibt ihn als EINE Zeile nach raw.smard_data.
    Bekommt die Verbindung vom Orchestrator, committet pro Block.
    Wirft bei Fehler nach oben (throw low) — fängt selbst nichts ab.
    """
    REGION = "DE"
    RESOLUTION = "hour"

    # 1. Timeseries-URL bauen.
    data_url = (
        f"https://www.smard.de/app/chart_data/{filter_id}/{REGION}/"
        f"{filter_id}_{REGION}_{RESOLUTION}_{block_timestamp}.json"
    )

    # 2. Response holen. raise_for_status() wirft bei schlechtem Statuscode.
    response = requests.get(data_url, timeout=30)
    response.raise_for_status()

    # 3. JSON parsen (bleibt ein dict — erst beim Insert in Json() wickeln).
    payload = response.json()

    # 4. Eine Zeile schreiben. transaction() = Commit bei Erfolg,
    #    Rollback bei Exception → geteilte Verbindung bleibt für den nächsten Block sauber.
    with conn.transaction():
        conn.execute(
        """
        insert into raw.smard_data
            (filter_id, region, resolution, block_timestamp, payload, source_url)
        values (%s, %s, %s, %s, %s, %s)
        """,
    (filter_id, REGION, RESOLUTION, block_timestamp, Json(payload), data_url),
)
        
def run_ingestion(num_blocks: int) -> None:
    with psycopg.connect(CONN_STRING, prepare_threshold=None) as conn:
        for filter_id in FILTER_IDS:
            # 1. Index-Call: volle Blockliste für diesen Filter holen.
            try:
                timestamps = list_block_timestamps(filter_id)
            except Exception as e:
                print(f"Fehler im Index-Call: {e} | {filter_id}")
                continue

            # 2. Zuschneiden: nur die letzten NUM_BLOCKS aus der Liste.
            timestamps = timestamps[-num_blocks:]

            # 3. Info-Print: welcher Filter, wie viele Blöcke.
            print(f"Filter: {filter_id} | Blöcke: {len(timestamps)}")

            # 4. Innere Schleife über die zugeschnittenen Blöcke:
            for block_timestamp in timestamps:
                try:
                    fetch_and_store_block(conn, filter_id, block_timestamp)
                except Exception as e:
                    print(f"Fehler im Worker: {e} | {filter_id} | {block_timestamp}")
                time.sleep(0.2)

if __name__ == "__main__":
    NUM_BLOCKS =  int(sys.argv[1]) if len(sys.argv) > 1 else 2

    print("Run startet, öffne Verbindung...")
    # Orchestrator: Verbindung EINMAL öffnen, an jeden Worker-Call übergeben.
    run_ingestion(NUM_BLOCKS)


print(f"Run startet mit {NUM_BLOCKS} Blöcken...") 

