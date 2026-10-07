"""Shared Streamlit rendering pieces."""
from __future__ import annotations

import html

import pandas as pd
import streamlit as st

from dashboard import formatting as fmt
from dashboard import nav

DISCLAIMER = (
    "Information aggregator for research only — **not investment advice**. Ratings, targets and stop losses shown are "
    "those **published by the named third parties**; this dashboard does not make its own recommendations. "
    "Always verify with the original source."
)

LINK = st.column_config.LinkColumn

# NSE "Indices eligible in derivatives" + India VIX
INDICES = ("Nifty 50", "Nifty Bank", "Nifty Financial Services", "Nifty Midcap Select", "Nifty Next 50",
           "Nifty India FPI 150", "India VIX")


def _index_source_caption(levels: pd.DataFrame) -> str:
    live, eod = levels[levels["kind"] == "live"], levels[levels["kind"] == "eod"]
    parts = []
    if not live.empty:
        parts.append(f"🟢 LIVE — as of {fmt.ist(live['bar_time'].max())} "
                     f"({', '.join(sorted(live['source'].unique()))}; worker updates every 5 min, page every 60 s)")
    if not eod.empty:
        parts.append(f"NSE EOD close as of {eod['as_of'].max()} for: {', '.join(eod['index_name'])}")
    return " · ".join(parts)


def live_index_tiles() -> bool:
    """Latest NSE levels for INDICES as compact tiles. Call from inside an auto-refreshing fragment."""
    from dashboard import queries as q

    levels = q.live_index_levels(INDICES)
    if levels.empty:
        st.info("Index data not loaded yet — start the worker, or run `python worker.py --once --job technical`.")
        return False
    by_name = {r.index_name: r for r in levels.itertuples()}
    shown = [n for n in INDICES if n in by_name]
    tiles = st.container(key="ov_indices")  # compact 16px numbers (style.CSS)
    for start in range(0, len(shown), 7):
        cols = tiles.columns(7)
        for col, name in zip(cols, shown[start:start + 7]):
            r = by_name[name]
            change = None
            if pd.notna(r.change_pct):
                change = fmt.pct(r.change_pct)
                if pd.notna(r.prev_close) and pd.notna(r.close):
                    change += f" ({r.close - r.prev_close:+,.2f})"
            col.metric(name, f"{r.close:,.2f}" if r.close is not None else "N/A", change,
                       delta_color="inverse" if name == "India VIX" else "normal")
    st.caption(_index_source_caption(levels))
    return True


def open_stock(symbol: str) -> None:
    st.session_state["detail_symbol"] = symbol
    st.switch_page(nav.PAGES["detail"])


def rec_frame(df: pd.DataFrame) -> pd.DataFrame:
    """Display frame for recommendations (SOURCE RECOMMENDATIONS)."""
    out = pd.DataFrame({
        "Stock": df["stock"],
        "Symbol": df["symbol"],
        "Published rating": [fmt.action_label(n, o) for n, o in zip(df["normalized_action"], df["original_action"])],
        "Change": df["rating_change"].fillna("N/A"),
        "Brokerage": df["brokerage"].map(fmt.na),
        "Analyst": df["analyst"].map(fmt.na),
        "Target": df["target_price"].map(fmt.price),
        "Stop loss": df["stop_loss"].map(fmt.price),
        "Last close": [f"{fmt.price(c)} ({d})" if pd.notna(c) else "N/A" for c, d in zip(df["last_close"], df["close_date"])],
        "Upside/Downside %": [fmt.upside(t, c) for t, c in zip(df["target_price"], df["last_close"])],
        "Horizon": df["time_horizon_original"].map(fmt.na),
        "Published": df["published_at"].map(lambda v: fmt.ist(v, with_time=False)),
        "Source": df["source_name"].map(fmt.na),
        "Reported by": df["mentions"].map(lambda n: f"{n} article(s)"),
        "Extracted": df["extraction_method"],
        "Article": df["article_url"].map(fmt.safe_url),
    })
    return out


def rec_table(df: pd.DataFrame, key: str, selectable: bool = True):
    if df.empty:
        st.info("No published recommendations found for this selection.")
        return None
    return st.dataframe(
        rec_frame(df), key=key, hide_index=True, width="stretch",
        on_select="rerun" if selectable else "ignore", selection_mode="multi-row",
        column_config={
            "Upside/Downside %": st.column_config.NumberColumn(format="%+.1f%%", help="(target − last NSE close) / last close; N/A if either is missing"),
            "Article": LINK(display_text="Open ↗"),
            "Extracted": st.column_config.TextColumn(help="RULE = parsed from headline/snippet; AI = AI-extracted and verified verbatim; MANUAL = user import"),
        },
    )


def rec_evidence(df: pd.DataFrame, rows: list[int], mentions: pd.DataFrame) -> None:
    for i in rows:
        r = df.iloc[i]
        with st.container(border=True):
            st.markdown(f"**SOURCE RECOMMENDATION — {r['symbol']}: {r['original_action']}** "
                        f"({fmt.na(r['brokerage'])}{' / ' + r['analyst'] if pd.notna(r['analyst']) else ''})")
            st.caption("Evidence (verbatim text the rating was read from):")
            st.text(r["evidence_text"])
            if pd.notna(r["review_note"]):
                st.warning(r["review_note"])
            m = mentions[mentions["recommendation_id"] == r["id"]]
            for _, row in m.iterrows():
                url = fmt.safe_url(row["url"])
                tag = " · earliest report found" if row["is_original_source"] else ""
                label = f"{row['publisher']} — {fmt.ist(row['sort_ts'])}{tag}"
                if url:
                    st.markdown(f"- [{label}]({url}): {row['headline']}")


def news_list(df: pd.DataFrame, collapse_clusters: bool = True, limit: int = 100) -> None:
    if df.empty:
        st.info("No news for this selection yet.")
        return
    if collapse_clusters:
        df = df.drop_duplicates("story_cluster_id", keep="first")
    for _, row in df.head(limit).iterrows():
        url = fmt.safe_url(row["url"])
        symbols, snippet, ai_summary = (row.get(k) if isinstance(row.get(k), str) else None
                                        for k in ("symbols", "snippet", "ai_summary"))
        with st.container(border=True):
            head = f"[{row['headline']}]({url})" if url else row["headline"]
            st.markdown(head)
            extra = f" · +{int(row['cluster_size']) - 1} similar" if collapse_clusters and row["cluster_size"] > 1 else ""
            st.caption(f"{row['publisher']} · {fmt.ist(row['sort_ts'])} · {row['category']}"
                       f"{' · ' + symbols if symbols else ''}{extra}")
            if snippet:
                st.text(snippet)
            if ai_summary:
                st.caption("AI SUMMARY (machine-generated, may contain errors)")
                st.text(ai_summary)


def _md(text: str) -> str:
    """Stops '$' in headlines from being rendered as LaTeX."""
    return str(text).replace("$", r"\$")


def _mark(tone: int) -> str:
    return "🟢" if tone > 0 else "🔴" if tone < 0 else "🟡"


def key_points(drivers: list[dict], limit: int = 6) -> list[tuple[str, str]]:
    """At most `limit` one-line points: sectors, heavyweights, breadth, VIX, range, big movers."""
    def pick(prefix: str) -> list[dict]:
        return [d for d in drivers if d.get("kind") != "stock" and d["text"].startswith(prefix)]

    def merged(prefix: str) -> tuple[str, str] | None:
        ds = pick(prefix)
        if not ds:
            return None
        tone = sum(d["tone"] for d in ds)
        return _mark(tone), " · ".join(d["text"] for d in ds)

    points = [merged("Sector"), merged("Heavyweights"), merged("Breadth"), merged("India VIX"), merged("Nifty range")]
    stocks = [d for d in drivers if d.get("kind") == "stock"]
    if stocks:
        movers = ", ".join(d["text"].split(" · ")[0] for d in sorted(stocks, key=lambda d: d["tone"]))
        points.append((_mark(0), f"Big stock moves (±2%+): {movers}"))
    return [p for p in points if p][:limit]


def market_observation(obs: dict | None) -> None:
    """'Why is the market up / down / flat?' panel (see analysis/observation.py)."""
    from dashboard import style

    st.subheader("🧭 Market Observation — what is happening & why")
    if not obs:
        st.info("No intraday index data yet — the worker fills it every 5 minutes during market hours "
                "(or run `python worker.py --once --job technical`).")
        return
    color = {"UP": style.GREEN, "DOWN": style.RED}.get(obs["trend"], style.AMBER)
    icon = {"UP": "🟢 ▲", "DOWN": "🔴 ▼"}.get(obs["trend"], "🟡 ■")
    st.markdown(style.card(f"{icon} {obs['title']}", f"<div>{html.escape(obs['summary'])}</div>", color),
                unsafe_allow_html=True)
    left, right = st.columns([3, 2])
    with left:
        st.markdown("**Why — what is moving the index**")
        for mark, text in key_points(obs["drivers"]):
            st.markdown(f"{mark} {_md(text)}")
    with right:
        st.markdown("**News backdrop (last 18h)**")
        if not obs["backdrop"]:
            st.caption("No macro / global headlines found.")
        for b in obs["backdrop"]:
            st.markdown(f"{b['label']}")
            for e in b["evidence"]:
                url = fmt.safe_url(e.get("url"))
                st.caption(f"[{_md(e['headline'])}]({url}) — {e['publisher']}" if url else _md(e["headline"]))
    st.caption(f"As of {fmt.ist(obs.get('as_of'))} (last closed 5-min bar, {obs.get('source') or 'intraday'}). "
               "Rule-based reading of price data and headlines: it describes what is moving now, not where the market "
               "will go. Headlines are associations, not confirmed causes. Heavyweight point impact uses approximate "
               "Nifty weights (config/nifty_weights.yaml).")


def status_badge(status: str) -> str:
    return {"ACTIVE": "🟢 ACTIVE", "FAILED": "🔴 FAILED", "RATE_LIMITED": "🟠 RATE LIMITED", "NO_DATA": "⚪ NO DATA",
            "BLOCKED": "⛔ BLOCKED", "DISABLED": "⏸ DISABLED", "NEVER_RUN": "… NEVER RUN"}.get(status, status)
