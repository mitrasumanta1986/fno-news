from __future__ import annotations

import pandas as pd
import streamlit as st

from dashboard import components as ui
from dashboard import formatting as fmt
from dashboard import queries as q


def render() -> None:
    st.title("Source Status")
    src = q.sources()
    table = pd.DataFrame({
        "Source": src["name"],
        "Status": src["status"].map(ui.status_badge),
        "Last success": src["last_success_at"].map(fmt.ist),
        "Last attempt": src["last_attempt_at"].map(fmt.ist),
        "Items (24h)": src["items_24h"],
        "Consecutive failures": src["consecutive_failures"],
        "Next allowed fetch": src["next_allowed_fetch_at"].map(fmt.ist),
        "Last error": src["last_error"].map(fmt.na),
        "Notes": src["notes"].map(fmt.na),
        "Access reviewed": src["tos_checked"].map(fmt.na),
    })
    st.dataframe(table, hide_index=True, width="stretch",
                 column_config={"Last error": st.column_config.TextColumn(width="large"),
                                "Notes": st.column_config.TextColumn(width="large")})
    st.caption("ACTIVE = last fetch succeeded · NO DATA = fetched but empty · FAILED = error (retried with backoff) · "
               "RATE LIMITED = publisher asked us to slow down · BLOCKED = robots.txt disallows or publisher refuses "
               "automated access (never circumvented) · DISABLED = turned off in config/sources.yaml")

    st.subheader("Recent fetch log")
    logs = q.fetch_logs(300)
    if not logs.empty:
        logs = logs.assign(started_at=logs["started_at"].map(fmt.ist))
    st.dataframe(logs, hide_index=True, width="stretch", height=400)
