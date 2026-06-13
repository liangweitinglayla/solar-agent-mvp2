import os
import re
import json
import pandas as pd
from dotenv import load_dotenv

from langchain_openai import ChatOpenAI
from langchain_core.tools import tool
from langgraph.prebuilt import create_react_agent

load_dotenv()

SCHEMA = """
Tables in the DuckDB database:

telemetry_minute(timestamp TIMESTAMP, inverter_id VARCHAR, active_power_kw DOUBLE, plant_id VARCHAR)
error_events(event_id VARCHAR, inverter_id VARCHAR, start_time TIMESTAMP, end_time TIMESTAMP, error_code VARCHAR, description VARCHAR, plant_id VARCHAR)
service_tickets(ticket_id VARCHAR, inverter_id VARCHAR, create_time TIMESTAMP, end_time TIMESTAMP, issue_category VARCHAR, status VARCHAR, plant_id VARCHAR)
solar_altitude(timestamp TIMESTAMP, altitude DOUBLE, plant_id VARCHAR)

Plants: 'Plant A' (2017-2026, ~11 inverters, full data), 'Plant B' (2018-2026, 107 inverters, telemetry only)
Energy: SUM(active_power_kw) / 12 = kWh  (5-minute intervals)
Peer baseline: AVG(active_power_kw) WHERE active_power_kw > 0 AND inverter_id != target_inverter
Daytime filter: JOIN solar_altitude ON timestamp + plant_id WHERE altitude >= 5
"""

SYSTEM_PROMPT = f"""You are an expert Solar Plant O&M analyst with access to 10 years of real data from two utility-scale PV plants.

{SCHEMA}

Guidelines:
- Write precise DuckDB SQL. Only SELECT is allowed.
- Always filter by plant_id unless comparing across plants.
- Format energy values as kWh with 1 decimal place.
- Be concise and actionable — you're talking to O&M engineers.
- If a query returns many rows, summarize the key insight rather than listing everything.
- After getting data, always provide a clear recommendation or interpretation.
"""


def build_om_agent(conn):
    """
    Build a LangGraph ReAct agent wired to the live DuckDB connection.
    Returns a compiled graph ready to invoke.
    """
    llm = ChatOpenAI(
        model="deepseek-chat",
        api_key=os.environ.get("DEEPSEEK_API_KEY"),
        base_url="https://api.deepseek.com",
        temperature=0,
    )

    @tool
    def query_database(sql: str) -> str:
        """Execute a SELECT SQL query on the solar plant DuckDB database. Returns results as a table or summary."""
        if not re.match(r"^\s*SELECT", sql, re.IGNORECASE):
            return "Error: only SELECT queries are permitted."
        try:
            df = conn.execute(sql).df()
            if df.empty:
                return "Query returned no results."
            # Return full table for small results, summary for large
            if len(df) <= 25:
                return df.to_string(index=False)
            else:
                return f"Query returned {len(df)} rows. First 10:\n{df.head(10).to_string(index=False)}"
        except Exception as e:
            return f"SQL error: {e}"

    @tool
    def get_schema() -> str:
        """Returns the database schema and usage guidelines."""
        return SCHEMA

    @tool
    def get_inverter_list(plant_id: str = "Plant A") -> str:
        """List all inverter IDs for a given plant."""
        try:
            df = conn.execute(
                "SELECT DISTINCT inverter_id FROM telemetry_minute WHERE plant_id = ? ORDER BY inverter_id",
                [plant_id]
            ).df()
            return ", ".join(df["inverter_id"].tolist())
        except Exception as e:
            return f"Error: {e}"

    agent = create_react_agent(
        llm,
        tools=[query_database, get_schema, get_inverter_list],
        prompt=SYSTEM_PROMPT,
    )
    return agent


def run_agent(agent, question: str) -> dict:
    """
    Run the agent on a question. Returns dict with:
      - answer: final text response
      - tool_calls: list of (tool_name, input, output) tuples
      - error: None or error string
    """
    try:
        result = agent.invoke(
            {"messages": [("human", question)]},
            config={"recursion_limit": 50},
        )
        messages = result["messages"]

        tool_calls = []
        final_answer = ""

        for msg in messages:
            # Tool call messages
            if hasattr(msg, "tool_calls") and msg.tool_calls:
                for tc in msg.tool_calls:
                    tool_calls.append({
                        "tool": tc["name"],
                        "input": tc["args"],
                        "output": None,
                    })
            # Tool result messages
            elif hasattr(msg, "name") and msg.name in ("query_database", "get_schema", "get_inverter_list"):
                if tool_calls:
                    tool_calls[-1]["output"] = msg.content
            # Final AI response
            elif hasattr(msg, "content") and msg.content and not getattr(msg, "tool_calls", None):
                final_answer = msg.content

        return {"answer": final_answer, "tool_calls": tool_calls, "error": None}

    except Exception as e:
        return {"answer": "", "tool_calls": [], "error": str(e)}
