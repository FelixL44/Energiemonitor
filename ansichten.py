import json
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
    return 1.2 + 2.5 * abs(gw)


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
                line={"width": 0.7, "color": "#41545d"},
                showlegend=False,
                fillcolor="#355751" if name == "Germany" else "#22333c",
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
        a, b = (0.11, 0.80) if value > 0 else (0.80, 0.11)
        pts = [a + (b - a) * i / 40 for i in range(41)]
        color = "#64deba" if value > 0 else "#ffc368"
        width = arrow_width(value)
        fig.add_scatter(
            x=[x + (10.45 - x) * f for f in pts],
            y=[y + (51.15 - y) * f for f in pts],
            mode="lines+markers",
            showlegend=False,
            name=name,
            customdata=[details] * 41,
            line={"width": width, "color": color, "simplify": False},
            marker={
                "symbol": ["circle"] * 40 + ["arrow"],
                "angleref": "previous",
                "size": [16] * 40 + [9 + width * 1.6],
                "line": {"width": 0},
                "color": ["rgba(0,0,0,0)"] * 40 + [color],
            },
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
        marker={"size": 7, "color": "#d9e5e6"},
        text=codes,
        textposition="top center",
        textfont={"color": "#e9f2f3", "size": 12},
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
            line={"width": arrow_width(gw), "color": "#afbdc4"},
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
        margin={"l": 0, "r": 0, "t": 3, "b": 4},
        plot_bgcolor="#142229",
        hovermode="closest",
        hoverdistance=12,
        hoverlabel={
            "bgcolor": "#122128",
            "bordercolor": "#72918d",
            "font": {"color": "#f5faf8"},
        },
        legend={
            "orientation": "h",
            "x": 0.01,
            "y": 0.005,
            "bgcolor": "#142229",
            "font": {"color": "#d9e5e6"},
            "itemclick": False,
            "itemdoubleclick": False,
        },
        clickmode="event+select",
        dragmode=False,
        xaxis={"range": [1, 21], "visible": False, "fixedrange": True},
        yaxis={"range": [45.5, 60.6], "visible": False, "fixedrange": True},
    )
    return fig
