import unittest
from datetime import date
from unittest.mock import patch

import pandas as pd
import requests
import streamlit as st
from streamlit.testing.v1 import AppTest

from ansichten import arrow_width, flow_map, hourly_flows, hours
from stromdaten import PRICE, bounds, load_series, spec

DAY = date(2026, 10, 25)


def mock_window(start, end, items):
    lo, hi = bounds(start, end)
    result = []
    for name, fid in items:
        step = 900_000 if name == PRICE else 3_600_000
        result.append(
            (
                name,
                {ts: 40 if name == PRICE else 1000 for ts in range(lo, hi, step)},
                [],
            )
        )
    return result


def mock_borders(day):
    return {
        "unit": "GW",
        "interval_minutes": 15,
        "series": [{"id": "france", "name": "France"}, {"id": "sum", "name": "sum"}],
        "data": [
            {"timestamp": t.isoformat(), "values": {"france": -1, "sum": -1}}
            for t in pd.date_range(
                hours(day)[0], hours(day)[-1] + pd.Timedelta(minutes=45), freq="15min"
            )
        ],
    }


class StromtagTest(unittest.TestCase):
    def setUp(self):
        st.cache_data.clear()

    def test_clock_change_and_missing_quarter(self):
        self.assertEqual(len(hours(DAY)), 25)
        self.assertEqual(len(hours(date(2026, 3, 29))), 23)
        payload = mock_borders(DAY)
        payload["data"].pop(2)
        flow = hourly_flows(payload, DAY)
        self.assertTrue(pd.isna(flow.iloc[0]["FR"]))
        self.assertEqual(flow.iloc[1]["Saldo"], -1)

    @patch("stromdaten.border_payload", side_effect=mock_borders)
    @patch("stromdaten.read_window", side_effect=mock_window)
    def test_dashboard(self, *_):
        app = AppTest.from_file("app.py", default_timeout=120).run()
        self.assertFalse(list(app.exception))
        self.assertEqual(app.metric[1].value, "3,00 GW")
        app.select_slider[0].set_value(3).run()
        self.assertFalse(list(app.exception))
        app.toggle[0].set_value(True).run()
        self.assertFalse(list(app.exception))
        app.select_slider[0].set_value(7).run()
        self.assertEqual(app.select_slider[0].value, 7)
        app.radio[1].set_value(3).run()
        self.assertEqual(app.select_slider[0].value, 7)
        app.toggle[0].set_value(False).run()
        app.radio[0].set_value("Historische Auswertung").run()
        self.assertFalse(list(app.exception))
        self.assertEqual(len(app.metric), 5)
        app.radio[1].set_value("Anteil")
        app.radio[2].set_value("Woche").run()
        self.assertFalse(list(app.exception))

    @patch("stromdaten.border_payload", side_effect=requests.ConnectionError)
    @patch("stromdaten.get_json", side_effect=requests.ConnectionError)
    @patch.dict("os.environ", {"SUPABASE_DB_URL": ""})
    def test_offline(self, *_):
        app = AppTest.from_file("app.py", default_timeout=60).run()
        self.assertFalse(list(app.exception))
        self.assertFalse(app.metric)
        calls = _[0].call_count
        app.button[0].click().run()
        self.assertGreater(_[0].call_count, calls)
        self.assertTrue(app.warning)

    @patch.dict("os.environ", {"SUPABASE_DB_URL": "test"})
    @patch("stromdaten.block", return_value=("source", {"series": [[3600000, 2]]}))
    @patch("stromdaten.index", return_value=[0])
    @patch("stromdaten.archive", return_value=[{"series": [[0, 1]]}])
    def test_partial_archive(self, *_):
        _, values, issues = load_series(("Netzlast", 410), 0, 7200000)
        self.assertEqual(values, {0: 1, 3600000: 2})
        self.assertFalse(issues)

    def test_arrow_magnitude_direction_and_hover(self):
        t = hours(DAY)[2]
        row = pd.Series({"FR": 3.2505, "NL": -0.4, "BE": 0.0}, name=t)
        fig = flow_map(row)
        arrows = {tr.name: tr for tr in fig.data if tr.mode == "lines+markers"}
        self.assertEqual(set(arrows), {"Frankreich", "Niederlande"})
        strong, weak = arrows["Frankreich"], arrows["Niederlande"]
        self.assertGreater(strong.line.width, weak.line.width)
        self.assertEqual(weak.line.width, arrow_width(0.4))
        self.assertGreater(strong.x[-1], strong.x[0])  # France to Germany
        self.assertLess(weak.x[-1], weak.x[0])  # Germany to Netherlands
        self.assertEqual(
            strong.customdata[20][1:3],
            ["Frankreich → Deutschland", "3 250,5 MW im Stundenmittel"],
        )
        self.assertIn("02:00 CEST–02:00 CET", strong.customdata[20][3])
        self.assertIn("customdata[2]", strong.hovertemplate)
        self.assertEqual(strong.marker.symbol[-1], "arrow")

    def test_prices_spec(self):
        self.assertEqual(spec(4169), ("DE-LU", "quarterhour"))


if __name__ == "__main__":
    unittest.main()
