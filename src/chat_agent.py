import os
import json
import re
import pandas as pd
from openai import OpenAI
from dotenv import load_dotenv

load_dotenv()

SCHEMA = """
You have access to a DuckDB database with the following tables:

TABLE: telemetry_minute
  - timestamp       TIMESTAMP   (5-minute intervals, Europe/Berlin local time, no timezone)
  - inverter_id     VARCHAR     (e.g. "INV 01.1", "INV 02.1" — use LIKE 'INV%' to match all)
  - active_power_kw DOUBLE      (instantaneous AC power output in kilowatts)

TABLE: error_events
  - event_id        VARCHAR     (e.g. "E-00001")
  - inverter_id     VARCHAR     (matches telemetry_minute.inverter_id)
  - start_time      TIMESTAMP
  - end_time        TIMESTAMP
  - error_code      VARCHAR     (hex string, e.g. "0040023")
  - description     VARCHAR     (human-readable error description)

TABLE: service_tickets
  - ticket_id       VARCHAR     (e.g. "T-0001")
  - inverter_id     VARCHAR
  - create_time     TIMESTAMP
  - end_time        TIMESTAMP   (NULL if still open)
  - issue_category  VARCHAR
  - status          VARCHAR     ("Open" or "Closed")

TABLE: solar_altitude
  - timestamp       TIMESTAMP
  - altitude        DOUBLE      (solar elevation angle in degrees; negative = nighttime)

IMPORTANT RULES:
- Data covers Plant A (2017–2026, ~11 inverters, has error_events + service_tickets) and Plant B (2018–2026, 108 inverters, telemetry only).
- Always filter by plant_id (e.g. WHERE plant_id = 'Plant A') unless the question explicitly asks for cross-plant comparison.
- Energy (kWh) = SUM(active_power_kw) / 12  (5-min intervals = 1/12 hour each)
- Always JOIN solar_altitude ON timestamp AND altitude >= 0 when computing energy or losses to exclude nighttime.
- For peer baseline: AVG(active_power_kw) across all OTHER inverter_ids at the same timestamp, WHERE active_power_kw > 0 (exclude silent zeros from peers).
- All timestamps are naive (no timezone suffix). Use CAST('2023-01-01' AS TIMESTAMP) style.
- Return only SELECT queries. Never use INSERT, UPDATE, DELETE, DROP.
"""

SYSTEM_PROMPT = f"""You are an expert Solar Plant O&M data analyst with deep knowledge of SQL and photovoltaic systems.

{SCHEMA}

When the user asks a question:
1. Think about which tables and joins are needed.
2. Return a JSON object with these fields:
   {{
     "sql": "<valid DuckDB SELECT query>",
     "answer_template": "<one sentence describing what the query will show, with {{RESULT}} as placeholder for the key number or table>",
     "chart_type": "bar" | "line" | "table" | "none",
     "chart_x": "<column name for x-axis, or null>",
     "chart_y": "<column name for y-axis, or null>",
     "chart_title": "<short chart title>"
   }}

Keep SQL concise. Limit results to 20 rows unless the user asks for more.
"""


class ChatAgent:
    def __init__(self):
        self._client = None

    @property
    def client(self):
        if self._client is None:
            self._client = OpenAI(
                api_key=os.environ.get("DEEPSEEK_API_KEY"),
                base_url="https://api.deepseek.com",
            )
        return self._client

    def ask(self, question: str, conn) -> dict:
        """
        Takes a natural language question, generates SQL, executes it,
        and returns a dict with: answer, dataframe, chart_type, chart_x, chart_y, chart_title, error
        """
        try:
            response = self.client.chat.completions.create(
                model="deepseek-chat",
                messages=[
                    {"role": "system", "content": SYSTEM_PROMPT},
                    {"role": "user", "content": question},
                ],
                response_format={"type": "json_object"},
            )
            plan = json.loads(response.choices[0].message.content)
        except Exception as e:
            return {"error": f"LLM error: {e}", "sql": "", "df": None}

        sql = plan.get("sql", "").strip()

        # Safety: only allow SELECT
        if not re.match(r"^\s*SELECT", sql, re.IGNORECASE):
            return {"error": "Query was not a SELECT statement — blocked for safety.", "sql": sql, "df": None}

        try:
            df = conn.execute(sql).df()
        except Exception as e:
            # Send the error back to the LLM for self-correction (one retry)
            try:
                retry = self.client.chat.completions.create(
                    model="deepseek-chat",
                    messages=[
                        {"role": "system", "content": SYSTEM_PROMPT},
                        {"role": "user", "content": question},
                        {"role": "assistant", "content": response.choices[0].message.content},
                        {"role": "user", "content": f"That SQL failed with: {e}\nPlease fix it and return corrected JSON."},
                    ],
                    response_format={"type": "json_object"},
                )
                plan = json.loads(retry.choices[0].message.content)
                sql = plan.get("sql", "").strip()
                df = conn.execute(sql).df()
            except Exception as e2:
                return {"error": f"SQL error (after retry): {e2}", "sql": sql, "df": None}

        # Build a plain-English answer from the template
        answer_template = plan.get("answer_template", "")
        if not df.empty and len(df) == 1 and len(df.columns) == 1:
            key_val = df.iloc[0, 0]
            if isinstance(key_val, float):
                key_val = f"{key_val:,.1f}"
            answer = answer_template.replace("{RESULT}", str(key_val))
        else:
            answer = answer_template.replace("{RESULT}", f"{len(df)} rows")

        return {
            "answer": answer,
            "sql": sql,
            "df": df,
            "chart_type": plan.get("chart_type", "table"),
            "chart_x": plan.get("chart_x"),
            "chart_y": plan.get("chart_y"),
            "chart_title": plan.get("chart_title", ""),
            "error": None,
        }
