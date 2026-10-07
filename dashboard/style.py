"""Colour theme: gradient headings, tinted metric cards, coloured pills and table cells.

Colours carry meaning consistently: green = up/bullish/positive published rating, red = down/bearish/negative,
amber = neutral/caution, blue/violet = informational. Every coloured value also carries a sign, icon or word,
so meaning never depends on colour alone. Tints are translucent so they work in light and dark mode.
"""
from __future__ import annotations

import html

import pandas as pd
import streamlit as st

GREEN, RED, AMBER, BLUE, VIOLET, GREY = "#16a34a", "#dc2626", "#d97706", "#2a78d6", "#7c3aed", "#6b7280"

CSS = """
<style>
h1 {
  background: linear-gradient(90deg, #2a78d6 0%, #7c3aed 55%, #eb6834 100%);
  -webkit-background-clip: text; background-clip: text; color: transparent !important; font-weight: 800 !important;
}
h2, h3 { color: #2a78d6 !important; }
[data-testid="stMetric"] {
  background: linear-gradient(135deg, rgba(42,120,214,.13), rgba(124,58,237,.10));
  border: 1px solid rgba(42,120,214,.28); border-radius: 14px; padding: 10px 14px;
}
.st-key-ov_indices [data-testid="stMetric"] { padding: 6px 10px; }
.st-key-ov_indices [data-testid="stMetricValue"], .st-key-ov_indices [data-testid="stMetricValue"] * {
  font-size: 16px !important; line-height: 1.3 !important; }
.st-key-ov_indices [data-testid="stMetricLabel"] *, .st-key-ov_indices [data-testid="stMetricDelta"] * {
  font-size: 13px !important; }
[data-testid="stSidebar"] { background: linear-gradient(180deg, rgba(42,120,214,.12), rgba(124,58,237,.08) 60%, rgba(235,104,52,.08)); }
.stTabs [data-baseweb="tab"][aria-selected="true"] { color: #7c3aed !important; }
.stTabs [data-baseweb="tab-highlight"] { background-color: #7c3aed !important; }
.fno-pill { display:inline-block; padding:2px 10px; border-radius:999px; font-size:.82rem; font-weight:600; margin:2px 4px 2px 0; }
.fno-card { border-radius:14px; padding:12px 14px; margin-bottom:10px; border:1px solid rgba(127,127,127,.25); }
.fno-card h4 { margin:0 0 6px 0; font-size:1rem; }
.fno-bar { display:flex; height:22px; border-radius:8px; overflow:hidden; font-size:.78rem; font-weight:700; color:#fff; }
.fno-bar div { display:flex; align-items:center; justify-content:center; }
.fno-banner { border-radius:16px; padding:14px 18px; margin:4px 0 14px 0; color:#fff;
  background: linear-gradient(100deg, #1d4ed8 0%, #7c3aed 55%, #db2777 100%); }
.fno-banner b { font-size:1.05rem; }
</style>
"""


def inject() -> None:
    st.markdown(CSS, unsafe_allow_html=True)


def pill(text: str, color: str) -> str:
    """Internal labels only; text is escaped."""
    return (f'<span class="fno-pill" style="background:{color}22;color:{color};border:1px solid {color}66">'
            f"{html.escape(str(text))}</span>")


def banner(text: str) -> None:
    st.markdown(f'<div class="fno-banner">{html.escape(text)}</div>', unsafe_allow_html=True)


def card(title: str, body_html: str, color: str) -> str:
    return (f'<div class="fno-card" style="background:{color}14;border-left:5px solid {color}">'
            f"<h4 style='color:{color}'>{html.escape(title)}</h4>{body_html}</div>")


def ratio_bar(parts: list[tuple[str, int, str]]) -> None:
    total = sum(p[1] for p in parts) or 1
    cells = "".join(f'<div style="width:{max(v / total * 100, 6 if v else 0):.1f}%;background:{c}">{html.escape(label)} {v}</div>'
                    for label, v, c in parts if v)
    st.markdown(f'<div class="fno-bar">{cells}</div>', unsafe_allow_html=True)


def tone_for(value) -> str:
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return GREY
    return GREEN if value > 0 else RED if value < 0 else GREY


# ---- pandas Styler helpers (cell colours in st.dataframe) ----------------------------------------
def _cell(color: str) -> str:
    return f"background-color: {color}26; color: {color}; font-weight: 600"


def color_change(v) -> str:
    if v is None or pd.isna(v):
        return ""
    return _cell(GREEN) if v > 0 else _cell(RED) if v < 0 else ""


WORD_COLORS = [
    (("bullish", "strong up", "above", "high roe", "earnings growing", "buy", "accumulate", "outperform", "positive", "up-trend"), GREEN),
    (("bearish", "strong down", "below", "low roe", "earnings falling", "sell", "reduce", "underperform", "negative", "down-trend", "loss"), RED),
    (("neutral", "hold", "inside", "no setup", "moderate", "mild", "flat", "quiet"), AMBER),
    (("high",), VIOLET), (("medium",), BLUE), (("low",), GREY),
]


def color_words(v) -> str:
    if not isinstance(v, str):
        return ""
    low = v.lower()
    for words, color in WORD_COLORS:
        if any(w in low for w in words):
            return _cell(color)
    return ""


def styled(df: pd.DataFrame, change_cols=(), word_cols=(), formats: dict | None = None):
    s = df.style
    if change_cols:
        s = s.map(color_change, subset=[c for c in change_cols if c in df])
    if word_cols:
        s = s.map(color_words, subset=[c for c in word_cols if c in df])
    if formats:
        s = s.format({k: v for k, v in formats.items() if k in df}, na_rep="N/A")
    return s
