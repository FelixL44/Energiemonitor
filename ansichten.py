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
                line={"width": 0.65, "color": "#475862"},
                fillcolor="#335451" if name == "Germany" else "#24343d",
            )
    labels = []
    for name, code, x, y in LAND.values():
        v = row.get(code)
        valid = pd.notna(v)
        if valid and v != 0:
            dx, dy = 10.45 - x, 51.15 - y
            a, b = (0.14, 0.78) if v > 0 else (0.78, 0.14)
            fig.add_annotation(
                x=x + dx * b,
                y=y + dy * b,
                ax=x + dx * a,
                ay=y + dy * a,
                xref="x",
                yref="y",
                axref="x",
                ayref="y",
                showarrow=True,
                arrowhead=3,
                arrowsize=1.3,
                arrowwidth=min(4, 1 + abs(v) * 0.55),
                arrowcolor="#64d6ae" if v > 0 else "#f4be67",
                text="",
            )
        labels.append(
            (
                x,
                y,
                code,
                name,
                "Daten fehlen"
                if not valid
                else f"{abs(v):.2f} GW "
                + ("Import" if v > 0 else "Export" if v < 0 else "Saldo null"),
            )
        )
    xs, ys, codes, names, details = zip(*labels)
    fig.add_scatter(
        x=xs,
        y=ys,
        mode="markers+text",
        marker={"size": 10, "color": "#d9e5e6"},
        text=codes,
        textposition="top center",
        customdata=list(zip(codes, names, details)),
        hovertemplate="%{customdata[1]} · %{customdata[2]}<extra></extra>",
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
        margin={"l": 0, "r": 0, "t": 0, "b": 0},
        showlegend=False,
        plot_bgcolor="#142229",
        clickmode="event+select",
        dragmode=False,
        xaxis={"range": [1, 21], "visible": False, "fixedrange": True},
        yaxis={"range": [45.7, 60.6], "visible": False, "fixedrange": True},
    )
    return fig
