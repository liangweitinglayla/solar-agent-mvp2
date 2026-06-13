import streamlit as st
import plotly.graph_objects as go
import plotly.express as px
import pandas as pd
import sys
import os

sys.path.append(os.path.join(os.path.dirname(__file__), "src"))
from data_pipeline import init_duckdb
from analytics_engine import AnalyticsEngine
from agent_core import OMAgent
from langgraph_agent import build_om_agent, run_agent
from pvlib_baseline import add_clearsky_to_df

st.set_page_config(page_title="Solar O&M Copilot", layout="wide")


@st.cache_resource
def setup():
    init_duckdb()
    engine = AnalyticsEngine()
    om_agent = OMAgent()
    lg_agent = build_om_agent(engine.conn)
    return engine, om_agent, lg_agent


@st.cache_data(ttl=300)
def load_events(_engine, plant_id):
    return _engine.get_events(plant_id)


engine, agent, lg_agent = setup()

# ── Plant selector (global, in sidebar) ─────────────────────────────────────
available_plants = engine.get_plants()
selected_plant = st.sidebar.selectbox("🌱 Plant", available_plants, index=0)

events_df = load_events(engine, selected_plant)

st.title("☀️ Solar O&M Copilot")

tab_dash, tab_inspect, tab_chat = st.tabs(["📊 Dashboard", "🔍 Fault Inspector", "💬 Ask the Data"])

# ── TAB 1: DASHBOARD ────────────────────────────────────────────────────────
with tab_dash:
    st.subheader(f"Plant Health Overview — {selected_plant}")

    with st.spinner("Computing plant-wide statistics..."):
        loss_summary = engine.get_inverter_loss_summary(selected_plant)
        top_events = engine.get_top_loss_events(selected_plant, n=10)
        recurring = engine.get_recurring_faults(selected_plant, min_occurrences=3)
        heatmap_df = engine.get_fault_heatmap(selected_plant)
        anomalies = engine.get_anomalies(selected_plant, days=30, threshold=0.15)

    # KPI cards
    total_faults = len(events_df)
    total_loss = loss_summary["total_loss_kwh"].sum() if not loss_summary.empty else 0
    worst_inv = loss_summary.iloc[0]["inverter_id"] if not loss_summary.empty else "—"
    worst_loss = loss_summary.iloc[0]["total_loss_kwh"] if not loss_summary.empty else 0

    k1, k2, k3, k4 = st.columns(4)
    k1.metric("Total Fault Events", f"{total_faults:,}")
    k2.metric("Est. Total Energy Loss", f"{total_loss:,.0f} kWh")
    k3.metric("Worst Inverter", worst_inv)
    k4.metric("Worst Inverter Loss", f"{worst_loss:,.0f} kWh")

    # Anomaly alerts banner
    if not anomalies.empty:
        st.markdown("---")
        st.subheader("🚨 Silent Underperformers — No Active Error Code")
        st.caption("Inverters producing >15% below fleet average over the last 30 days, with no logged fault.")
        a_cols = st.columns(min(len(anomalies), 4))
        for i, row in anomalies.iterrows():
            if i >= 4:
                break
            a_cols[i].metric(
                label=row["inverter_id"],
                value=f"{row['avg_power_kw']} kW",
                delta=f"-{row['underperformance_pct']}% vs fleet",
                delta_color="inverse",
            )
        if len(anomalies) > 4:
            anom_disp = anomalies.copy()
            anom_disp.columns = ["Inverter", "Avg Power (kW)", "Fleet Avg (kW)", "Underperformance (%)"]
            st.dataframe(anom_disp, use_container_width=True, hide_index=True)

        worst_inv_anom = anomalies.iloc[0]["inverter_id"]
        trend_df = engine.get_performance_trend(worst_inv_anom, selected_plant, days=90)
        if not trend_df.empty:
            fig_trend = px.line(
                trend_df, x="week", y="performance_ratio",
                title=f"{worst_inv_anom} — Weekly Performance vs Fleet (%) · Last 90 days",
                labels={"week": "Week", "performance_ratio": "Performance (% of fleet avg)"},
            )
            fig_trend.add_hline(y=100, line_dash="dash", line_color="green", annotation_text="Fleet average")
            fig_trend.add_hline(y=85, line_dash="dot", line_color="red", annotation_text="Alert threshold")
            fig_trend.update_layout(height=300, margin=dict(l=0, r=0, t=40, b=0))
            st.plotly_chart(fig_trend, use_container_width=True)

    st.markdown("---")
    col_left, col_right = st.columns(2)

    # Energy loss per inverter bar chart
    with col_left:
        st.subheader("Energy Loss by Inverter")
        if not loss_summary.empty:
            fig_bar = px.bar(
                loss_summary,
                x="inverter_id",
                y="total_loss_kwh",
                color="total_loss_kwh",
                color_continuous_scale="Reds",
                labels={"inverter_id": "Inverter", "total_loss_kwh": "Est. Loss (kWh)"},
            )
            fig_bar.update_layout(
                height=350,
                margin=dict(l=0, r=0, t=10, b=0),
                coloraxis_showscale=False,
                xaxis_tickangle=-45,
            )
            st.plotly_chart(fig_bar, use_container_width=True)

    # Fault frequency heatmap
    with col_right:
        st.subheader("Fault Frequency Heatmap")
        if not heatmap_df.empty:
            pivot = heatmap_df.pivot(
                index="inverter_id", columns="month", values="fault_count"
            ).fillna(0)
            fig_heat = go.Figure(
                go.Heatmap(
                    z=pivot.values,
                    x=pivot.columns.tolist(),
                    y=pivot.index.tolist(),
                    colorscale="YlOrRd",
                    hovertemplate="Inverter: %{y}<br>Month: %{x}<br>Faults: %{z}<extra></extra>",
                )
            )
            fig_heat.update_layout(
                height=350,
                margin=dict(l=0, r=0, t=10, b=0),
                xaxis=dict(tickangle=-45, nticks=12),
            )
            st.plotly_chart(fig_heat, use_container_width=True)

    st.markdown("---")

    # Top 10 highest-impact events
    st.subheader("⚡ Top 10 Highest-Impact Fault Events")
    if not top_events.empty:
        top_display = top_events.copy()
        top_display["start_time"] = pd.to_datetime(top_display["start_time"]).dt.strftime("%Y-%m-%d %H:%M")
        top_display["loss_kwh"] = top_display["loss_kwh"].round(1)
        top_display.columns = [
            "Event ID", "Inverter", "Start", "End", "Error Code", "Description", "Loss (kWh)"
        ]
        st.dataframe(top_display[["Event ID", "Inverter", "Start", "Error Code", "Description", "Loss (kWh)"]],
                     use_container_width=True, hide_index=True)

    st.markdown("---")

    # Recurring faults table
    st.subheader("🔁 Recurring Fault Patterns")
    if not recurring.empty:
        rec_display = recurring.copy()
        rec_display["first_seen"] = pd.to_datetime(rec_display["first_seen"]).dt.strftime("%Y-%m-%d")
        rec_display["last_seen"] = pd.to_datetime(rec_display["last_seen"]).dt.strftime("%Y-%m-%d")
        rec_display.columns = [
            "Inverter", "Error Code", "Description", "Occurrences",
            "Total Downtime (min)", "First Seen", "Last Seen"
        ]
        st.dataframe(rec_display, use_container_width=True, hide_index=True)


# ── TAB 2: FAULT INSPECTOR ─────────────────────────────────────────────────
with tab_inspect:
    st.sidebar.header("🔍 Filter Events")

    all_inverters = sorted(events_df["inverter_id"].unique().tolist())
    selected_inverters = st.sidebar.multiselect(
        "Inverter", all_inverters, placeholder="All inverters"
    )

    import datetime
    min_date = events_df["start_time"].min().date() if not events_df.empty else datetime.date(2017, 1, 1)
    max_date = events_df["start_time"].max().date() if not events_df.empty else datetime.date.today()
    date_range = st.sidebar.date_input(
        "Date Range",
        value=(min_date, max_date),
        min_value=min_date,
        max_value=max_date,
    )

    keyword = st.sidebar.text_input("Search description / error code", "")

    filtered = events_df.copy()

    if selected_inverters:
        filtered = filtered[filtered["inverter_id"].isin(selected_inverters)]

    if isinstance(date_range, (list, tuple)) and len(date_range) == 2:
        filtered = filtered[
            (filtered["start_time"].dt.date >= date_range[0])
            & (filtered["start_time"].dt.date <= date_range[1])
        ]

    if keyword:
        mask = filtered["description"].str.contains(
            keyword, case=False, na=False
        ) | filtered["error_code"].str.contains(keyword, case=False, na=False)
        filtered = filtered[mask]

    if events_df.empty:
        st.info("No fault event data available for Plant B — the dataset only includes telemetry. Use the Dashboard tab for anomaly detection or Ask the Data for custom queries.")
        st.stop()

    st.subheader(f"📋 Fault Events  —  {len(filtered):,} found")

    display_df = filtered[
        ["event_id", "inverter_id", "start_time", "end_time", "error_code", "description"]
    ].copy()
    display_df["start_time"] = display_df["start_time"].dt.strftime("%Y-%m-%d %H:%M")
    display_df["end_time"] = display_df["end_time"].dt.strftime("%Y-%m-%d %H:%M")
    display_df.columns = ["ID", "Inverter", "Start", "End", "Error Code", "Description"]

    selection = st.dataframe(
        display_df,
        use_container_width=True,
        hide_index=True,
        on_select="rerun",
        selection_mode="single-row",
        height=320,
    )

    if not selection.selection.rows:
        st.info("👆 Click a row above to analyze the event in detail.")
    else:
        row_idx = selection.selection.rows[0]
        selected_event_id = filtered.iloc[row_idx]["event_id"]

        st.markdown("---")

        with st.spinner("Analyzing data and calculating impact..."):
            event_details = engine.get_event_details(selected_event_id)
            loss_kwh, ts_df = engine.calculate_impact(
                event_details["inverter_id"],
                event_details["start_time"],
                event_details["end_time"],
            )
            ts_df = add_clearsky_to_df(ts_df, event_details["inverter_id"], selected_plant)

        col1, col2, col3, col4 = st.columns(4)
        col1.metric("Inverter", event_details["inverter_id"])
        col2.metric("Error Code", event_details["error_code"])
        col3.metric("Est. Energy Loss", f"{loss_kwh:.2f} kWh")
        col4.metric("Linked Ticket", event_details.get("ticket_id") or "—")

        st.markdown("---")

        st.subheader("📈 Power Output vs Peer Baseline")

        fig = go.Figure()
        fig.add_trace(
            go.Scatter(
                x=ts_df["timestamp"],
                y=ts_df["baseline_power"],
                mode="lines",
                name="Peer Baseline (Expected)",
                line=dict(dash="dash", color="gray"),
            )
        )
        fig.add_trace(
            go.Scatter(
                x=ts_df["timestamp"],
                y=ts_df["actual_power"],
                mode="lines",
                name="Actual Power",
                line=dict(color="royalblue"),
            )
        )
        fig.add_trace(
            go.Scatter(
                x=ts_df["timestamp"],
                y=ts_df["clearsky_power"],
                mode="lines",
                name="Clear-sky Expected (pvlib)",
                line=dict(dash="dot", color="orange"),
            )
        )
        fig.add_vrect(
            x0=event_details["start_time"],
            x1=event_details["end_time"],
            fillcolor="red",
            opacity=0.15,
            layer="below",
            line_width=0,
            annotation_text="Error Window",
            annotation_position="top left",
        )
        fig.update_layout(
            height=400,
            margin=dict(l=0, r=0, t=30, b=0),
            yaxis_title="Active Power (kW)",
            legend=dict(orientation="h", yanchor="bottom", y=1.02),
        )
        st.plotly_chart(fig, use_container_width=True)

        st.subheader("🤖 Agent Insights & Recommendations")

        cache_key = f"insights_{selected_event_id}"
        if cache_key not in st.session_state:
            with st.spinner("Generating AI insights..."):
                st.session_state[cache_key] = agent.generate_insights(event_details, loss_kwh)

        insights = st.session_state[cache_key]
        st.info(f"**Incident Summary:** {insights.get('incident_summary')}")
        st.warning(f"**Likely Cause:** {insights.get('likely_cause')}")
        st.success(f"**Suggested Action:** {insights.get('suggested_action')}")
        st.caption(f"Agent Confidence: {insights.get('confidence')}")


# ── TAB 3: CHAT (LangGraph ReAct Agent) ────────────────────────────────────
with tab_chat:
    st.subheader("💬 Ask the Plant Data")
    st.caption(
        "Powered by a **LangGraph ReAct agent** — it plans, queries the live database, "
        "and reasons across multiple steps to answer your question."
    )

    EXAMPLE_QUESTIONS = [
        "Which inverter had the most fault events in Plant A?",
        "Find the inverter with the highest total energy loss, then show its top 3 fault events",
        "Compare average power output of Plant A vs Plant B in 2023",
        "Which error code caused the most total downtime?",
        "Are there any open service tickets? Which inverter has the most?",
    ]

    if "chat_history" not in st.session_state:
        st.session_state.chat_history = []

    st.markdown("**Try an example:**")
    cols = st.columns(len(EXAMPLE_QUESTIONS))
    for i, q in enumerate(EXAMPLE_QUESTIONS):
        if cols[i].button(q, key=f"ex_{i}", use_container_width=True):
            st.session_state.pending_question = q

    st.markdown("---")

    # Render chat history
    for msg in st.session_state.chat_history:
        with st.chat_message(msg["role"]):
            st.markdown(msg["content"])
            if msg.get("tool_calls"):
                for tc in msg["tool_calls"]:
                    with st.expander(f"🔧 Tool: `{tc['tool']}`", expanded=False):
                        if tc["tool"] == "query_database":
                            st.code(tc["input"].get("sql", ""), language="sql")
                        if tc.get("output"):
                            st.text(tc["output"][:500] + ("..." if len(str(tc["output"])) > 500 else ""))

    def _run_and_append(question: str):
        st.session_state.chat_history.append({"role": "user", "content": question})
        with st.spinner("Agent is thinking... (may take 10-20s for multi-step questions)"):
            result = run_agent(lg_agent, question)
        if result["error"]:
            reply = {"role": "assistant", "content": f"Sorry, I hit an error: {result['error']}", "tool_calls": []}
        else:
            reply = {"role": "assistant", "content": result["answer"], "tool_calls": result["tool_calls"]}
        st.session_state.chat_history.append(reply)
        st.rerun()

    if "pending_question" in st.session_state:
        _run_and_append(st.session_state.pop("pending_question"))

    user_input = st.chat_input("Ask anything about the plant data...")
    if user_input:
        _run_and_append(user_input)
