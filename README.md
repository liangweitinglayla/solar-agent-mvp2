# Solar O&M Copilot MVP

This is the MVP repository for the Solar O&M Agent Hackathon. It provides a Streamlit-based web application that connects minute-resolution inverter telemetry, error codes, and service tickets to help O&M teams quickly identify inverter failures, calculate production impact, and get actionable advice via an LLM-powered agent.

## Project Structure
- `data/`: Place your raw CSV files here (`telemetry_minute.csv`, `error_events.csv`, `service_tickets.csv`).
- `src/`:
  - `data_pipeline.py`: Initializes DuckDB, loads CSVs, and creates wide tables.
  - `analytics_engine.py`: Executes DuckDB queries to calculate power loss and fetch event details.
  - `agent_core.py`: Assembles context and calls the OpenAI API to generate O&M insights.
- `app.py`: The Streamlit frontend.
- `requirements.txt`: Python dependencies.

## Quick Start
1. Install dependencies: `pip install -r requirements.txt`
2. Set your OpenAI API key: `export OPENAI_API_KEY='your-key-here'`
3. Place your data in the `data/` folder (or use the mock data generation script if available).
4. Run the app: `streamlit run app.py`

## Features
- **Impact Calculation**: Compares an inverter's actual power against a peer baseline to estimate lost kWh during an error event.
- **Visual Evidence**: Plotly charts showing the exact moment of failure.
- **Agent Insights**: Translates raw data and error codes into plain English summaries, likely causes, and suggested actions.
