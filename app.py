import streamlit as st
import plotly.graph_objects as go
import sys
import os

# Ensure src modules can be imported
sys.path.append(os.path.join(os.path.dirname(__file__), "src"))
from data_pipeline import init_duckdb
from analytics_engine import AnalyticsEngine
from agent_core import OMAgent

st.set_page_config(page_title="Solar O&M Copilot", layout="wide")

@st.cache_resource
def setup():
    init_duckdb()
    return AnalyticsEngine(), OMAgent()

engine, agent = setup()

st.title("☀️ Solar O&M Copilot")

# --- Sidebar: Event Selection ---
st.sidebar.header("Incident Selection")
events_df = engine.get_events()

if events_df.empty:
    st.error("No events found in database.")
    st.stop()

# Create a friendly label for the dropdown
events_df['label'] = events_df['inverter_id'] + " | " + events_df['error_code'] + " (" + events_df['start_time'].astype(str) + ")"
selected_label = st.sidebar.selectbox("Select an Event to Analyze:", events_df['label'])

# Get the selected event_id
selected_event_id = events_df[events_df['label'] == selected_label]['event_id'].values[0]

# --- Main Logic ---
with st.spinner("Analyzing data and calculating impact..."):
    event_details = engine.get_event_details(selected_event_id)
    loss_kwh, ts_df = engine.calculate_impact(
        event_details['inverter_id'], 
        event_details['start_time'], 
        event_details['end_time']
    )

# --- Top Area: Summary Cards ---
col1, col2, col3, col4 = st.columns(4)
col1.metric("Inverter", event_details['inverter_id'])
col2.metric("Error Code", event_details['error_code'])
col3.metric("Est. Energy Loss", f"{loss_kwh:.2f} kWh")
col4.metric("Linked Ticket", event_details.get('ticket_id', 'None'))

st.markdown("---")

# --- Middle Area: Visualization ---
st.subheader("Visual Evidence: Power Output vs Baseline")

fig = go.Figure()
fig.add_trace(go.Scatter(x=ts_df['timestamp'], y=ts_df['baseline_power'], mode='lines', name='Peer Baseline (Expected)', line=dict(dash='dash', color='gray')))
fig.add_trace(go.Scatter(x=ts_df['timestamp'], y=ts_df['actual_power'], mode='lines', name='Actual Power', line=dict(color='blue')))

# Highlight the error window
fig.add_vrect(
    x0=event_details['start_time'], x1=event_details['end_time'],
    fillcolor="red", opacity=0.2, layer="below", line_width=0,
    annotation_text="Error Window", annotation_position="top left"
)

fig.update_layout(height=400, margin=dict(l=0, r=0, t=30, b=0), yaxis_title="Active Power (kW)")
st.plotly_chart(fig, use_container_width=True)

# --- Bottom Area: Agent Insights ---
st.subheader("🤖 Agent Insights & Recommendations")

with st.spinner("Generating AI insights..."):
    insights = agent.generate_insights(event_details, loss_kwh)

st.info(f"**Incident Summary:** {insights.get('incident_summary')}")
st.warning(f"**Likely Cause:** {insights.get('likely_cause')}")
st.success(f"**Suggested Action:** {insights.get('suggested_action')}")
st.caption(f"Agent Confidence Level: {insights.get('confidence')}")
