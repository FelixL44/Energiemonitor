from datetime import date, timedelta
from time import monotonic

import pandas as pd
import plotly.graph_objects as go
import requests
import streamlit as st

from ansichten import (
    LAND,
    border_reading,
    flow_map,
    frame,
    hourly_flows,
    hours,
    plot_series,
)
from stromdaten import (
    BERLIN,
    GENERATION,
    LOAD,
    PRICE,
    RENEWABLES,
    SERIES,
    border_payload,
    read_window,
)

st.set_page_config(
    page_title="Energiemonitor · Deutschland", page_icon="⚡", layout="wide"
)
TODAY = pd.Timestamp.now(tz=BERLIN).date()


@st.cache_data(ttl=900, max_entries=64, show_spinner=False)
def data(start, end, names):
    return frame(read_window(start, end, [(name, SERIES[name]) for name in names]))


@st.cache_data(ttl=900, max_entries=64, show_spinner=False)
def flows(day):
    try:
        return hourly_flows(border_payload(day), day), None
    except (requests.RequestException, ValueError, KeyError, TypeError):
        return pd.DataFrame(
            index=hours(day)
        ), "Grenzflüsse konnten nicht geladen werden."


def val(number, unit):
    if pd.isna(number):
        return "—"
    return f"{number:,.2f}".replace(",", " ").replace(".", ",") + " " + unit


def strict_sum(df):
    return df.sum(axis=1, min_count=len(df.columns))


def show_warnings(warnings):
    if warnings:
        with st.expander("Datenquellen mit Einschränkungen"):
            for message in dict.fromkeys(warnings):
                st.write(message)


def reset_clock():
    st.session_state["next-hour-at"] = monotonic() + 2


def prices(day, prices, selected):
    st.subheader("Wann ist Strom an der Börse günstig?")
    st.caption(
        "Day-Ahead · Deutschland/Luxemburg · Der Haushaltsstrompreis hängt vom Tarif ab."
    )
    idx = hours(day)
    quarters = pd.date_range(
        idx[0], idx[-1] + pd.Timedelta(hours=1), freq="15min", inclusive="left"
    )
    s = prices.reindex(quarters)
    if s.isna().all():
        st.info("Für diesen Tag liegen keine Viertelstundenpreise vor.")
        return
    duration = st.radio(
        "Dauer",
        [1, 2, 3, 4],
        index=1,
        horizontal=True,
        format_func=lambda n: f"{n} h",
        on_change=reset_clock,
    )
    eligible = s.loc[s.index >= pd.Timestamp.now(tz=BERLIN)] if day == TODAY else s
    costs = eligible.rolling(4 * duration, min_periods=4 * duration).mean().dropna()
    fig = plot_series({PRICE: s}, "€/MWh", selected)
    fig.update_traces(line_shape="hv")
    if not costs.empty:
        end = costs.idxmin() + pd.Timedelta(minutes=15)
        start = end - pd.Timedelta(hours=duration)
        fig.add_vrect(
            x0=start.timestamp(),
            x1=end.timestamp(),
            fillcolor="#66d4ae",
            opacity=0.17,
            line_width=0,
        )
        st.write(
            f"Günstigstes {'verbleibendes ' if day == TODAY else ''}Fenster: "
            f"**{start:%H:%M %Z} bis {end:%H:%M %Z}** · Ø {val(costs.min(), '€/MWh')}"
        )
    else:
        st.caption("Für diese Dauer gibt es kein vollständiges Preisfenster mehr.")
    st.plotly_chart(fig, use_container_width=True)


def day_view():
    st.title("Der deutsche Stromtag")
    st.caption(
        "Erzeugung, Verbrauch und Stromflüsse im Tagesverlauf · Zeit in Deutschland"
    )
    earliest = TODAY - timedelta(days=365 * 2)
    try:
        linked = date.fromisoformat(st.query_params.get("tag", ""))
    except ValueError:
        linked = TODAY
    day = st.date_input(
        "Stromtag",
        min(TODAY, max(earliest, linked)),
        min_value=earliest,
        max_value=TODAY,
        key="selected-day",
    )
    if day is None:
        st.info("Bitte einen Stromtag wählen.")
        return
    if st.query_params.get("tag") != day.isoformat():
        st.query_params["tag"] = day.isoformat()
    with st.spinner("Stromdaten werden geladen …"):
        raw, issues = data(day, day, tuple(SERIES))
        borders, problem = flows(day)
    ticks = hours(day)
    actual = raw.reindex(ticks).drop(columns=PRICE) / 1000  # MWh per full hour → GW
    s = pd.DataFrame(index=ticks)
    s[LOAD] = actual[LOAD]
    s["Solar"] = actual["Solar"]
    s["Wind"] = actual["Wind an Land"] + actual["Wind auf See"]
    s["Residuallast"] = s[LOAD] - s["Solar"] - s["Wind"]
    for name, forecasts in {
        LOAD: ["Netzlast · Prognose"],
        "Solar": ["Solar · Prognose"],
        "Wind": ["Wind an Land · Prognose", "Wind auf See · Prognose"],
    }.items():
        last = s[name].last_valid_index()
        pred = strict_sum(actual[forecasts])
        s[name + " · Prognose"] = (
            pred.where(pred.index > last) if last is not None else pred
        )
    balance = borders.get("Saldo", pd.Series(index=ticks, dtype=float))
    common = pd.concat(
        [s[[LOAD, "Solar", "Wind"]], strict_sum(actual[list(GENERATION)]), balance],
        axis=1,
    )
    fresh = common.dropna().index
    complete = len(fresh) > 0
    if not complete:
        fresh = s[[LOAD, "Solar", "Wind"]].dropna().index
    initial = ticks.get_loc(fresh[-1]) if len(fresh) else 0
    if len(fresh):
        scope = (
            "Erzeugung, Netzlast und Grenzsaldo"
            if complete
            else "Netzlast, Wind und Solar"
        )
        st.caption(
            f"Letzte gemeinsame Messstunde für {scope}: {fresh[-1]:%d.%m.%Y, %H:%M %Z}."
        )
    else:
        st.warning(
            "Für diesen Tag gibt es noch keine gemeinsame Messstunde für Netzlast, Wind und Solar."
        )
    warnings = issues + ([problem] if problem else [])
    show_warnings(warnings)
    if warnings:

        def retry():
            data.clear(day, day, tuple(SERIES))
            flows.clear(day)

        st.button("Daten erneut laden", on_click=retry)
    if raw.dropna(how="all").empty and borders.dropna(how="all").empty:
        st.info("Für den gewählten Tag sind keine Daten verfügbar.")
        return
    play = st.toggle("Tag abspielen", key=f"play-{day}", on_change=reset_clock)

    @st.fragment(run_every=2 if play else None)
    def timeline():
        key = f"hour-{day}"
        if key not in st.session_state:
            st.session_state[key] = initial
        if play and monotonic() >= st.session_state.get("next-hour-at", 0):
            reset_clock()
            st.session_state[key] = (st.session_state[key] + 1) % len(ticks)
        pos = st.select_slider(
            "Messstunde",
            options=list(range(len(ticks))),
            format_func=lambda i: ticks[i].strftime("%H:%M %Z"),
            key=key,
            on_change=reset_clock,
        )
        t = ticks[pos]
        m = s.loc[t]
        other = strict_sum(
            actual[
                [
                    n
                    for n in GENERATION
                    if n not in ("Wind an Land", "Wind auf See", "Solar")
                ]
            ]
        ).loc[t]
        border = borders.loc[t]
        columns = st.columns(4)
        for column, (label, value) in zip(
            columns,
            [
                ("Netzlast", m[LOAD]),
                ("Wind und Solar", m["Wind"] + m["Solar"]),
                ("Übrige Erzeugung", other),
                ("Nettoimport (+) / Export (−)", border.get("Saldo")),
            ],
        ):
            column.metric(label, val(value, "GW"))
        st.caption(
            f"Mittlere Leistung ab {t:%H:%M %Z} für eine Stunde · — Daten fehlen"
        )
        chart_col, map_col = st.columns([1.15, 1])
        with chart_col:
            st.subheader("Last und Erzeugung")
            st.caption(
                "Gestrichelt: Prognose ab dem letzten Messwert der jeweiligen Reihe."
            )
            st.plotly_chart(
                plot_series(s.to_dict("series"), "GW", t),
                use_container_width=True,
                key="day-lines",
            )
        with map_col:
            st.subheader("Strom über die Grenzen")
            st.caption("Pfeilrichtung: Stromfluss · Pfeilbreite: mittlere Leistung")
            event = st.plotly_chart(
                flow_map(border),
                use_container_width=True,
                key="border-map",
                on_select=reset_clock,
                selection_mode="points",
                config={"displayModeBar": False},
            )
        labels = {code: name for name, code, _, _ in LAND.values()}
        points = event.selection.points
        selected = next(
            (p["customdata"][0] for p in reversed(points) if p.get("customdata")), None
        )
        available = [c for c in borders if c != "Saldo"]
        if available:
            if selected in available and selected != st.session_state.get(
                "last_map_pick"
            ):
                st.session_state["border-choice"] = selected
            st.session_state["last_map_pick"] = selected
            country = st.selectbox(
                "Grenzverbindung im Tagesverlauf",
                available,
                format_func=lambda c: labels.get(c, c),
                key="border-choice",
                on_change=reset_clock,
            )
            route, reading, interval = border_reading(
                labels.get(country, country), border.get(country), t
            )
            st.caption(f"{route} · {reading} · {interval}")
            st.plotly_chart(
                plot_series({labels.get(country, country): borders[country]}, "GW", t),
                use_container_width=True,
                key="border-history",
            )
        else:
            st.caption("Keine gemessenen Grenzflüsse für diesen Tag verfügbar.")

        prices(day, raw[PRICE], t)

    timeline()


def history():
    st.title("Erzeugung im Zeitverlauf")
    dates = st.date_input(
        "Zeitraum",
        (TODAY - timedelta(days=7), TODAY),
        max_value=TODAY,
        min_value=TODAY - timedelta(days=365 * 2),
    )
    if not dates or len(dates) != 2:
        st.info("Bitte ein Enddatum wählen.")
        return
    if (dates[1] - dates[0]).days >= 35:
        st.info("Bitte höchstens 35 Tage gleichzeitig auswählen.")
        return
    raw, warnings = data(*dates, tuple(GENERATION) + (LOAD,))
    show_warnings(warnings)
    idx = pd.date_range(hours(dates[0])[0], hours(dates[1])[-1], freq="h")
    gen = raw.reindex(idx)[list(GENERATION)] / 1000
    load = raw[LOAD].reindex(idx) / 1000
    total, renew = strict_sum(gen), strict_sum(gen[RENEWABLES])
    complete = total.notna() & load.notna() & load.gt(0)
    if not complete.any():
        st.info("Keine vollständigen Stunden für die Übersicht.")
    else:
        denom = total[complete].sum()

        def share(values):
            return val(100 * values[complete].sum() / denom if denom else None, "%")

        for widget, (name, value) in zip(
            st.columns(5),
            [
                ("Erneuerbare / Erzeugung", share(renew)),
                ("Solar / Erzeugung", share(gen["Solar"])),
                ("Wind / Erzeugung", share(gen["Wind an Land"] + gen["Wind auf See"])),
                (
                    "Erneuerbare / Netzlast",
                    val(100 * renew[complete].sum() / load[complete].sum(), "%"),
                ),
                (
                    "Stunden über Netzlast",
                    val(100 * (renew[complete] > load[complete]).mean(), "%"),
                ),
            ],
        ):
            widget.metric(name, value)
    st.caption(
        f"Kennzahlen aus {complete.sum()} von {len(idx)} Stunden mit vollständigen Daten."
    )
    unit_col, period_col = st.columns(2)
    mode = unit_col.radio("Darstellung", ["Energie", "Anteil"], horizontal=True)
    period = period_col.radio("Auflösung", ["Stunde", "Tag", "Woche"], horizontal=True)
    rule = {"Stunde": "h", "Tag": "D", "Woche": "W-SUN"}[period]
    agg = gen.resample(rule).sum(min_count=1)
    agg = agg.where(gen.resample(rule).count().eq(gen.resample(rule).size(), axis=0))
    if mode == "Anteil":
        agg = agg.div(strict_sum(agg).replace(0, float("nan")), axis=0) * 100
    unit = "%" if mode == "Anteil" else "GWh"
    st.plotly_chart(plot_series(agg.to_dict("series"), unit), use_container_width=True)
    # Stack complete intervals only. Plotly otherwise interpolates missing layers.
    grouped = agg.dropna()
    if not grouped.empty:
        fig = go.Figure(
            [go.Bar(x=grouped.index, y=grouped[n], name=n) for n in grouped]
        )
        fig.update_layout(
            barmode="stack", yaxis_title=unit, legend={"orientation": "h"}
        )
        st.plotly_chart(fig, use_container_width=True)


view = st.radio(
    "Ansicht",
    ["Stromtag", "Historische Auswertung"],
    horizontal=True,
    label_visibility="collapsed",
)
if view == "Stromtag":
    day_view()
else:
    history()
st.caption(
    "Daten: Bundesnetzagentur | [SMARD.de](https://www.smard.de/home/datennutzung) · "
    "Grenzflüsse: [Energy-Charts.info](https://api.energy-charts.info/) · "
    "[CC BY 4.0](https://creativecommons.org/licenses/by/4.0/) · Kartengrundlage: Natural Earth."
)
