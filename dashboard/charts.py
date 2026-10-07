"""Altair charts. One axis per chart, thin marks, tooltips on every mark, text in ink colours.
Single-series charts use one hue; rating polarity uses blue (positive) / grey (neutral) /
orange (negative) plus a shape so identity never depends on colour alone."""
from __future__ import annotations

import altair as alt
import pandas as pd

BLUE = "#2a78d6"
ORANGE = "#eb6834"
GREY = "#898781"
MUTED = "#898781"

ACTION_COLOR = {"BUY": BLUE, "ACCUMULATE": BLUE, "HOLD": GREY, "NEUTRAL": GREY, "UNMAPPED": GREY,
                "REDUCE": ORANGE, "SELL": ORANGE}
ACTION_SHAPE = {"BUY": "triangle-up", "ACCUMULATE": "circle", "HOLD": "square", "NEUTRAL": "square",
                "UNMAPPED": "cross", "REDUCE": "circle", "SELL": "triangle-down"}


def _axis(**kw) -> alt.Axis:
    style = {"labelColor": MUTED, "titleColor": MUTED, "gridColor": "#e6e5e0", "gridOpacity": 0.4, "domain": False,
             "tickColor": "#e6e5e0"}
    return alt.Axis(**{**style, **kw})


def price_line(prices: pd.DataFrame) -> alt.Chart:
    df = prices.assign(trade_date=pd.to_datetime(prices["trade_date"]))
    hover = alt.selection_point(fields=["trade_date"], nearest=True, on="pointerover", empty=False)
    base = alt.Chart(df).encode(x=alt.X("trade_date:T", title=None, axis=_axis(format="%d %b")))
    line = base.mark_line(color=BLUE, strokeWidth=2).encode(
        y=alt.Y("close:Q", title="Close (₹, NSE EOD)", scale=alt.Scale(zero=False), axis=_axis()))
    points = base.mark_point(color=BLUE, filled=True, size=70).encode(
        y="close:Q", opacity=alt.condition(hover, alt.value(1), alt.value(0)),
        tooltip=[alt.Tooltip("trade_date:T", title="Date", format="%d %b %Y"),
                 alt.Tooltip("close:Q", title="Close ₹", format=",.2f"),
                 alt.Tooltip("volume:Q", title="Volume", format=",")]).add_params(hover)
    rule = base.mark_rule(color=MUTED, strokeWidth=1).encode(
        opacity=alt.condition(hover, alt.value(0.6), alt.value(0))).transform_filter(hover)
    return (line + points + rule).properties(height=260)


def top_bars(df: pd.DataFrame, value: str, value_title: str, fmt: str = ",.0f") -> alt.Chart:
    return alt.Chart(df).mark_bar(color=BLUE, cornerRadiusEnd=4, size=14).encode(
        x=alt.X(f"{value}:Q", title=value_title, axis=_axis(format="~s")),
        y=alt.Y("symbol:N", sort="-x", title=None, axis=_axis(labelColor="#52514e")),
        tooltip=[alt.Tooltip("symbol:N", title="Symbol"), alt.Tooltip("name:N", title="Company"),
                 alt.Tooltip(f"{value}:Q", title=value_title, format=fmt)],
    ).properties(height=34 * len(df) + 20)


def target_history(recs: pd.DataFrame) -> alt.Chart | None:
    df = recs.dropna(subset=["target_price"])
    if df.empty:
        return None
    df = df.assign(published=pd.to_datetime(df["published_at"], utc=True).dt.tz_convert("Asia/Kolkata").dt.tz_localize(None),
                   brokerage=df["brokerage"].fillna("N/A"))
    actions = [a for a in ACTION_COLOR if a in set(df["normalized_action"])]
    return alt.Chart(df).mark_point(filled=True, size=110, stroke="#fcfcfb", strokeWidth=2).encode(
        x=alt.X("published:T", title=None, axis=_axis(format="%d %b %y")),
        y=alt.Y("target_price:Q", title="Published target (₹)", scale=alt.Scale(zero=False), axis=_axis()),
        color=alt.Color("normalized_action:N", title="Published rating",
                        scale=alt.Scale(domain=actions, range=[ACTION_COLOR[a] for a in actions])),
        shape=alt.Shape("normalized_action:N", scale=alt.Scale(domain=actions, range=[ACTION_SHAPE[a] for a in actions]),
                        legend=None),
        tooltip=[alt.Tooltip("published:T", title="Published", format="%d %b %Y"),
                 alt.Tooltip("brokerage:N", title="Brokerage"), alt.Tooltip("original_action:N", title="Rating (as published)"),
                 alt.Tooltip("target_price:Q", title="Target ₹", format=",.2f")],
    ).properties(height=240)
