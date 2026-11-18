import json
from math import sqrt
from pathlib import Path

import pandas as pd
import plotly.graph_objects as go

from stromdaten import BERLIN

PALETTE = {
    "Netzlast": "#efe7d6",
    "Solar": "#f7c758",
    "Wind": "#59cdb1",
    "Residuallast": "#aa9de1",
}
LAND = {
    "Austria": ("Österreich", "AT", 14.1, 47.5),
    "Belgium": ("Belgien", "BE", 4.6, 50.7),
    "Switzerland": ("Schweiz", "CH", 8.0, 46.8),
    "Czech Republic": ("Tschechien", "CZ", 15.5, 49.8),
    "Denmark": ("Dänemark", "DK", 9.6, 56.3),
    "France": ("Frankreich", "FR", 3.7, 47.5),
    "Luxembourg": ("Luxemburg", "LU", 6.1, 49.6),
    "Netherlands": ("Niederlande", "NL", 5.1, 52.5),
    "Norway": ("Norwegen", "NO", 7.5, 59.4),
    "Poland": ("Polen", "PL", 18.4, 52.4),
    "Sweden": ("Schweden", "SE", 14.4, 57.7),
}
# Schematic route endpoints inside Germany, separated by frontier for legibility.
# These coordinates do not represent individual transmission lines.
GERMAN_ENDPOINT = {
    "AT": (12.0, 48.5),
    "BE": (7.65, 50.9),
    "CH": (8.55, 48.15),
    "CZ": (13.0, 50.5),
    "DK": (9.9, 53.75),
    "FR": (8.35, 49.15),
    "LU": (7.6, 49.75),
    "NL": (8.45, 52.35),
    "NO": (8.1, 53.55),
    "PL": (13.55, 52.25),
    "SE": (12.0, 53.75),
}
FLOW_INK = "#c1c9d3"
BORDERS = json.loads((Path(__file__).parent / "assets/mitteleuropa.json").read_text())
ALIASES = {"czechia": "CZ", "czech_republic": "CZ"}
for english, (german, code, _, _) in LAND.items():
    for value in (english, german, code):
        ALIASES[value.lower()] = code


def hours(day):
    start = pd.Timestamp(day, tz=BERLIN)
    return pd.date_range(
        start, start + pd.DateOffset(days=1), freq="h", inclusive="left"
    )


def frame(results):
    columns = {}
    issues = []
    for name, values, warnings in results:
        s = pd.Series(values, dtype=float)
        s.index = pd.to_datetime(s.index, unit="ms", utc=True).tz_convert(BERLIN)
        columns[name] = s
        issues.extend(warnings)
    return pd.DataFrame(columns).sort_index(), issues


def hourly_flows(payload, day):
    step = payload.get("interval_minutes")
    if step not in (15, 30, 60):
        raise ValueError("Unbekannte Auflösung")
    records = payload["data"]
    result = pd.DataFrame(index=hours(day))
    if not records:
        return result
    idx = pd.to_datetime([r["timestamp"] for r in records], utc=True).tz_convert(BERLIN)
    rows = pd.DataFrame([r["values"] for r in records], index=idx)
    rows = rows.loc[~rows.index.duplicated(keep="last")]
    for item in payload["series"]:
        key = item["id"]
        label = str(item.get("name") or key)
        code = ALIASES.get(key.lower()) or ALIASES.get(label.lower(), label)
        if key.lower() in ("sum", "total") or label.lower() in ("sum", "total"):
            code = "Saldo"
        unit = item.get("unit") or payload.get("unit")
        if key not in rows or unit not in ("MW", "GW"):
            continue
        s = pd.to_numeric(rows[key], errors="coerce")
        groups = s.resample("h")
        result[code] = groups.mean().where(groups.count() == 60 // step) / (
            1000 if unit == "MW" else 1
        )
    return result


def plot_series(series, unit, selected=None):
    fig = go.Figure()
    intraday = selected is not None
    for name, values in series.items():
        base = name.split(" · ")[0]
        fig.add_scatter(
            x=[t.timestamp() for t in values.index] if intraday else values.index,
            customdata=values.index.strftime("%d.%m. %H:%M %Z"),
            y=values,
            name=name,
            connectgaps=False,
            line={
                "color": PALETTE.get(base),
                "width": 2.5,
                "dash": "dash" if "Prognose" in name else "solid",
            },
            hovertemplate=f"%{{customdata}} · %{{y:.2f}} {unit}<extra>{name}</extra>",
        )
    if selected is not None:
        fig.add_vline(x=selected.timestamp(), line_width=1, line_color="#efbe68")
    fig.update_layout(
        yaxis_title=unit,
        hovermode="x unified",
        height=335,
        margin={"l": 10, "r": 10, "t": 15, "b": 10},
        legend={"orientation": "h"},
    )
    if intraday:
        times = next(iter(series.values())).index
        labels = [t for t in times if t.hour % 4 == 0 and t.minute == 0]
        fig.update_xaxes(
            type="linear",
            tickvals=[t.timestamp() for t in labels],
            ticktext=[t.strftime("%H:%M") for t in labels],
            range=[times[0].timestamp(), times[-1].timestamp()],
        )
        fig.update_layout(hovermode="closest")
    else:
        fig.update_xaxes(tickformat="%d.%m.")
    return fig


def border_reading(name, value, hour):
    interval = (
        f"{hour:%d.%m.%Y} · {hour:%H:%M %Z}–{hour + pd.Timedelta(hours=1):%H:%M %Z}"
    )
    if pd.isna(value):
        return name, "Kein Messwert", interval
    if value == 0:
        return name, "0 MW · ausgeglichener Fluss", interval
    direction = f"{name} → Deutschland" if value > 0 else f"Deutschland → {name}"
    # One GW is 1,000 MW. Preserve sub-MW differences between hourly averages.
    mw = (
        f"{abs(value) * 1000:,.2f}".rstrip("0")
        .rstrip(".")
        .translate(str.maketrans({",": " ", ".": ","}))
    )
    return direction, f"{mw} MW im Stundenmittel", interval


def arrow_width(gw):
    # Identical scale for every connection and hour, measured in screen pixels.
    return 0.8 + 1.25 * sqrt(abs(gw))


def flow_map(row):
    fig = go.Figure()
    for name, polygons in BORDERS.items():
        for poly in polygons:
            xs, ys = zip(*poly)
            fig.add_scatter(
                x=xs,
                y=ys,
                mode="lines",
                fill="toself",
                hoverinfo="skip",
                line={"width": 0.7, "color": "#353c46"},
                showlegend=False,
                fillcolor="#343d49" if name == "Germany" else "#222830",
            )

    # Paths end just before the labels. Dense transparent markers make the full
    # shaft hoverable and clickable, including thin flows on narrow screens.
    hover = (
        "<b>%{customdata[1]}</b><br>%{customdata[2]}<br>%{customdata[3]}<extra></extra>"
    )
    labels = []
    for name, code, x, y in LAND.values():
        value = row.get(code)
        details = [code, *border_reading(name, value, row.name)]
        labels.append((x, y, code, details))
        if pd.isna(value) or value == 0:
            continue
        dx, dy = GERMAN_ENDPOINT[code]
        # Keep a gap between each country label and its route in both directions.
        foreign = (x + 0.18 * (dx - x), y + 0.18 * (dy - y))
        origin, tip = (foreign, (dx, dy)) if value > 0 else ((dx, dy), foreign)
        width = arrow_width(value)
        fig.add_annotation(
            ax=origin[0],
            ay=origin[1],
            x=tip[0],
            y=tip[1],
            axref="x",
            ayref="y",
            xref="x",
            yref="y",
            text="",
            showarrow=True,
            arrowhead=2,
            arrowsize=(5 + width) / (3 * width),
            arrowwidth=width,
            arrowcolor="#64deba" if value > 0 else "#ffc368",
            captureevents=False,
        )
        fig.add_scatter(
            x=[origin[0] + (tip[0] - origin[0]) * i / 40 for i in range(41)],
            y=[origin[1] + (tip[1] - origin[1]) * i / 40 for i in range(41)],
            mode="markers",
            showlegend=False,
            name=name,
            customdata=[details] * 41,
            marker={"size": 16, "color": "rgba(0,0,0,0)", "line": {"width": 0}},
            hovertemplate=hover,
            selected={"marker": {"opacity": 1}},
            unselected={"marker": {"opacity": 1}},
        )
    xs, ys, codes, details = zip(*labels)
    fig.add_scatter(
        x=xs,
        y=ys,
        mode="markers+text",
        showlegend=False,
        marker={"size": 18, "color": "rgba(0,0,0,0)", "line": {"width": 0}},
        text=codes,
        textposition="middle center",
        textfont={"color": "#ccd1d8", "size": 12},
        customdata=details,
        hovertemplate=hover,
        selected={"marker": {"opacity": 1}},
        unselected={"marker": {"opacity": 1}},
    )
    for gw in (1, 4):
        fig.add_scatter(
            x=[None],
            y=[None],
            mode="lines",
            hoverinfo="skip",
            line={"width": arrow_width(gw), "color": FLOW_INK},
            name=f"{gw} GW",
        )
    fig.add_annotation(
        x=10.45,
        y=51.15,
        text="<b>DE</b>",
        showarrow=False,
        font={"color": "white", "size": 17},
    )
    fig.update_layout(
        height=400,
        margin={"l": 0, "r": 0, "t": 3, "b": 28},
        plot_bgcolor="#171c22",
        paper_bgcolor="rgba(0,0,0,0)",
        hovermode="closest",
        hoverdistance=12,
        hoverlabel={
            "bgcolor": "#20252d",
            "bordercolor": "#535c68",
            "font": {"color": "#f5faf8"},
        },
        legend={
            "orientation": "h",
            "x": 1,
            "xanchor": "right",
            "y": -0.015,
            "yanchor": "top",
            "bgcolor": "rgba(0,0,0,0)",
            "font": {"color": "#9da5b0", "size": 11},
            "itemclick": False,
            "itemdoubleclick": False,
        },
        clickmode="event+select",
        dragmode=False,
        xaxis={"range": [1, 21], "visible": False, "fixedrange": True},
        yaxis={"range": [45.5, 60.6], "visible": False, "fixedrange": True},
    )
    return fig
