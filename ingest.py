"""Refresh recent SMARD blocks, keeping late corrections and concurrent runs safe."""

import argparse
import os
import sys
import time

import psycopg
import requests
from psycopg.types.json import Jsonb

from stromdaten import SERIES, block, index, spec


def run_ingestion(count):
    failed = False
    with psycopg.connect(
        os.environ["SUPABASE_DB_URL"], autocommit=True, prepare_threshold=None
    ) as conn:
        conn.execute("CREATE SCHEMA IF NOT EXISTS raw")
        conn.execute("""
            CREATE TABLE IF NOT EXISTS raw.stromtag_blocks (
                filter_id integer NOT NULL, region text NOT NULL, resolution text NOT NULL,
                block_timestamp bigint NOT NULL, payload jsonb NOT NULL, source_url text NOT NULL,
                fetched_at timestamptz NOT NULL DEFAULT now(),
                PRIMARY KEY (filter_id, region, resolution, block_timestamp)
            )
        """)
        # Older imports can contain repeated snapshots without a version column.
        # Keep the old archive intact and prefer the snapshot with most reported values.
        if conn.execute("SELECT to_regclass('raw.smard_data')").fetchone()[0]:
            conn.execute("""
                INSERT INTO raw.stromtag_blocks
                    (filter_id,region,resolution,block_timestamp,payload,source_url)
                SELECT DISTINCT ON (filter_id,region,resolution,block_timestamp)
                    filter_id,region,resolution,block_timestamp,payload::jsonb,source_url
                  FROM raw.smard_data old
                 WHERE NOT EXISTS (SELECT 1 FROM raw.stromtag_blocks saved
                    WHERE (saved.filter_id,saved.region,saved.resolution,saved.block_timestamp)
                        = (old.filter_id,old.region,old.resolution,old.block_timestamp))
                 ORDER BY filter_id,region,resolution,block_timestamp,
                    jsonb_array_length(jsonb_path_query_array(payload::jsonb,'$.series[*][1] ? (@ != null)')) DESC
                ON CONFLICT DO NOTHING
            """)
        for name, fid in SERIES.items():
            try:
                for stamp in index(fid)[-count:]:
                    url, data = block(fid, stamp)
                    conn.execute(
                        """
                        INSERT INTO raw.stromtag_blocks
                            (filter_id, region, resolution, block_timestamp, payload, source_url)
                        VALUES (%s,%s,%s,%s,%s,%s)
                        ON CONFLICT (filter_id,region,resolution,block_timestamp)
                        DO UPDATE SET payload=EXCLUDED.payload, source_url=EXCLUDED.source_url,
                                      fetched_at=now()
                    """,
                        (fid, *spec(fid), stamp, Jsonb(data), url),
                    )
                    time.sleep(0.2)
            except (
                requests.RequestException,
                ValueError,
                KeyError,
                psycopg.Error,
            ) as exc:
                failed = True
                print(
                    f"{name}: Import fehlgeschlagen ({type(exc).__name__})",
                    file=sys.stderr,
                )
    return int(failed)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("num_blocks", nargs="?", type=int, default=2)
    args = parser.parse_args()
    if args.num_blocks < 1:
        parser.error("num_blocks muss positiv sein")
    sys.exit(run_ingestion(args.num_blocks))
